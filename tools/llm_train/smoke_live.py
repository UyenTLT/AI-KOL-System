#!/usr/bin/env python3
"""Three requests through the real live path, checked rather than eyeballed.

Each probe targets something that was changed today and could plausibly still be broken:

    zh      Traditional characters, Taiwan phrasing. speaks_cjk and wants_traditional were
            False until the identity fix, so a Chinese reply proves the language gate opened.
    en      Lowercase, SGV register, no full stop at the end. Her English voice per
            character.md IV, which only the fine-tune can produce.
    ex/mom  The ex-lore and the family. Two probes, not one: LIFE_MIX picks a single story, so
            a question naming both makes them compete and only one can surface. The check is
            whether ANY canon name reaches the reply -- if none does, the model is inventing
            over a life it was handed, which is a weights problem and not a prompt problem.

    finetune\\.venv\\Scripts\\python.exe tools\\llm_train\\smoke_live.py
"""
from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
for sub in ("livestream", "livetalking", "studio", "voice_eval", "llm_train"):
    sys.path.insert(0, str(REPO / "tools" / sub))
for st in (sys.stdout, sys.stderr):
    try:
        st.reconfigure(errors="replace")
    except Exception:
        pass

os.environ.setdefault("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1")
os.environ.setdefault("KOL_LLM_TUNED", "1")
os.environ.setdefault("KOL_LLM_MODEL", "sofia-hsu-tuned")
KOL = os.getenv("KOL_ID", "sofia-hsu")

CJK = re.compile(r"[一-鿿]")
# Simplified forms whose traditional counterpart is different. Presence means the Traditional
# rule leaked, which matters because her profile declares Traditional and opencc is meant to
# enforce it in sanitize_for_speech.
SIMPLIFIED = "们说话时间这么会开关点东买卖学问题实现对错单双图书馆爱国语头发么"
CANON = ["Brandon", "Vivian", "Mia", "Kevin", "NFT", "scale", "basil", "Tainan", "Arcadia",
         "Alhambra", "dental", "Valorant", "Marcus"]

PROBES = [
    ("zh", "妳中文到底哪裡學的 笑死"),
    ("en", "girl where do you even get your boba in the 626"),
    # Split into two, because LIFE_MIX picks ONE story and a question naming both the ex and
    # the mother makes them compete: measured, "mom" overlaps three family words against
    # "boyfriend"'s one, so the family story wins and the ex-lore never appears. That is the
    # ranking working, not failing -- but it makes a combined probe undiagnosable.
    ("ex", "how do i get over my ex"),
    ("mom", "whats the most mom thing your mom has ever done"),
]


def main() -> int:
    from stage import classify, respond, speech_chunks
    from persona_brain import check_reply, speaks_cjk, wants_traditional

    print(f"  model            {os.environ['KOL_LLM_MODEL']}")
    print(f"  speaks_cjk       {speaks_cjk(KOL)}")
    print(f"  wants_traditional {wants_traditional(KOL)}\n")

    ok = True
    for tag, q in PROBES:
        mode = classify(q)
        t0 = time.perf_counter()
        try:
            text = respond(KOL, q, mode, history=[], asker="Mai")[0]
        except Exception as exc:
            print(f"  [{tag}] FAILED: {exc}")
            ok = False
            continue
        dt = time.perf_counter() - t0
        flags = []
        v = check_reply(q, text, no_cjk=not speaks_cjk(KOL))
        if v:
            flags.append("GUARD:" + "+".join(v))
            ok = False
        if tag == "zh":
            if not CJK.search(text):
                flags.append("NO CJK - language gate still shut")
                ok = False
            leak = [c for c in text if c in SIMPLIFIED]
            if leak:
                flags.append("SIMPLIFIED:" + "".join(sorted(set(leak))))
        if tag == "en":
            if CJK.search(text):
                flags.append("CJK in an english reply")
            words = [w for w in text.split() if w.isalpha()]
            upper = sum(1 for w in words if w[0].isupper())
            flags.append(f"capitalised {upper}/{len(words)}")
            flags.append("ends on a full stop" if text.rstrip().endswith(".") else "no final stop")
        if tag in ("ex", "mom"):
            hits = [c for c in CANON if c.lower() in text.lower()]
            flags.append("canon:" + (",".join(hits) if hits else "NONE - rule still blocking"))
            if not hits:
                ok = False
        clips = len(speech_chunks(text))
        if clips > 1:
            flags.append(f"{clips} clips - seam")
        print(f"  [{tag}] {mode:8s} {dt:5.2f}s  {len(text):3d}c  {clips} clip  {' | '.join(flags)}")
        print(f"        {text}\n")

    print("  RESULT:", "pass" if ok else "SOMETHING FAILED - see flags above")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
