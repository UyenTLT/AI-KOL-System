#!/usr/bin/env python3
"""Why does her voice move less in production than it did in the studio?

The studio measured 14.48 semitones of pitch range for this voice and reported it as matching
a human recording at 14.10. Measured on 38 windows of what the live stream actually rendered,
the same voice sits at 10.93. Both numbers are real; they were taken under different settings,
and nobody had compared the settings.

Two things differ between them, and they were changed at different times for different reasons:

    instruct   the studio uses the standing instruction in her profile; the stream overrides it
               per register with a shorter wording chosen for transcription accuracy, not range
    speed      the stream multiplies by PACE (1.08) to shave 13% off the wait

So this renders the same sentences under all four combinations and measures each. A finding is
only useful if it names which of the two to change — "production is flatter" does not.

Pitch is measured with tools/voice_eval/prosody.py, the same instrument as every other voice
number in this repo, and every arm is measured identically, so whatever the window length does
to the absolute figure it does it to all four equally.

    .venv\Scripts\python.exe tools\voice_eval\why_flat.py
    .venv\Scripts\python.exe tools\voice_eval\why_flat.py --kol sofia-hsu --runs 2
"""
from __future__ import annotations

import argparse
import statistics
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
for sub in ("studio", "livestream", "voice_eval"):
    sys.path.insert(0, str(REPO / "tools" / sub))

# Varied on purpose. A single sentence measures one contour; the complaint is about how she
# sounds across a conversation, and a flat delivery shows up most on the lines that ought not
# to be flat.
LINES = [
    "Okay so this actually happened to me last week and I still cannot believe it.",
    "No, honestly, that one is not worth the money. I tried it and I would not buy it again.",
    "I filmed four takes of the same thing and used the first one anyway.",
    "Wait, really? He said that to your face?",
    "It was fine. Just fine. And somehow that was worse than if it had been bad.",
    "I missed a flight arguing about breakfast. I still think I was right.",
]


def render_and_measure(kol: str, text: str, instruct: str | None, speed: float,
                       out_dir: Path, tag: str, i: int) -> float | None:
    from voice_studio import synthesize
    import prosody
    out = out_dir / f"{tag}_{i}.wav"
    try:
        synthesize(kol, text, out=out, speed=speed, instruct=instruct)
    except Exception as exc:
        print(f"    render failed ({tag}): {type(exc).__name__}: {exc}", file=sys.stderr)
        return None
    y = prosody.load_any(str(out))
    f = prosody.feats(y)
    return f.get("f0_range_st") if f else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kol", default="sofia-hsu")
    ap.add_argument("--runs", type=int, default=1, help="repeats per arm; the engine is stochastic")
    args = ap.parse_args()

    import json
    from stage import ANSWERING, PACE
    prof = json.loads((REPO / "kols" / args.kol / "profile.json").read_text(encoding="utf-8"))
    profile_instruct = (prof.get("ai_assets", {}).get("voice", {}) or {}).get("instruct")

    arms = [
        ("studio      profile instruct, 1.00", profile_instruct, 1.0),
        ("instruct    stream instruct, 1.00", ANSWERING, 1.0),
        ("pace        profile instruct, %.2f" % PACE, profile_instruct, PACE),
        ("production  stream instruct, %.2f" % PACE, ANSWERING, PACE),
    ]

    print(f"{args.kol}: {len(LINES)} lines x {args.runs} run(s) per arm\n")
    results = {}
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        for name, instruct, speed in arms:
            vals = []
            for r in range(args.runs):
                for i, line in enumerate(LINES):
                    v = render_and_measure(args.kol, line, instruct, speed, td,
                                           name.split()[0] + str(r), i)
                    if v:
                        vals.append(v)
            results[name] = vals
            if vals:
                print(f"  {name:<40} {statistics.mean(vals):5.2f} st  "
                      f"(n={len(vals)}, sd {statistics.pstdev(vals):.2f})", flush=True)
            else:
                print(f"  {name:<40} no measurements", flush=True)

    ok = {k: v for k, v in results.items() if v}
    if len(ok) < 2:
        return 1
    best = max(ok, key=lambda k: statistics.mean(ok[k]))
    worst = min(ok, key=lambda k: statistics.mean(ok[k]))
    print(f"\n  widest : {best.strip()}  ({statistics.mean(ok[best]):.2f} st)")
    print(f"  flattest: {worst.strip()}  ({statistics.mean(ok[worst]):.2f} st)")
    print("\n  Human reference for this voice: 14.10 st (kols/<id>/voice/ref_human.wav).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
