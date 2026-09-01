#!/usr/bin/env python3
"""Time to first audio, measured through the path the live server actually uses.

Three numbers, because "response time" hides which stage is slow and they move independently:

    think       first complete sentence out of the model
    render      that text synthesised and the timbre pass applied
    TTFA        the sum -- when a viewer first hears anything

Renders through stage.perform, the same function server.answer calls, so the timbre pass and
PACE are in the measurement rather than assumed away.

    .venv\\Scripts\\python.exe tools\\voice_eval\\ttft.py
    .venv\\Scripts\\python.exe tools\\voice_eval\\ttft.py --n 6 --label after
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import time
import wave
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
for sub in ("livestream", "livetalking", "studio", "voice_eval"):
    sys.path.insert(0, str(REPO / "tools" / sub))
for st in (sys.stdout, sys.stderr):
    try:
        st.reconfigure(errors="replace")
    except Exception:
        pass
os.environ.setdefault("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1")
os.environ.setdefault("KOL_LLM_TUNED", "1")
os.environ.setdefault("KOL_LLM_MODEL", "sofia-hsu-tuned")

COMMENTS = [
    "where did you get that jacket?",
    "coffee or tea?",
    "what did you eat today?",
    "bet you can't go one day without coffee",
    "you look tired today, everything ok?",
    "how do you stay motivated?",
]


def audio_seconds(p: Path) -> float:
    try:
        with wave.open(str(p)) as w:
            return w.getnframes() / float(w.getframerate())
    except Exception:
        return 0.0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--n", type=int, default=4)
    ap.add_argument("--label", default="now")
    ap.add_argument("--kol", default=os.getenv("KOL_ID", "sofia-hsu"))
    args = ap.parse_args()

    from stage import (LIVE_MAX_TOKENS, PACE, classify, perform, respond_streamed,
                       speech_chunks, strip_tics)

    tmp = Path(tempfile.mkdtemp(prefix="ttft-"))
    print(f"  {args.label}:  LIVE_MAX_TOKENS={LIVE_MAX_TOKENS}  PACE={PACE}\n")
    print(f"  {'think':>7} {'render':>7} {'TTFA':>7} {'audio':>6} {'RTF':>5} {'clips':>5}  text")
    rows = []
    for i, q in enumerate(COMMENTS[:args.n]):
        mode = classify(q)
        t0 = time.perf_counter()
        pieces, first_text, think = [], None, 0.0
        for piece in respond_streamed(args.kol, q, mode, history=[], asker="Mai"):
            if piece is None:
                break
            if first_text is None:
                first_text, think = piece, time.perf_counter() - t0
            pieces.append(piece)
        if first_text is None:
            print("  guard tripped, skipped")
            continue
        full, _ = strip_tics(" ".join(pieces), first_message=False, message=q)
        clips = speech_chunks(full)
        # What the viewer waits for: the FIRST clip. With one clip per reply that is the whole
        # answer, which is why the cap and this number are the same conversation.
        t1 = time.perf_counter()
        out = perform(args.kol, clips[0], mode, tmp / f"{i:02d}.wav")
        render = time.perf_counter() - t1
        secs = audio_seconds(out)
        rtf = render / secs if secs else 0.0
        rows.append((think, render, think + render, secs, rtf, len(clips)))
        print(f"  {think:6.2f}s {render:6.2f}s {think+render:6.2f}s {secs:5.1f}s "
              f"{rtf:5.2f} {len(clips):5d}  {full[:52]}")

    if rows:
        def med(i):
            return sorted(r[i] for r in rows)[len(rows) // 2]
        print(f"\n  median  think {med(0):.2f}s   render {med(1):.2f}s   "
              f"TTFA {med(2):.2f}s   RTF {med(4):.2f}")
        print(f"  RTF is render time over audio length. Above 1.00 the player drains its buffer "
              f"faster than\n  the server fills it, which is heard as the answer stopping "
              f"mid-sentence.")
    shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
