#!/usr/bin/env python3
"""Score every candidate reference clip against a target voice brief, on the same measures.

Written for the brief "a gentle, warm, young female voice - breathy, conversational, 4-6 s".
Three of those four words are measurable and one is not:

    length        the brief asks for 4-6 s. CosyVoice's own guidance is a short clean prompt.
    brightness    energy in 2-5 kHz over total. Breath and sibilance live here, and denoising
                  is what removes them -- so a LOW number on a clip that should be breathy is
                  the fingerprint of over-cleaning, not of a soft voice.
    pitch         median f0, and range in semitones. "Young female" is roughly 180-260 Hz;
                  range is how much colour is in the delivery.
    warmth        not measurable. That one is decided by ear, which is what the demo A/B is for.

    .venv\\Scripts\\python.exe tools\\voice_eval\\ref_audit.py
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
for st in (sys.stdout, sys.stderr):
    try:
        st.reconfigure(errors="replace")
    except Exception:
        pass

TARGET = {"secs": (4.0, 6.0), "f0": (180, 260), "brightness": (10.0, 27.0)}


def measure(path: Path) -> dict | None:
    import librosa
    import numpy as np
    try:
        y, sr = librosa.load(str(path), sr=None, mono=True)
    except Exception:
        return None
    if y.size == 0:
        return None
    secs = len(y) / sr
    S = np.abs(librosa.stft(y, n_fft=2048))
    freqs = librosa.fft_frequencies(sr=sr, n_fft=2048)
    band = (freqs >= 2000) & (freqs <= 5000)
    total = float(S.sum()) or 1.0
    brightness = 100.0 * float(S[band].sum()) / total
    try:
        f0, voiced, _ = librosa.pyin(y, fmin=70, fmax=500, sr=sr)
        f0 = f0[~np.isnan(f0)]
        med = float(np.median(f0)) if f0.size else 0.0
        rng = float(12 * np.log2(np.percentile(f0, 95) / np.percentile(f0, 5))) if f0.size else 0.0
    except Exception:
        med, rng = 0.0, 0.0
    # Noise floor: the quietest 10% of frames. A reference is meant to be silent underneath.
    rms = librosa.feature.rms(y=y)[0]
    floor = 20 * np.log10(max(float(np.percentile(rms, 10)), 1e-9))
    peak = 20 * np.log10(max(float(np.abs(y).max()), 1e-9))
    return {"secs": secs, "sr": sr, "f0": med, "range_st": rng,
            "brightness": brightness, "floor_db": floor, "peak_db": peak}


def verdict(m: dict) -> str:
    bad = []
    if not TARGET["secs"][0] <= m["secs"] <= TARGET["secs"][1]:
        bad.append(f"{m['secs']:.1f}s outside 4-6")
    if not TARGET["f0"][0] <= m["f0"] <= TARGET["f0"][1]:
        bad.append(f"f0 {m['f0']:.0f}")
    if m["brightness"] < TARGET["brightness"][0]:
        bad.append("dull/over-denoised")
    return "ok" if not bad else ", ".join(bad)


def main() -> int:
    kol = sys.argv[1] if len(sys.argv) > 1 else "sofia-hsu"
    v = REPO / "kols" / kol / "voice"
    files = sorted(v.glob("ref*.wav")) + sorted(v.glob("ref_human.wav.*")) + \
        sorted((v / "candidates").glob("*.wav"))
    print(f"  target: 4-6 s, f0 180-260 Hz, brightness 10-27% (breath lives in 2-5 kHz)\n")
    print(f"  {'file':<34}{'secs':>6}{'sr':>7}{'f0':>6}{'range':>7}{'bright':>8}"
          f"{'floor':>7}  verdict")
    print("  " + "-" * 96)
    for f in files:
        m = measure(f)
        if not m:
            continue
        name = f.name if f.parent.name != "candidates" else f"candidates/{f.stem}"
        print(f"  {name:<34}{m['secs']:6.1f}{m['sr']:7d}{m['f0']:6.0f}{m['range_st']:7.1f}"
              f"{m['brightness']:7.1f}%{m['floor_db']:7.0f}  {verdict(m)}")
    print("\n  brightness is the one to read. The shipping reference measures ~6.6% against "
          "10-27%\n  for every licensed candidate — that gap IS the missing breath, and it was "
          "removed by\n  cleanup, not by the speaker. See profile.json ai_assets.voice."
          "reference_cleanup.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
