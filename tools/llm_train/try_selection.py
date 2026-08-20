#!/usr/bin/env python3
"""Generate several answers and keep the best one, instead of improving the first one.

Seven attempts to make her funnier through the prompt all failed. This changes the mechanism
rather than the wording -- the same rejection sampling that took question-back from 71% to 4% --
and it changes the target from humour to story, which is what "more interesting" actually
means and which she already does sometimes.

Measured, 40 prompts, six candidates each:

    first candidate (what she says today)    7.5% story   20% opinion   2.5% deflect
    best of six                             32.5% story   45% opinion     0% deflect
    real people ANSWERING a question         4.3% story   19% opinion
    real people TELLING a story to camera   18.2% story

Two things follow. Selection works: story more than quadruples and deflection disappears, with
no change to the prompt or the weights. And humour does not move (2.5% either way), which is the
cleanest evidence yet that it is unreachable in this model while everything else was reachable.

The overshoot is the decision, not a defect. SHAPE_TARGET sets story at 4.3% because that is
what a real person does when answering a question, and she is already at 7.5% -- above it. To
be MORE interesting than an average person answering is a product choice about what a KOL is,
not a bug fix, and it belongs to whoever owns the persona rather than to this script.

    python tools/llm_train/try_selection.py
"""
import sys
import numpy as np
for d in ("tools/llm_train", "tools/livestream", "tools/livetalking", "tools/studio"):
    sys.path.insert(0, d)
for st in (sys.stdout, sys.stderr):
    try: st.reconfigure(errors="replace")
    except Exception: pass
from harvest_talk import is_playful, is_story, _OPINION, _FILLER
from stage import deflected
import build_dataset as B

MODEL = "sofia-hsu-tuned"
seeds = list(B.real_seeds())[:40]

def score(t):
    v = 0
    if is_story(t): v += 3
    if _OPINION.search(t): v += 1
    if is_playful(t): v += 2
    if _FILLER.search(t): v += 1
    if deflected(t): v -= 3
    if len(t.split()) > 90: v -= 2
    return v

first, best = [], []
for q in seeds:
    cands = [c for c in B.candidates("sofia-hsu", q, 6, MODEL) if c and c.strip()]
    if not cands:
        continue
    first.append(cands[0])
    best.append(max(cands, key=score))
print(f"  {len(first)} prompts x 6 candidates")

def report(rows, label):
    n = max(len(rows), 1)
    print(f"  {label:<26} {100*sum(map(is_story,rows))/n:5.1f}% story "
          f"{100*sum(1 for x in rows if _OPINION.search(x))/n:5.1f}% opinion "
          f"{100*sum(map(is_playful,rows))/n:4.1f}% playful "
          f"{100*sum(1 for x in rows if deflected(x))/n:4.1f}% deflect "
          f"{int(np.median([len(x.split()) for x in rows])) if rows else 0}w")

report(first, "first candidate (today)")
report(best, "best of six (selected)")
print("  real people:               18.2% story  ~19% opinion  5-6% playful")
