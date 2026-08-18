#!/usr/bin/env python3
"""Serve the fine-tuned persona behind the same API the rest of the system already speaks.

Everything here talks to Ollama through an OpenAI-shaped client. Rather than convert the adapter
to GGUF and import it — a conversion step that would have to be redone after every training run —
this serves the adapter directly and answers on the same endpoint shape, so switching is one
environment variable:

    set OLLAMA_BASE_URL=http://127.0.0.1:11435/v1

The base is loaded in 4-bit and the LoRA adapter on top, which is about 5.5 GB resident and
leaves room for CosyVoice on the same 12 GB card.

## One generation at a time

A single GPU cannot usefully interleave two generations, and the live stream already prefetches
answers in a background thread while a page request may ask for another. Serialising here is
what stops those two colliding — the wait is real either way; this makes it orderly.

## What the persona prompt should look like now

The character moved into the weights, so callers do not need the 3645-character prompt any more:
measured on held-out mid-conversation turns, the tuned model with a 129-character prompt scored
92% against 83% for the base with the full one. What should NOT be dropped is the hard rules —
no invented prices, no medical or income claims, no pretending to be human. They are cheap to
state, they are the part with consequences, and `check_reply` still enforces them regardless.

    finetune\\.venv\\Scripts\\python.exe tools\\llm_train\\serve.py        # :11435
"""
from __future__ import annotations

import argparse
import sys
import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BASE = REPO / "finetune" / "base" / "Qwen2.5-7B-Instruct"
ADAPTERS = REPO / "finetune" / "adapters"

GPU = threading.Lock()
STATE: dict = {}


def load(kol_id: str, base: Path, adapter: Path | None):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from peft import PeftModel

    tok = AutoTokenizer.from_pretrained(str(base))
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    quant = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                               bnb_4bit_use_double_quant=True,
                               bnb_4bit_compute_dtype=torch.bfloat16)
    model = AutoModelForCausalLM.from_pretrained(
        str(base), quantization_config=quant, dtype=torch.bfloat16, device_map={"": 0})
    tuned = False
    if adapter and (adapter / "adapter_config.json").is_file():
        model = PeftModel.from_pretrained(model, str(adapter))
        tuned = True
    model.eval()
    STATE.update(tok=tok, model=model, tuned=tuned, kol=kol_id,
                 name=f"{kol_id}-tuned" if tuned else "qwen2.5:7b-base")
    return STATE


def generate(messages: list[dict], *, temperature: float, max_tokens: int) -> tuple[str, int, int]:
    import torch
    tok, model = STATE["tok"], STATE["model"]
    enc = tok.apply_chat_template(messages, add_generation_prompt=True,
                                  return_tensors="pt", return_dict=True)
    enc = {k: v.to(model.device) for k, v in enc.items()}
    n_in = enc["input_ids"].shape[-1]
    # temperature 0 means greedy. Passing 0 to a sampler is an error rather than determinism.
    kw = dict(do_sample=temperature > 0.01, pad_token_id=tok.pad_token_id)
    if kw["do_sample"]:
        kw.update(temperature=temperature, top_p=0.9)
    with GPU, torch.no_grad():
        out = model.generate(**enc, max_new_tokens=max_tokens, **kw)
    text = tok.decode(out[0][n_in:], skip_special_tokens=True).strip()
    return text, n_in, int(out.shape[-1] - n_in)


def completion_body(text: str, model_name: str, n_in: int, n_out: int) -> dict:
    return {
        "id": "chatcmpl-" + uuid.uuid4().hex[:24], "object": "chat.completion",
        "created": int(time.time()), "model": model_name,
        "choices": [{"index": 0, "finish_reason": "stop",
                     "message": {"role": "assistant", "content": text}}],
        "usage": {"prompt_tokens": n_in, "completion_tokens": n_out,
                  "total_tokens": n_in + n_out},
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "KolLLM/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass  # one line per token-generation request is noise; errors still surface below

    def handle_one_request(self):
        try:
            super().handle_one_request()
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            self.close_connection = True

    def _json(self, obj, status: int = 200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.rstrip("/") in ("/v1/models", "/models"):
            self._json({"object": "list", "data": [
                {"id": STATE["name"], "object": "model", "owned_by": "local"}]})
        elif self.path.rstrip("/") in ("/health", "/v1/health"):
            self._json({"up": True, "model": STATE["name"], "tuned": STATE["tuned"]})
        # The rest of this project probes Ollama's own tags endpoint to decide whether the brain
        # is reachable. Answering it means those checks keep working unchanged.
        elif self.path.rstrip("/") == "/api/tags":
            self._json({"models": [{"name": STATE["name"], "model": STATE["name"]}]})
        else:
            self._json({"error": {"message": "not found"}}, 404)

    def do_POST(self):
        if self.path.rstrip("/") not in ("/v1/chat/completions", "/chat/completions"):
            self._json({"error": {"message": "not found"}}, 404)
            return
        n = int(self.headers.get("Content-Length") or 0)
        try:
            req = json.loads(self.rfile.read(n) or b"{}")
        except Exception as exc:
            self._json({"error": {"message": f"bad JSON: {exc}"}}, 400)
            return

        msgs = req.get("messages") or []
        if not msgs:
            self._json({"error": {"message": "messages is required"}}, 400)
            return
        # Several system messages in a row is how persona_brain composes its instructions, and
        # chat templates expect at most one. Merging keeps every instruction and stops the
        # template dropping the later ones silently.
        merged, sys_parts = [], []
        for m in msgs:
            if m.get("role") == "system":
                sys_parts.append(str(m.get("content") or ""))
            else:
                merged.append({"role": m.get("role", "user"),
                               "content": str(m.get("content") or "")})
        if sys_parts:
            merged.insert(0, {"role": "system", "content": "\n\n".join(sys_parts)})

        try:
            text, n_in, n_out = generate(
                merged, temperature=float(req.get("temperature", 0.7)),
                max_tokens=int(req.get("max_tokens") or 160))
        except Exception as exc:
            self._json({"error": {"message": f"{type(exc).__name__}: {exc}"}}, 500)
            return

        if req.get("stream"):
            self._stream(text, req.get("model") or STATE["name"])
        else:
            self._json(completion_body(text, req.get("model") or STATE["name"], n_in, n_out))

    def _stream(self, text: str, model_name: str):
        """Server-sent events, emitted after generation rather than during it.

        Honest about what this is: the text is already complete, so this replays it in chunks to
        satisfy clients that ask for a stream. It buys the caller nothing in latency — the reason
        it exists is that `persona_brain.chat(stream=True)` would otherwise fail outright, and a
        working slow path beats a broken fast one.
        """
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        cid = "chatcmpl-" + uuid.uuid4().hex[:24]

        def frame(delta: dict, finish=None):
            return ("data: " + json.dumps({
                "id": cid, "object": "chat.completion.chunk", "created": int(time.time()),
                "model": model_name,
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}) + "\n\n")

        try:
            self.wfile.write(frame({"role": "assistant"}).encode())
            for i in range(0, len(text), 24):
                self.wfile.write(frame({"content": text[i:i + 24]}).encode())
            self.wfile.write(frame({}, "stop").encode())
            self.wfile.write(b"data: [DONE]\n\n")
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass
        self.close_connection = True


def main() -> int:
    # Model output carries emoji and this console is cp950. Printing a sample must not be able
    # to destroy a run whose numbers are already computed — it happened here, and in
    # harvest_talk before it.
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--kol", default="sofia-vargas")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=11435)
    ap.add_argument("--base", default=str(BASE))
    ap.add_argument("--adapter", default=None)
    ap.add_argument("--no-adapter", action="store_true", help="serve the base model untouched")
    args = ap.parse_args()

    adapter = None if args.no_adapter else Path(
        args.adapter or (ADAPTERS / args.kol / "final"))
    print(f"loading {Path(args.base).name}" + (f" + {adapter.parent.name}" if adapter else ""),
          flush=True)
    t = time.perf_counter()
    load(args.kol, Path(args.base), adapter)
    import torch
    print(f"ready in {time.perf_counter()-t:.0f}s, "
          f"{torch.cuda.memory_allocated()/1e9:.1f} GB on the card", flush=True)
    print(f"model name: {STATE['name']}  (tuned={STATE['tuned']})", flush=True)
    print(f"point the system at:  OLLAMA_BASE_URL=http://{args.host}:{args.port}/v1", flush=True)

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
