#!/usr/bin/env python3
"""Print the EXACT prompt the live stream sends, for one comment, register by register.

Written for handover. Every previous description of this stack in a document has drifted from
the code within a week, so this reads the code instead: what it prints is what the model is
sent, assembled by the same functions the server calls.

    python tools/livestream/dump_prompt.py "where did you get that jacket?"
    python tools/livestream/dump_prompt.py --all > docs/persona-prompts.txt
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
for sub in ("livestream", "livetalking", "studio", "voice_eval"):
    sys.path.insert(0, str(REPO / "tools" / sub))
for st in (sys.stdout, sys.stderr):
    try:
        st.reconfigure(errors="replace")
    except Exception:
        pass

SAMPLES = {
    "comment": "where did you get that jacket?",
    "banter": "bet you can't go one day without coffee",
    "heart": "i had the worst week and i do not want to talk to anyone",
}


def dump(kol_id: str, message: str, mode: str | None = None) -> None:
    from stage import MODES, classify, life_threads, LIVE_MAX_TOKENS
    from persona_brain import build_system_prompt, language_directive, wants_traditional

    mode = mode or classify(message)
    tuned = os.getenv("KOL_LLM_TUNED", "1").strip().lower() in ("1", "true", "yes")
    sysmsg = MODES[mode]["system"]
    life = life_threads(kol_id, message=message)
    if life:
        sysmsg += "\n\n" + life
    asker = "Mai"
    sysmsg += (f"\n\nThis comment is from {asker}. Talk to them, and use their name when "
               f"it fits naturally.")

    msgs = [("system  [1/3] persona + hard rules", build_system_prompt(kol_id, tuned=tuned)),
            ("system  [2/3] register + life + asker", sysmsg),
            ("system  [3/3] language directive",
             language_directive(message, wants_traditional(kol_id))),
            ("user", message)]

    print("=" * 100)
    print(f"REGISTER: {mode}    (classify() picked this from the message)")
    print(f"MODEL:    {os.getenv('KOL_LLM_MODEL', 'qwen2.5:7b')}   "
          f"tuned-prompt={tuned}   temperature=0.6   max_tokens={LIVE_MAX_TOKENS}")
    print(f"HISTORY:  [] - the live path sends none; see server.answer_worker")
    print("=" * 100)
    total = 0
    for label, body in msgs:
        print(f"\n----- {label}  ({len(body)} chars) " + "-" * max(0, 40 - len(label)))
        print(body)
        total += len(body)
    print(f"\n----- total {total} chars sent per comment " + "-" * 30)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("message", nargs="?", default=SAMPLES["comment"])
    ap.add_argument("--kol", default=os.getenv("KOL_ID", "sofia-hsu"))
    ap.add_argument("--mode", default=None, help="force a register instead of classify()")
    ap.add_argument("--all", action="store_true", help="one sample per register")
    args = ap.parse_args()

    if args.all:
        for mode, msg in SAMPLES.items():
            dump(args.kol, msg, mode)
            print("\n\n")
    else:
        dump(args.kol, args.message, args.mode)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
