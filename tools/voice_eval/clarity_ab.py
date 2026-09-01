#!/usr/bin/env python3
"""Find the setting that makes her sound clear rather than boomy, by measuring the balance.

"Boomy" is not a vague complaint, it is a spectrum shape: too much energy low down relative to
the top. So this measures the shape rather than guessing at it.

    mud        200-500 Hz as a share of total. This is the band that reads as boxy or boomy.
    presence   2-5 kHz. Consonants, breath, the sense of the voice being in the room.
    centroid   the spectrum's centre of mass in Hz. The closest single number to what a
               listener calls "bright", and the one to watch.

Two of the settings under test are already in the codebase and currently fight each other:
`soften` cuts 4 dB at 3.2 kHz to reduce harshness, which is the same band `air` was added to
restore. Turning soften off has never been measured -- it was added before the complaint was
clarity, and it has been on ever since.

    .venv\\Scripts\\python.exe tools\\voice_eval\\clarity_ab.py
    .venv\\Scripts\\python.exe tools\\voice_eval\\clarity_ab.py --runs 3
"""
from __future__ import annotations

import argparse
import json
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

LINE = ("Honestly the second coffee is the one that counts, and I am not taking questions "
        "about it today.")

# (label, soften, air, lowcut)   soften=False disables it entirely
ARMS = [
    ("A  current (soften -4dB)", {"hz": 3200, "gain_db": -4}, None,               None),
    ("B  soften OFF",            False,                       None,               None),
    ("C  soften off + air +2",   False,                       {"hz": 3500, "gain_db": 2.0}, None),
    ("D  C + low-mid cut",       False,                       {"hz": 3500, "gain_db": 2.0}, 250),
    ("E  C + air +3.5",          False,                       {"hz": 3500, "gain_db": 3.5}, 250),
]


def measure(path: Path) -> dict:
    import librosa
    import numpy as np
    y, sr = librosa.load(str(path), sr=None, mono=True)
    S = np.abs(librosa.stft(y, n_fft=2048))
    f = librosa.fft_frequencies(sr=sr, n_fft=2048)
    tot = float(S.sum()) or 1.0
    def band(lo, hi):
        return 100.0 * float(S[(f >= lo) & (f <= hi)].sum()) / tot
    cen = float(np.mean(librosa.feature.spectral_centroid(y=y, sr=sr)))
    return {"mud": band(200, 500), "presence": band(2000, 5000),
            "centroid": cen, "secs": len(y) / sr}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--kol", default="sofia-hsu")
    args = ap.parse_args()

    from voice_studio import synthesize
    pf = REPO / "kols" / args.kol / "profile.json"
    prof = json.loads(pf.read_text(encoding="utf-8"))
    v = prof["ai_assets"]["voice"]
    keep = (v.get("soften"), v.get("air"), v.get("lowcut_hz"))
    out = REPO / "renders" / "clarity"
    out.mkdir(parents=True, exist_ok=True)

    print(f"  {args.runs} runs per arm, same line, only the post-chain differing")
    print(f"  lower mud = less boomy, higher presence and centroid = clearer\n")
    print(f"  {'arm':<28}{'mud':>7}{'presence':>10}{'centroid':>10}")
    print("  " + "-" * 56)
    rows = {}
    for label, soften, air, lowcut in ARMS:
        v["soften"] = soften
        if air:
            v["air"] = air
        else:
            v.pop("air", None)
        if lowcut:
            v["lowcut_hz"] = lowcut
        else:
            v.pop("lowcut_hz", None)
        pf.write_text(json.dumps(prof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        got = []
        for i in range(args.runs):
            p = out / f"{label.split()[0]}_{i}.wav"
            synthesize(args.kol, LINE, out=p)
            got.append(measure(p))
        med = lambda k: sorted(g[k] for g in got)[len(got) // 2]
        rows[label] = (med("mud"), med("presence"), med("centroid"))
        print(f"  {label:<28}{med('mud'):6.1f}%{med('presence'):9.1f}%{med('centroid'):9.0f}Hz")

    v["soften"], v["air"], v["lowcut_hz"] = keep[0], keep[1], keep[2]
    for k in ("air", "lowcut_hz"):
        if v.get(k) is None:
            v.pop(k, None)
    pf.write_text(json.dumps(prof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    base = rows[ARMS[0][0]]
    best = max(rows.items(), key=lambda kv: kv[1][2])
    print(f"\n  brightest: {best[0]}  centroid {best[1][2]:.0f} Hz "
          f"against {base[2]:.0f} now ({best[1][2] - base[2]:+.0f})")
    print(f"  clips in {out} - A is what ships today, listen against the winner")
    print("  profile restored; nothing switched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
