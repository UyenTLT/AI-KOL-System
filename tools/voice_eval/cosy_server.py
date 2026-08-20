#!/usr/bin/env python3
"""A tiny HTTP front end for CosyVoice 2, so it can be compared against GPT-SoVITS live.

CosyVoice pins a different dependency stack from the rest of the repo and therefore lives in
its own venv (`CosyVoice/.venv`). Nothing in `tools/` can import it. Loading the model takes
tens of seconds, so shelling out per utterance would make interactive comparison useless.

The repo already solved this shape once: GPT-SoVITS is reached over HTTP on :9880 rather than
imported. This mirrors that — load once, serve many — so the voice lab can call both engines
the same way.

    CosyVoice\\.venv\\Scripts\\python.exe tools\\voice_eval\\cosy_server.py     # :9881

    POST /say   {"text": "...", "mode": "zero_shot"|"instruct",
                 "ref": "<path to a 3-10 s reference wav>",
                 "ref_text": "exact transcript of that clip",   # zero_shot only
                 "instruct": "speak warmly, with natural pauses"}  # instruct only
                -> audio/wav

    GET  /health -> {"up": true, "sample_rate": 24000, "device": "cuda"}

Only ever bound to localhost: it loads a multi-GB model and runs arbitrary text through it.
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import tempfile
import time
import uuid
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
COSY = REPO / "CosyVoice"
sys.path.insert(0, str(COSY))
sys.path.insert(0, str(COSY / "third_party" / "Matcha-TTS"))

_MODEL = None
_SR = 24000


def load_model(model_dir: Path, fp16: bool = False):
    global _MODEL, _SR
    from cosyvoice.cli.cosyvoice import CosyVoice2
    patch_load_wav()
    started = time.perf_counter()
    _MODEL = CosyVoice2(str(model_dir), load_jit=False, load_trt=False, fp16=fp16)
    _SR = _MODEL.sample_rate
    print(f"[load] ready in {time.perf_counter()-started:.1f} s · sample_rate {_SR}")
    return _MODEL


def to_wav_bytes(tensor) -> bytes:
    """Serialise a float tensor to 16-bit PCM. torchaudio.save wants a path; the lab wants
    bytes, and going through a temp file per request is needless."""
    import numpy as np
    audio = tensor.squeeze(0).detach().cpu().numpy()
    audio = np.clip(audio, -1.0, 1.0)
    pcm = (audio * 32767.0).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(_SR)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def _load_wav(wav, target_sr: int, min_sr: int = 16000):
    """Drop-in replacement for `cosyvoice.utils.file_utils.load_wav`.

    The original calls `torchaudio.load(wav, backend='soundfile')`. Under torchaudio 2.11 that
    still routes through TorchCodec, which is not installed, so every synthesis request fails
    with `ImportError: TorchCodec is required`. Reading with soundfile directly skips the
    decoder; the resample is pure torch and needs no media backend.

    Same contract as the original — takes a path, returns mono shape (1, n) at target_sr.
    """
    import soundfile as sf
    import torch
    import torchaudio

    data, sr = sf.read(str(wav), dtype="float32", always_2d=True)
    speech = torch.from_numpy(data.T.copy()).mean(dim=0, keepdim=True)
    if sr != target_sr:
        if sr < min_sr:
            raise ValueError(f"reference clip is {sr} Hz; needs at least {min_sr} Hz")
        speech = torchaudio.transforms.Resample(orig_freq=sr, new_freq=target_sr)(speech)
    return speech


def patch_load_wav() -> None:
    """Install `_load_wav` everywhere CosyVoice reaches for the broken one.

    `frontend.py` did `from cosyvoice.utils.file_utils import load_wav`, so it holds its own
    reference — patching only the source module leaves the frontend still calling the original.
    Both bindings have to be replaced, which is why the first attempt at this fix changed
    nothing.

    Done here rather than by editing the CosyVoice checkout: that directory is gitignored, so
    an edit inside it would vanish on a fresh clone. Same reasoning as patches/README.md.
    """
    import cosyvoice.utils.file_utils as fu
    import cosyvoice.cli.frontend as fe
    fu.load_wav = _load_wav
    fe.load_wav = _load_wav


def synth(body: dict) -> tuple[bytes, dict]:
    import torch

    text = (body.get("text") or "").strip()
    if not text:
        raise ValueError("text is required")
    ref = body.get("ref")
    if not ref or not Path(ref).is_file():
        raise ValueError(f"reference clip not found: {ref!r}")
    # The frontend loads the clip itself (frontend.py calls load_wav on whatever it is given),
    # so hand it the path, not a tensor.
    prompt = str(ref)
    mode = body.get("mode") or "zero_shot"

    started = time.perf_counter()
    if mode == "instruct":
        instruct = body.get("instruct") or "Speak naturally."
        # The instruction has to be terminated with <|endofprompt|>, or the model reads it
        # aloud as if it were the script. Measured: without the marker the output began
        # "speak warmly and conversationally like talking to a close friend..." instead of the
        # requested line. frontend_instruct2 passes the instruction into the slot zero-shot
        # uses for the reference transcript and then drops the matching audio tokens, so
        # nothing else tells the model where the instruction ends.
        if "<|endofprompt|>" not in instruct:
            instruct = instruct.rstrip() + "<|endofprompt|>"
        gen = _MODEL.inference_instruct2(text, instruct, prompt, stream=False)
    elif mode == "zero_shot":
        ref_text = body.get("ref_text") or ""
        if not ref_text:
            raise ValueError("zero_shot needs ref_text — the exact transcript of the "
                             "reference clip. A wrong transcript is the usual cause of a "
                             "bad clone.")
        gen = _MODEL.inference_zero_shot(text, ref_text, prompt, stream=False)
    else:
        raise ValueError(f"unknown mode {mode!r} (expected zero_shot or instruct)")

    chunks = [o["tts_speech"] for o in gen]
    if not chunks:
        raise RuntimeError("model produced no audio")
    wav = torch.cat(chunks, dim=1)
    elapsed = time.perf_counter() - started
    dur = wav.shape[1] / _SR
    return to_wav_bytes(wav), {"seconds": round(dur, 2), "gen_seconds": round(elapsed, 2),
                               "rtf": round(elapsed / dur, 2) if dur else None,
                               "mode": mode}


def _target_lufs_for(kol: str | None) -> float | None:
    if not kol:
        return None
    try:
        v = (json.loads((REPO / "kols" / kol / "profile.json").read_text(encoding="utf-8"))
             .get("ai_assets") or {}).get("voice") or {}
        return v.get("target_lufs")
    except Exception:
        return None


def _normalise_wav_bytes(wav: bytes, lufs: float, true_peak: float = -1.5) -> bytes:
    """Loudness-normalise a wav in memory, mirroring voice_studio._normalise_loudness.

    The limiter matters: peaks reach the true-peak ceiling before the integrated loudness
    reaches target, so without it loudnorm stops 3-4 dB short. Measured to leave pitch range
    untouched.
    """
    import re
    import subprocess
    import tempfile as _tf
    work = Path(_tf.mkdtemp())
    src, lim, dst = work / "in.wav", work / "lim.wav", work / "out.wav"
    src.write_bytes(wav)
    try:
        # Limit as its own pass, then measure the limited signal. Chaining them and feeding
        # loudnorm statistics from the unlimited audio makes it correct against an input it
        # never sees — measured overshoot of 3 dB and a clipped 0.0 dB peak. `level=false`
        # keeps alimiter from applying its own normalisation on top.
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src),
                        "-af", "alimiter=limit=0.7:level=false",
                        "-ar", str(_SR), "-ac", "1", str(lim)], check=True)
        probe = subprocess.run(
            ["ffmpeg", "-hide_banner", "-nostats", "-i", str(lim),
             "-af", f"loudnorm=I={lufs}:TP={true_peak}:LRA=11:print_format=json",
             "-f", "null", "-"], capture_output=True, text=True)
        stats = {}
        for key in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset"):
            m = re.search(rf'"{key}"\s*:\s*"(-?[\d.]+|-?inf)"', probe.stderr)
            if m and "inf" not in m.group(1):
                stats[key] = m.group(1)
        norm = (f"loudnorm=I={lufs}:TP={true_peak}:LRA=11:measured_I={stats['input_i']}"
                f":measured_TP={stats['input_tp']}:measured_LRA={stats['input_lra']}"
                f":measured_thresh={stats['input_thresh']}"
                f":offset={stats['target_offset']}:linear=true"
                if len(stats) == 5 else f"loudnorm=I={lufs}:TP={true_peak}:LRA=11")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(lim), "-af", norm,
                        "-ar", str(_SR), "-ac", "1", str(dst)], check=True)
        return dst.read_bytes()
    except Exception:
        return wav          # never lose the audio over a levelling step


def mode_for_reference(ref_path: str) -> dict | None:
    """Which KOL owns this reference clip, and how does their profile say to speak it?

    LiveTalking's CosyVoice plugin only knows `inference_zero_shot` — it posts a prompt wav and
    a transcript, and there is no field for a delivery instruction. Rather than patch the
    engine (it is gitignored, so the edit would have to live in patches/ and be re-applied),
    the server resolves the character from the clip it was handed and applies whatever mode
    that character's profile declares. sofia-hsu is configured for `instruct`, so the
    avatar gets the same voice as the studio instead of the flatter zero-shot one.
    """
    try:
        target = Path(ref_path).resolve()
    except Exception:
        return None
    for prof_path in (REPO / "kols").glob("*/profile.json"):
        try:
            v = (json.loads(prof_path.read_text(encoding="utf-8")).get("ai_assets")
                 or {}).get("voice") or {}
        except Exception:
            continue
        if v.get("engine") != "cosyvoice2":
            continue
        ref = v.get("reference_audio")
        if ref and (REPO / ref).resolve() == target:
            return {"kol": prof_path.parent.name, "mode": v.get("mode", "zero_shot"),
                    "instruct": v.get("instruct"), "ref_text": v.get("reference_text", "")}
    return None


def parse_multipart(body: bytes, content_type: str) -> dict:
    """Pull fields and the uploaded wav out of a multipart body.

    Deliberately small rather than pulling in `cgi` (removed in 3.13) or `email`: the only
    producer is LiveTalking's plugin, which sends two text fields and one file.
    """
    if "boundary=" not in content_type:
        return {}
    boundary = content_type.split("boundary=", 1)[1].strip().strip('"')
    sep = b"--" + boundary.encode()
    out: dict = {}
    for part in body.split(sep):
        if not part.strip(b"-\r\n"):
            continue
        head, _, payload = part.partition(b"\r\n\r\n")
        if not _:
            continue
        headers = head.decode("utf-8", "replace")
        name = None
        for token in headers.split(";"):
            token = token.strip()
            if token.startswith("name="):
                name = token[5:].strip().strip('"').split("\r\n")[0]
                break
        if not name:
            continue
        value = payload.rstrip(b"\r\n")
        out[name] = value
    return out


class Handler(BaseHTTPRequestHandler):
    server_version = "CosyVoiceEval/1.0"

    def log_message(self, fmt, *args):
        pass

    def _send(self, body: bytes, ctype: str, status: int = 200, extra: dict | None = None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, str(v))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, status=200):
        self._send(json.dumps(obj, ensure_ascii=False).encode(), "application/json", status)

    def _inference_zero_shot(self):
        """The endpoint LiveTalking's CosyVoice plugin calls.

        Two things must match its expectations exactly, and both are easy to get wrong:
        it reads the response with `np.frombuffer(chunk, dtype=np.int16)`, so the body must be
        **raw PCM with no WAV header** — 44 stray bytes at the front arrive as a burst of
        noise — and it resamples from 24 kHz, which is CosyVoice 2's native rate.

        It also issues this as a GET carrying a multipart body, which is unusual but legal.
        """
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        fields = parse_multipart(raw, self.headers.get("Content-Type", ""))
        text = (fields.get("tts_text") or b"").decode("utf-8", "replace").strip()
        prompt_text = (fields.get("prompt_text") or b"").decode("utf-8", "replace").strip()
        wav = fields.get("prompt_wav")
        if not text or not wav:
            self._json({"error": "tts_text and prompt_wav are required"}, 400)
            return

        tmp = Path(tempfile.gettempdir()) / f"lt-prompt-{uuid.uuid4().hex[:8]}.wav"
        tmp.write_bytes(wav)
        try:
            cfg = mode_for_reference(str(tmp)) or {}
            # The uploaded clip is a copy, so match on what LiveTalking was launched with too.
            if not cfg:
                for prof_path in (REPO / "kols").glob("*/profile.json"):
                    try:
                        v = (json.loads(prof_path.read_text(encoding="utf-8")).get("ai_assets")
                             or {}).get("voice") or {}
                    except Exception:
                        continue
                    ref = v.get("reference_audio")
                    if (v.get("engine") == "cosyvoice2" and ref
                            and (REPO / ref).is_file()
                            and (REPO / ref).read_bytes() == wav):
                        cfg = {"kol": prof_path.parent.name, "mode": v.get("mode", "zero_shot"),
                               "instruct": v.get("instruct"),
                               "ref_text": v.get("reference_text", "")}
                        break

            mode = cfg.get("mode", "zero_shot")
            body = {"text": text, "mode": mode, "ref": str(tmp)}
            if mode == "instruct":
                body["instruct"] = cfg.get("instruct") or "Speak naturally."
                who = cfg.get("kol", "?")
                print(f"  [lt] {who}: instruct mode for the avatar", flush=True)
            else:
                body["ref_text"] = prompt_text or cfg.get("ref_text", "")
            audio, meta = synth(body)
        except Exception as exc:
            self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)
            return
        finally:
            tmp.unlink(missing_ok=True)

        # Level the avatar's audio the same way the studio path does. Without this the two
        # diverge: the studio normalises in voice_studio, but LiveTalking reaches synth()
        # directly and skipped it, so the avatar came out ~4 dB quieter than the same line
        # from the studio. Same voice, different volume, for no reason anyone could see.
        target = cfg.get("target_lufs")
        if target is None:
            target = _target_lufs_for(cfg.get("kol"))
        if target is not None:
            audio = _normalise_wav_bytes(audio, float(target))

        pcm = audio[44:] if audio[:4] == b"RIFF" else audio      # strip the WAV header
        self._send(pcm, "application/octet-stream",
                   extra={"X-RTF": meta["rtf"], "X-Mode": meta["mode"]})

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/inference_zero_shot":
            self._inference_zero_shot()
            return
        if self.path.split("?")[0] == "/health":
            import torch
            self._json({"up": _MODEL is not None, "sample_rate": _SR,
                        "device": "cuda" if torch.cuda.is_available() else "cpu"})
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        path = self.path.split("?")[0]
        # LiveTalking sends this as a GET, but accept POST too — that is what the endpoint
        # ought to be, and upstream tooling may well use it.
        if path == "/inference_zero_shot":
            self._inference_zero_shot()
            return
        if path != "/say":
            self._json({"error": "not found"}, 404)
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception as exc:
            self._json({"error": f"bad request: {exc}"}, 400)
            return
        try:
            wav, meta = synth(body)
        except ValueError as exc:
            self._json({"error": str(exc)}, 400)
            return
        except Exception as exc:
            self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)
            return
        # Timing rides along in headers so the caller gets it without a second request.
        self._send(wav, "audio/wav", extra={
            "X-Gen-Seconds": meta["gen_seconds"], "X-Audio-Seconds": meta["seconds"],
            "X-RTF": meta["rtf"], "X-Mode": meta["mode"]})


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9881)
    ap.add_argument("--model", default=str(COSY / "pretrained_models" / "CosyVoice2-0.5B"))
    ap.add_argument("--fp16", action="store_true")
    args = ap.parse_args()

    model_dir = Path(args.model)
    if not model_dir.is_dir():
        raise SystemExit(f"weights not found: {model_dir}")
    load_model(model_dir, args.fp16)

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"CosyVoice 2 serving -> http://{args.host}:{args.port}  (POST /say, GET /health)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
