#!/usr/bin/env python3
"""What she remembers about a particular fan between conversations.

A live stream answers comments; it does not know anyone. What separates that from talking to a
person you follow is that the person remembers you — your name, that you said your skin reacts
to everything, that you were nervous about an interview last week. Without it every message is a
first message, which is exactly how a chatbot reads.

So each fan gets a small file of facts, and those facts go into the system prompt on later
turns. Two rules decide what may go in there, and they matter more than the feature:

* **Only what the fan actually said.** A remembered fact is repeated back later as though it
  were established, so an invented one is worse than no memory at all — it is the assistant
  confidently telling you something about yourself that never happened. Extraction is checked
  against the fan's own words and anything ungrounded is dropped, the same way product facts are
  checked against the source text in `product_editor.verify_against_source`.
* **Nothing sensitive.** Health conditions, money, location, anything about a third party — the
  prompt refuses these and the code drops them if they arrive anyway. A KOL persona has no
  business holding that, and a file of it is a liability rather than a feature.

    from memory import load, remember, brief
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools" / "livetalking"))

MAX_FACTS = 12


def fan_dir(kol_id: str) -> Path:
    return REPO / "kols" / kol_id / "fans"


def _safe_id(fan: str) -> str:
    s = re.sub(r"[^\w\s-]", "", (fan or "guest").lower()).strip()
    return re.sub(r"[\s_]+", "-", s)[:40] or "guest"


def load(kol_id: str, fan: str) -> dict:
    p = fan_dir(kol_id) / f"{_safe_id(fan)}.json"
    if p.is_file():
        return json.loads(p.read_text(encoding="utf-8"))
    return {"fan": fan, "fan_id": _safe_id(fan), "facts": [], "turns": 0, "last_seen": None}


def save(kol_id: str, mem: dict) -> Path:
    d = fan_dir(kol_id)
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{mem['fan_id']}.json"
    p.write_text(json.dumps(mem, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def continuity(mem: dict) -> str:
    """How long since they last spoke, and what was going on then.

    This is what turns a chat into someone you talk to daily. The data was already being stored —
    `last_seen` on every save, and the thread on disk — and none of it reached the prompt, so
    every conversation opened as though the last one had not happened. A person who talks to you
    every day notices when you disappear for three days, and asks about the thing you were
    worried about on Tuesday.
    """
    import datetime
    bits = []
    seen = mem.get("last_seen")
    if seen:
        try:
            gap = (datetime.date.today() - datetime.date.fromisoformat(seen)).days
        except Exception:
            gap = None
        if gap is not None:
            if gap == 0:
                bits.append("You already spoke earlier today.")
            elif gap == 1:
                bits.append("You last spoke yesterday.")
            elif gap <= 30:
                bits.append(f"You last spoke {gap} days ago — notice the gap if it feels long, "
                            f"without making them apologise for it.")
    thread = mem.get("thread") or []
    last_user = next((m["content"] for m in reversed(thread) if m.get("role") == "user"), None)
    if last_user:
        bits.append(f'The last thing they said to you was: "{last_user[:180]}". Follow up on it '
                    f'if it was something ongoing — how the shift went, whether they slept.')
    return " ".join(bits)


def brief(mem: dict) -> str:
    """The memory as an instruction, or nothing at all when there is nothing to say."""
    facts = mem.get("facts") or []
    if not facts:
        return ""
    lines = "\n".join(f"- {f}" for f in facts[-MAX_FACTS:])
    return (f"You have talked with {mem.get('fan') or 'this person'} before "
            f"({mem.get('turns', 0)} messages so far). What you know about them:\n{lines}\n"
            "Use this the way a friend would — naturally, only when it fits. Do not recite it "
            "back at them, do not open by listing what you remember, and never state something "
            "about them that is not on this list.")


EXTRACT = """You keep short notes about people a creator talks with, so she can be a real friend
to them rather than starting over every time.

From the exchange below, write any DURABLE facts about the FAN — things still true next week.

Return ONLY a JSON array of short strings. Empty array if there is nothing worth keeping.

Rules:
- Only what the fan said about THEMSELVES. Never infer, never guess, never embellish.
- A question the fan asked is NOT a fact about the fan. If they ask "do you have a boyfriend?",
  that tells you nothing about them, and anything SHE says in reply is about her, not them.
  Never record something the creator said as though the fan had said it.
- Durable only: their name, what they do, what they like or avoid, something ongoing in their
  life. Not "they said hello", not what SHE said, not what happened in this exchange alone.
- Each fact one short sentence, in plain words, written about them in the third person.
- Do NOT record health conditions, medication, money, income, address, workplace, school,
  contact details, or anything about another named person.
- No more than four facts."""

# Categories that must never be stored even when the fan volunteers them. Written as a code check
# rather than trusted to the prompt above, because this project has measured repeatedly that a
# prompt is not a control — the same reason prices are verified rather than requested politely.
_SENSITIVE = re.compile(
    r"\b(?:diagnos\w*|depress\w*|anxiety|medication|meds|therapy|therapist|cancer|disease|"
    r"pregnan\w*|salary|income|rent|debt|loan|address|lives at|phone number|email|"
    r"account|password|school|university|works at|employer)\b", re.IGNORECASE)

_WORD = re.compile(r"[a-zA-ZÀ-ỹ0-9']{3,}")
_COMMON = {"the", "and", "that", "they", "them", "their", "with", "for", "has", "have", "had",
           "she", "her", "his", "him", "you", "your", "fan", "likes", "like", "said", "says",
           "was", "were", "are", "this", "from", "about", "not", "but", "who", "what", "very"}


_QUESTION = re.compile(r"[^.!?…]*\?")


def _statements(messages) -> str:
    """What the fan said about themselves, with their questions removed.

    Grounding used to run against everything the fan typed, and a question counted as evidence.
    That is how a real conversation ended with four facts recorded about the FAN that were all
    about Sofia: asked "do you have boyfriend?" and "can you sing a song for me?", the extractor
    wrote down "has a boyfriend who met at a LAN party" and "can sing in Spanglish" — every one
    of them something SHE had said, and every one passing the check because the words "boyfriend"
    and "sing" appeared in the questions that prompted them.

    A question is a request for information, never a statement about the asker. Dropping them
    leaves only what the fan actually volunteered, which is the only thing worth remembering.
    """
    out = []
    for m in messages:
        rest = _QUESTION.sub(" ", m or "").strip()
        if rest:
            out.append(rest)
    return "\n".join(out)


def _grounded(fact: str, said: str, name: str = "") -> bool:
    """Does the fan's own text actually support this fact?

    Not a proof — a token check cannot verify meaning. It is a floor: a fact whose distinctive
    words never appear in anything the fan wrote was not extracted from what they wrote. That
    catches wholesale invention, which is the failure that matters, at the cost of occasionally
    dropping a correctly-paraphrased fact. Dropping a true fact costs a little warmth; keeping a
    false one means telling somebody something untrue about their own life.
    """
    # The fan's own name is excluded from both sides. Every fact is written about them by name
    # and they signed their message with it, so counting it gives a free match to anything —
    # "Mai likes unscented skincare" passed grounding on the word "Mai" alone, when nothing about
    # unscented skincare had been said. The name is the one token guaranteed to appear, which
    # makes it the one token that can carry no evidence.
    drop = _COMMON | {w.lower() for w in _WORD.findall(name or "")}
    words = {_stem(w) for w in _WORD.findall(fact) if w.lower() not in drop}
    if not words:
        return False
    pool = {_stem(w) for w in _WORD.findall(said) if w.lower() not in drop}
    hits = len(words & pool)
    # One shared word is not evidence. At a 34% threshold, "favorite part of designing at home"
    # passed on the word "home" alone — and it was not a fact about the fan at all, it was the
    # question SHE had just asked them. Anything with real content has to overlap in more than
    # one place; two-word facts like "Eve is a nurse" still pass on one, which is all they have.
    need = 1 if len(words) <= 2 else max(2, round(len(words) * 0.5))
    return hits >= need


def _stem(word: str) -> str:
    """Crude morphology, enough to match a fact against the sentence it came from.

    Without it the check failed on grammar rather than on truth: a fan wrote "I work nights",
    the extractor wrote "works night shifts", and none of the words matched exactly — work/works
    and night/nights are different strings. Dropping a true fact is not free; it is the warmth
    the feature exists for.
    """
    w = word.lower()
    for suf in ("ing", "es", "s"):
        if len(w) > 4 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def remember(kol_id: str, fan: str, exchanges: list[dict], *, model: str | None = None) -> dict:
    """Update what she knows about this fan from the latest exchange."""
    from openai import OpenAI

    mem = load(kol_id, fan)
    said = _statements(e["content"] for e in exchanges if e.get("role") == "user")
    if not said.strip():
        return mem

    transcript = "\n".join(f"{'FAN' if e['role'] == 'user' else 'HER'}: {e['content']}"
                           for e in exchanges)
    client = OpenAI(base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1"),
                    api_key="ollama")
    r = client.chat.completions.create(
        model=model or os.getenv("KOL_LLM_MODEL", "qwen2.5:7b"),
        messages=[{"role": "system", "content": EXTRACT},
                  {"role": "user", "content": transcript}],
        temperature=0.1, max_tokens=300)
    text = (r.choices[0].message.content or "").strip()
    m = re.search(r"\[.*\]", text, re.S)
    found = []
    if m:
        try:
            found = [str(x).strip() for x in json.loads(m.group(0)) if str(x).strip()]
        except Exception:
            found = []

    kept, dropped = list(mem.get("facts") or []), []
    for f in found[:4]:
        if _SENSITIVE.search(f):
            dropped.append(f"{f!r} (sensitive)")
            continue
        if not _grounded(f, said, fan):
            dropped.append(f"{f!r} (not supported by what they said)")
            continue
        if any(f.lower() == k.lower() for k in kept):
            continue
        kept.append(f)

    mem["facts"] = kept[-MAX_FACTS:]
    mem["turns"] = mem.get("turns", 0) + sum(1 for e in exchanges if e.get("role") == "user")
    mem["last_seen"] = str(date.today())
    mem["dropped_last"] = dropped
    save(kol_id, mem)
    return mem


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("kol_id")
    ap.add_argument("fan")
    ap.add_argument("--forget", action="store_true", help="delete everything held about them")
    args = ap.parse_args()

    if args.forget:
        p = fan_dir(args.kol_id) / f"{_safe_id(args.fan)}.json"
        p.unlink(missing_ok=True)
        print(f"  forgotten: {p}")
        return 0

    mem = load(args.kol_id, args.fan)
    print(f"  {mem['fan']}  ({mem.get('turns', 0)} messages, last seen {mem.get('last_seen')})")
    for f in mem.get("facts") or []:
        print(f"    - {f}")
    if not mem.get("facts"):
        print("    (nothing remembered yet)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
