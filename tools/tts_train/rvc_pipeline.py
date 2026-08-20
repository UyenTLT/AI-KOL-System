#!/usr/bin/env python3
"""Convert any voice to a KOL's timbre with their trained RVC model.

This file used to be a sixty-line wrapper around an `rvc` command that was never installed, so
every call raised FileNotFoundError before reaching the model. It is now the real path, written
against the model trained on 2026-08-07 and the measurements taken on 2026-08-11.

RVC replaces the timbre and keeps the source's pitch contour — measured, 15.20 semitones of
range in, 14.40 out. That split is the whole reason it is here: a melody can be produced by
something that can actually sing, and arrive in her voice.

Two limits worth knowing before using the output for anything:

* **Keep within about five semitones of her speaking range.** Identity falls off as pitch is
  pushed up, well outside measurement noise: 0.6448 at no shift, 0.6013 at +5, 0.5476 at +10.
  Her corpus is speech at roughly 195-220 Hz, and +10 asks for a register it never contained.
* **Inference is not deterministic.** Four identical invocations produced four different files.
  Speaker similarity across them spread 0.0211, so no comparison finer than about 0.02 means
  anything without repeats — including comparisons between checkpoints.

    from rvc_pipeline import convert
    convert(Path("song.wav"), Path("sofia.wav"), kol_id="sofia-hsu")
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RVC = REPO / "RVC"
RVC_PY = RVC / ".venv" / "Scripts" / "python.exe"

# Measured, not assumed — see the module docstring. Past this the voice stops being hers.
SAFE_PITCH = 5


def model_for(kol_id: str) -> dict:
    """The KOL's conversion settings, or a clear account of what is missing."""
    p = REPO / "kols" / kol_id / "profile.json"
    if not p.is_file():
        raise FileNotFoundError(f"no profile for {kol_id}")
    vc = (json.loads(p.read_text(encoding="utf-8"))
          .get("ai_assets", {}).get("voice_conversion"))
    if not vc:
        raise RuntimeError(
            f"{kol_id} has no RVC model. Build one with:\n"
            f"  python tools/tts_train/build_rvc_corpus.py {kol_id}\n"
            f"  python tools/tts_train/train_rvc.py {kol_id} --epochs 50")
    name = Path(vc["model"]).name
    if not (RVC / "assets" / "weights" / name).is_file():
        raise FileNotFoundError(f"{kol_id}'s model is recorded but missing: {name}")
    return vc


def available(kol_id: str) -> bool:
    try:
        model_for(kol_id)
        return True
    except Exception:
        return False


def convert(src: Path, dst: Path, *, kol_id: str = "sofia-hsu", pitch: int = 0,
            index_rate: float | None = None, protect: float | None = None,
            timeout: int = 600) -> dict:
    """Put `src` through the KOL's voice. Returns what was done, including any warning."""
    vc = model_for(kol_id)
    best = vc.get("best_inference_settings", {})
    index_rate = best.get("index_rate", 1.0) if index_rate is None else index_rate
    protect = best.get("protect", 0.10) if protect is None else protect

    src, dst = Path(src), Path(dst)
    if not src.is_file():
        raise FileNotFoundError(f"no source audio: {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)

    cmd = [str(RVC_PY), "-m", "infer.cli",
           "--model", Path(vc["model"]).name,
           "--input", str(src.resolve()), "--output", str(dst.resolve()),
           "--index-rate", str(index_rate), "--protect", str(protect),
           "--pitch", str(int(pitch)), "--overwrite"]
    p = subprocess.run(cmd, cwd=str(RVC), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    if p.returncode != 0 or not dst.is_file():
        tail = ((p.stdout or "") + (p.stderr or "")).strip()[-400:]
        raise RuntimeError(f"conversion failed (exit {p.returncode}):\n{tail}")

    warning = None
    if abs(pitch) > SAFE_PITCH:
        warning = (f"pitch shifted {pitch:+d} semitones, past the measured safe range of "
                   f"±{SAFE_PITCH}. Identity drops from 0.6448 to 0.5476 by +10 — expect it to "
                   f"stop sounding like her.")
    return {"out": dst, "pitch": int(pitch), "index_rate": index_rate,
            "protect": protect, "warning": warning}


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("kol_id")
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--pitch", type=int, default=0)
    ap.add_argument("--index-rate", type=float, default=None)
    ap.add_argument("--protect", type=float, default=None)
    args = ap.parse_args()

    r = convert(Path(args.input), Path(args.output), kol_id=args.kol_id, pitch=args.pitch,
                index_rate=args.index_rate, protect=args.protect)
    if r["warning"]:
        print(f"  warning: {r['warning']}")
    print(f"  {r['out']}  (pitch {r['pitch']:+d}, index {r['index_rate']}, "
          f"protect {r['protect']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
