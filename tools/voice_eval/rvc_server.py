#!/usr/bin/env python3
"""RVC held resident, so a timbre pass can sit in the streaming path.

Her speaking voice is a zero-shot CosyVoice clone taken from a 6.5 second reference. The RVC
model is trained on 98.5 minutes of the same person. Measured identity against her real human
reference, level-matched, four lines each:

    CosyVoice alone     0.4784 +/- 0.0277
    CosyVoice + RVC     0.8979 +/- 0.0156      difference +0.4195, pooled sd 0.0225

That is the timbre, and it is why she sounded generated: the clone was about half-way to her
voice and the trained model gets there. Prosody survives the pass -- pitch range 12.82 -> 11.46
semitones over four short clips, inside a pooled spread of 2.54, and duration is unchanged.

The reason this file exists rather than a call to `infer.cli`: the CLI costs a FIXED ~6.4
seconds whether it converts 3.2 seconds of audio or 8.1, because it starts a process and loads
the model every time. First-words latency on the stream is 2.9 s and was taken there from 16.6
s; paying 6.4 s per chunk would undo that outright. Loading once and converting per request is
the whole point.

    RVC\.venv\Scripts\python.exe tools\voice_eval\rvc_server.py        # :9882

POST /convert  {"input": "<path>", "output": "<path>", "pitch": 0}
GET  /health
"""
from __future__ import annotations

import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RVC = REPO / "RVC"
sys.path.insert(0, str(RVC))

VC_OBJ = None
LOADED = {"model": None}


def _profile(kol: str = "sofia-vargas") -> dict:
    p = REPO / "kols" / kol / "profile.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    return d.get("ai_assets", {}).get("voice_conversion", {})


def load(kol: str = "sofia-vargas"):
    """Load the model once. Everything after this is just inference."""
    global VC_OBJ
    # RVC resolves its own resources -- i18n locales, hubert weights, the model directory --
    # relative to the working directory, so it has to be run from inside its own tree. The CLI
    # gets this for free by being launched with cwd=RVC; a resident server has to do it itself.
    import os
    os.chdir(RVC)
    # These four are read from the environment deep inside RVC (`f'{os.getenv("weight_root")}/
    # {sid}'`), so an unset one fails as the literal path "None/sofia-vargas.pth". infer.cli
    # sets them at import; nothing sets them for a caller that imports the modules directly.
    os.environ.setdefault("weight_root", str(RVC / "assets" / "weights"))
    os.environ.setdefault("index_root", str(RVC / "logs"))
    os.environ.setdefault("outside_index_root", str(RVC / "assets" / "indices"))
    os.environ.setdefault("rmvpe_root", str(RVC / "assets" / "rmvpe"))
    from configs.config import Config
    from infer.vc.modules import VC
    vc_cfg = _profile(kol)
    model = Path(vc_cfg["model"]).name
    cfg = Config()
    VC_OBJ = VC(cfg)
    VC_OBJ.get_vc(model)
    LOADED["model"] = model
    LOADED["index"] = str(REPO / vc_cfg["index"]) if vc_cfg.get("index") else ""
    best = vc_cfg.get("best_inference_settings", {})
    LOADED["index_rate"] = float(best.get("index_rate", 1.0))
    LOADED["protect"] = float(best.get("protect", 0.10))
    print(f"  loaded {model}", flush=True)
    # Convert something once before serving. hubert and rmvpe load lazily on the first real
    # conversion, which measured 4.63 s against 0.97 s for every call after it -- and the first
    # real conversion is somebody waiting on a live stream. The reference clip is already here
    # and is the right length for the job.
    try:
        import tempfile
        warm = Path(tempfile.gettempdir()) / "rvc_warmup.wav"
        t0 = time.perf_counter()
        convert(str(REPO / "kols" / kol / "voice" / "ref_human.wav"), str(warm))
        warm.unlink(missing_ok=True)
        print(f"  warmed in {time.perf_counter() - t0:.1f}s", flush=True)
    except Exception as exc:
        print(f"  warm-up skipped: {type(exc).__name__}: {exc}", flush=True)


def convert(inp: str, outp: str, pitch: int = 0) -> dict:
    import soundfile as sf
    t0 = time.perf_counter()
    _, wav = VC_OBJ.vc_single(
        0, inp, pitch, "rmvpe", LOADED["index"], LOADED["index_rate"],
        0, 0.25, LOADED["protect"])
    if wav is None:
        raise RuntimeError("conversion returned nothing")
    sr, audio = wav
    Path(outp).parent.mkdir(parents=True, exist_ok=True)
    sf.write(outp, audio, sr)
    return {"out": outp, "seconds": round(time.perf_counter() - t0, 3), "sr": sr}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code: int, payload: dict):
        b = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path.startswith("/health"):
            self._send(200, {"ok": VC_OBJ is not None, "model": LOADED.get("model")})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if not self.path.startswith("/convert"):
            self._send(404, {"error": "not found"})
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
            self._send(200, convert(body["input"], body["output"],
                                    int(body.get("pitch", 0))))
        except Exception as exc:
            self._send(500, {"error": f"{type(exc).__name__}: {exc}"})


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9882)
    ap.add_argument("--kol", default="sofia-vargas")
    args = ap.parse_args()
    for st in (sys.stdout, sys.stderr):
        try:
            st.reconfigure(errors="replace")
        except Exception:
            pass
    load(args.kol)
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"  rvc_server on http://{args.host}:{args.port}", flush=True)
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
