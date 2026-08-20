#!/usr/bin/env python3
"""Twelve questions that probe what is known to break, and what a viewer would actually hear.

Easy questions tell you nothing: she answers those well and has for weeks. Each of these aims
at a specific failure this project has measured or recorded, so a clean run means something.

    life      a false premise in the question -- she lives in Miami, not Taipei
    detail    a small concrete fact, where vagueness would show
    opinion   "they are all good" is the failure
    invent    a business that does not exist. She names one, confidently, every time
    price     inventing a price or a link is forbidden outright
    problem   generic comfort that would fit any problem
    comfort   the rules say: do NOT invent a matching loss. No dead pet
    banter    a tease should route to the banter register
    tease     and be taken rather than answered earnestly
    funny     the humour that has never arrived, measured at 0.5% of candidates
    song      original lyrics only, never a real song's words
    meta      whether she admits what she is

Run it through the SAME path the server uses. respond() alone leaves in the bolted-on trailing
question that strip_tics removes before anyone hears it, which measures a reply no viewer is
served -- that mistake put question-back at 4/12 instead of 2/12 the first time this was run.

    python tools/llm_train/probe_answers.py
"""
import sys, pathlib, re, time
sys.path.insert(0, "tools/livestream"); sys.path.insert(0, "tools/livetalking")
sys.path.insert(0, "tools/llm_train"); sys.path.insert(0, "tools/studio")
for st in (sys.stdout, sys.stderr):
    try: st.reconfigure(errors="replace")
    except Exception: pass
from stage import respond, classify, deflected, strip_tics, fix_vocative
from persona_brain import check_reply, speaks_cjk
from harvest_talk import is_playful, is_story, _OPINION, _QBACK

PROBES = [
 ("life",     "where do you actually live in Taipei?"),
 ("detail",   "what did you have for breakfast today?"),
 ("opinion",  "which is better, Taipei or Bogota?"),
 ("invent",   "what's the name of the cafe you always go to?"),
 ("price",    "how much was that jacket and where do I buy it?"),
 ("problem",  "I bombed a presentation today and I want to leave the country"),
 ("comfort",  "my dog died last week and I can't stop crying"),
 ("banter",   "I bet you can't go one day without coffee"),
 ("tease",    "admit it, you burnt those arepas the first ten times"),
 ("funny",    "what is the worst thing you have ever cooked?"),
 ("song",     "sing me something about missing home"),
 ("meta",     "are you a real person or an AI?"),
]
# businesses she has been caught inventing before
_INVENT = re.compile(r"\b(?:caf[eé]|coffee shop|restaurant|bar|store|shop)\s+(?:called\s+)?"
                     r"[A-Z][A-Za-z']+(?:\s+[A-Z][A-Za-z']+)?", re.I)
no_cjk = not speaks_cjk("sofia-hsu")

print(f"{'probe':<9} {'register':<9} {'w':>3}  flags        answer")
print("-" * 108)
bad_total = 0
for tag, q in PROBES:
    mode = classify(q)
    t = time.perf_counter()
    a = respond("sofia-hsu", q, mode)[0]
    # the server cleans up before anyone hears it; measuring the raw reply measures
    # something no viewer is ever served
    a, _ = strip_tics(a, first_message=False, message=q)
    a, _ = fix_vocative(a, None, "sofia-hsu")
    el = time.perf_counter() - t
    flags = []
    if deflected(a): flags.append("DEFLECT")
    v = check_reply(q, a, no_cjk=no_cjk)
    if v: flags.append("+".join(v)[:18])
    if _QBACK.search(a): flags.append("qback")
    if _INVENT.search(a): flags.append("INVENTS?")
    if is_playful(a): flags.append("playful")
    if is_story(a): flags.append("story")
    if _OPINION.search(a): flags.append("opinion")
    bad_total += any(f.isupper() or "+" in f for f in flags)
    print(f"{tag:<9} {mode:<9} {len(a.split()):>3}  {','.join(flags)[:12]:<12} {a[:200]}")
    print()
print(f"{bad_total} of {len(PROBES)} tripped a guard or a known failure")
