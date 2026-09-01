#!/usr/bin/env python3
"""A/B the voice post-chain: old instruct and no shaping, against the new config.

Four measurements, and the first is the one that has caught this project out before:

    transcribes   the rendered audio sent back through whisper and matched word-for-word
                  against the text that was MEANT to be spoken. A 219-character instruct
                  once scored 0.409 here because CosyVoice read the instruction out loud
                  mid-line. Any instruct change has to clear this before anything else
                  about it is worth discussing.
    brightness    energy in 2-5 kHz. This is the breath the air shelf is meant to restore.
    f0            median pitch. The shift should move it by about the semitones asked for
                  and no more.
    harshness     also 2-5 kHz, and the reason `soften` exists. The shelf works against it,
                  so this is the number that says whether +1.5 dB went too far.

    .venv\\Scripts\\python.exe tools\\voice_eval\\ab_voice_config.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
for sub in ("studio", "livetalking", "livestream", "voice_eval"):
    sys.path.insert(0, str(REPO / "tools" / sub))
for st in (sys.stdout, sys.stderr):
    try:
        st.reconfigure(errors="replace")
    except Exception:
        pass

LINE = ("Honestly the second coffee is the one that counts, and I will not be taking "
        "questions about it today.")
OLD_INSTRUCT = "Speak softly and warmly, at a natural everyday pace."


def measure(path: Path) -> dict:
    import librosa
    import numpy as np
    y, sr = librosa.load(str(path), sr=None, mono=True)
    S = np.abs(librosa.stft(y, n_fft=2048))
    freqs = librosa.fft_frequencies(sr=sr, n_fft=2048)
    band = (freqs >= 2000) & (freqs <= 5000)
    total = float(S.sum()) or 1.0
    f0, _, _ = librosa.pyin(y, fmin=70, fmax=500, sr=sr)
    f0 = f0[~np.isnan(f0)]
    return {"secs": len(y) / sr,
            "f0": float(np.median(f0)) if f0.size else 0.0,
            "range_st": float(12 * np.log2(np.percentile(f0, 95) / np.percentile(f0, 5)))
            if f0.size else 0.0,
            "band_pct": 100.0 * float(S[band].sum()) / total}


def word_match(said: str, meant: str) -> float:
    norm = lambda t: re.findall(r"[a-z']+", t.lower())
    a, b = norm(said), norm(meant)
    if not b:
        return 0.0
    from difflib import SequenceMatcher
    return SequenceMatcher(None, a, b).ratio()


def main() -> int:
    from voice_studio import synthesize, transcribe
    pf = REPO / "kols/sofia-hsu/profile.json"
    prof = json.loads(pf.read_text(encoding="utf-8"))
    v = prof["ai_assets"]["voice"]
    new_instruct = v["instruct"]
    tmp = REPO / "renders" / "ab_voice"
    tmp.mkdir(parents=True, exist_ok=True)

    arms = [
        ("A  old instruct, no shaping", OLD_INSTRUCT, None, None),
        ("B  new instruct only", new_instruct, None, None),
        ("C  new + pitch +0.75st", new_instruct, 0.75, None),
        ("D  new + pitch + air 1.5dB", new_instruct, 0.75, {"hz": 3500, "gain_db": 1.5}),
    ]
    print(f"  line ({len(LINE)} chars): {LINE}")
    print(f"  new instruct is {len(new_instruct)} chars; the one that leaked was 219\n")
    print(f"  {'arm':<30}{'secs':>6}{'f0':>7}{'range':>7}{'2-5kHz':>8}{'transcribes':>13}")
    print("  " + "-" * 76)
    rows = {}
    for label, instruct, pitch, air in arms:
        # Drive the real chain by editing the profile the way production reads it, so the
        # measurement is of the shipping code path and not of a parallel one.
        v["pitch_shift_st"] = pitch or 0
        if air:
            v["air"] = air
        else:
            v.pop("air", None)
        pf.write_text(json.dumps(prof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        out = tmp / f"{label.split()[0]}.wav"
        synthesize("sofia-hsu", LINE, out=out, instruct=instruct)
        m = measure(out)
        # transcribe() is annotated `-> str` and returns (text, language). Unpacked here
        # rather than "fixed", because other callers may already depend on the tuple.
        said = transcribe(out, lang="en")
        m["match"] = word_match(said[0] if isinstance(said, tuple) else said, LINE)
        rows[label] = m
        flag = "  <-- INSTRUCT LEAKED" if m["match"] < 0.9 else ""
        print(f"  {label:<30}{m['secs']:6.1f}{m['f0']:7.0f}{m['range_st']:7.1f}"
              f"{m['band_pct']:7.1f}%{m['match']:13.3f}{flag}")

    # restore the requested shipping config
    v["pitch_shift_st"] = 0.75
    v["air"] = {"hz": 3500, "gain_db": 1.5,
                "why": "High shelf restoring the breath the reference cleanup removed. Runs "
                       "after soften, which dips 3.2 kHz by 4 dB."}
    pf.write_text(json.dumps(prof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    a, d = rows[arms[0][0]], rows[arms[-1][0]]
    print(f"\n  net A -> D:  f0 {a['f0']:.0f} -> {d['f0']:.0f} Hz "
          f"({12 * (d['f0'] / a['f0'] - 1) * 1.44:+.2f} st approx),  "
          f"2-5 kHz {a['band_pct']:.1f}% -> {d['band_pct']:.1f}%")
    print(f"  clips are in {tmp} — A and D are the pair to listen to.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
