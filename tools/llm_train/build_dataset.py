#!/usr/bin/env python3
"""Build a fine-tuning set out of the model's own best answers.

The problem this exists to solve was measured, not assumed. With the persona and style
instructions in place, the 7B model still greeted a fan again mid-conversation on 2 turns out of
4 and signed off with an offer of further help on 1 of 4 — both explicitly forbidden in the
prompt it was given. It is not that the model cannot write the right reply. It writes it about
half the time and writes an assistant's reply the other half.

That shape is what rejection sampling is for. Ask for several answers, throw away the ones that
break the rules, and keep the ones that do not. Train on what survives and the good half becomes
the default, which is precisely the part a prompt has failed to deliver.

Two design choices that matter more than the sampling:

* **Training prompts are SHORT.** Each example pairs a one-line system prompt with a reply that
  was generated under the full persona. The point of training is to move the persona out of the
  context window and into the weights — keeping the long prompt at inference would leave the
  cost in place and learn nothing.
* **The filter is the same guard that runs in production**, plus the style checks. A sample that
  would be blocked when spoken has no business being taught as a target.

    python tools/llm_train/build_dataset.py sofia-vargas --n 250
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
for sub in ("livetalking", "livestream"):
    sys.path.insert(0, str(REPO / "tools" / sub))

OUT = REPO / "datasets"

from stage import fix_vocative, strip_tics  # noqa: E402  same cleanup production runs

# Deliberately terse, and deliberately not the persona. What the model must learn is how she
# sounds; if the answer only appears when the whole character sheet is present, nothing has been
# learned that the prompt was not already doing.
TRAIN_SYSTEM = ("You are {name}, a virtual influencer talking to your followers. "
                "Reply as yourself, out loud, in one or two short sentences.")

# Seeds, not the whole corpus. Real comments are shorter, blunter and more varied than anything
# a model invents unprompted, so these anchor the generated ones to something plausible.
SEEDS = [
    "what do you use for dry skin?", "your hair looks amazing today",
    "where did you get that jacket?", "do you ever get nervous on camera?",
    "what did you eat today?", "is that lipstick new?",
    "how do you stay motivated?", "what music are you into lately?",
    "coffee or tea?", "any plans this weekend?",
    "how long have you been doing this?", "what's your favourite city?",
    "do you actually use the stuff you post about?", "you look tired today, everything ok?",
    "my skin is so oily in summer, any tips?", "what camera do you film on?",
    "do you speak spanish at home?", "how do you deal with mean comments?",
    "what's the worst product you've tried?", "can you do a morning routine video?",
    "i'm having a bad day", "do you have a dog?",
    "what time do you wake up?", "is it hard being on camera all the time?",
    "what's in your bag right now?", "do you cook or order in?",
    "how do you pick what to review?", "favourite film?",
    "do you get lonely doing this?", "what did you want to be as a kid?",
    # Advice and opinion. The first corpus was almost all small talk, so the model was never
    # shown what committing to a view looks like — which is exactly where it hedges.
    "should I quit my job? my boss is driving me crazy",
    "do you think I should text him first or wait?",
    "I've been struggling to focus lately, everything takes twice as long",
    "should I cut my hair short? I've had it long for years",
    "my friend keeps cancelling on me and I don't know if I should say something",
    "is it worth spending more on skincare or is the cheap stuff fine?",
    "I got offered a job in another city. what would you do?",
    "do you think I'm overreacting? my flatmate never cleans anything",
    "should I go to the party tonight or stay in? I'm exhausted",
    "I want to start posting online but I'm scared people will laugh",
    "my mum keeps asking when I'm getting married and I hate it",
    "is it stupid to go back to studying at thirty?",
    "I think I want to break up with him but I'm not sure",
    "should I tell my friend her boyfriend is awful?",
    "everyone says I should network more but I hate small talk",
    "I keep comparing myself to people online and it's making me miserable",
    # Everyday material. Humour lives here more than in the crisis questions — there is nothing
    # funny to say about a bereavement, and plenty about a flatmate.
    "my flatmate ate my food again and denied it",
    "I spent 40 minutes picking a film and then watched nothing",
    "my flight got cancelled and I'm stuck at the airport",
    "I just walked into a glass door in front of everyone",
    "what did you have for dinner?",
    "I bought a plant and it died in four days",
    "my neighbour is doing DIY at 7am on a Sunday",
    "I've reread the same page of this book five times",
    "tell me something ridiculous that happened to you",
    "I said 'you too' when the waiter said enjoy your meal",
    "what's the most annoying thing about your week?",
    "I have 47 unread messages and I'm ignoring all of them",
]

MORE_FANS = """Write short comments a follower would leave for a beauty and lifestyle creator on
a live stream. Real comments: short, casual, sometimes typo-ish, sometimes off-topic, sometimes
personal. Not marketing copy, not questions a journalist would ask.

Return ONLY a JSON array of {n} strings. No numbering, no commentary."""

# The habits that make a reply read as an assistant. Each was observed in this project's own
# output with an instruction against it in place.
TICS = [
    ("double_greeting", r"^\s*(?:hey|hi|hello)[^.!?]{0,24}[!.]\s*(?:hi|hey|hello)\b"),
    ("thanks_for_asking", r"\bthanks for (?:asking|reaching out|the question)\b"),
    ("hope_helps", r"\bhope (?:this|that|it) helps\b"),
    ("offer_more", r"\b(?:let me know|feel free to (?:ask|reach))\b"),
    ("as_an_ai", r"\bas an ai\b"),
    ("listed", r"(?:^|\n)\s*(?:\d+[.)]|[-*•])\s+\S"),
    ("stage_direction", r"[\*\[(](?:laughs|smiles|giggles|winks)"),
    # Offering the menu back instead of an opinion. Asked "should I quit and go freelance?", the
    # model answered "maybe talk to your boss first? ... Or maybe it's time to reassess?" — two
    # options, no view, and it only committed when asked point blank what it would do. An
    # explicit instruction against it did not stop it: 2 replies in 4 still hedged with the rule
    # in the prompt. So it becomes a filter instead.
    ("hedged_two_ways",
     r"\bor maybe\b|\bmaybe\b[^.?!]{0,80}[?][^.?!]{0,40}\bor\b"
     r"|\beither\b[^.?!]{0,60}\bor\b|\byou could\b[^.?!]{0,70}\bor you could\b"
     r"|\bon the other hand\b|\bit depends\b"),
]
MIN_LEN, MAX_LEN = 35, 220

# Someone weighing a decision, as opposed to making conversation.
_ASKS_ADVICE = re.compile(
    r"\bshould I\b|\bwhat would you do\b|\bdo you think I\b|\bwould you\b[^?]{0,40}\?"
    r"|\bam I (?:over|wrong|being)\b|\bis it (?:worth|stupid|bad|okay|ok)\b"
    r"|\bany advice\b|\bwhat do I do\b|\bhelp me decide\b|\bor (?:should|do) I\b",
    re.IGNORECASE)

# First person, committed. Filtering out the hedge was not enough on its own: with "maybe X or
# maybe Y" removed, the surviving replies were still suggestions aimed at the fan — "have you
# tried talking to them first?", "you might feel nervous, but try it" — and only 2 in 8 said what
# she would actually do. Measured identically on the base model, so training on that set taught
# nothing. Rejection sampling removes what you filter against; the target has to be REQUIRED, not
# merely left un-penalised.
_HAS_OPINION = re.compile(
    r"\bI(?:'d|’d| would| will|'ll|’ll)\b|\bI think\b|\bI'?d? just\b|\bif I were you\b"
    r"|\bhonestly,? I\b|\bmy (?:take|vote|money)\b|\bI say\b|\bI'?ve done\b|\bI did\b",
    re.IGNORECASE)

# Only wrong when the conversation is already running. Opening with hello is what a person does;
# the fourth hello is the tell, and it is the failure the first dataset could not teach against
# because every example in it was a first message.
MID_TICS = [
    ("greeting_again", r"^\s*(?:hey|hi|hello|hiya|oh hey)\b"),
    ("reintroduced", r"\b(?:nice to meet you|good to meet you|welcome (?:back|to))\b"),
]

# A fan writing the next message in a conversation, not an interviewer. Given the thread so far.
FOLLOWUP = """You are a follower chatting with a creator you like. Write ONLY your next message
in this conversation — one short line, casual, the way people actually type.

Sometimes you follow up on what she said, sometimes you change the subject, sometimes you just
react. Do not be relentlessly positive and do not interview her. No quotation marks, no name
prefix, nothing but the message itself."""


def _client():
    from openai import OpenAI
    return OpenAI(base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1"),
                  api_key="ollama")


def parse_strings(text: str) -> list[str]:
    """Pull the list out of whatever shape the model returned it in.

    Asked for one JSON array, this model returns one array PER LINE. A single greedy `\\[.*\\]`
    then spans from the first bracket to the last, covering several arrays at once, and
    `json.loads` fails on "Extra data" — which the first version treated as "no more messages"
    and quit, leaving a 29-example dataset that looked like a finished run.

    Three attempts, cheapest first, ending with a quoted-string sweep that survives almost any
    formatting.
    """
    text = (text or "").strip()
    try:
        v = json.loads(text)
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
    except Exception:
        pass
    out = []
    for m in re.finditer(r"\[[^\[\]]*\]", text, re.S):
        try:
            v = json.loads(m.group(0))
            if isinstance(v, list):
                out += [str(x).strip() for x in v if str(x).strip()]
        except Exception:
            continue
    if out:
        return out
    return [s.strip() for s in re.findall(r'"([^"\n]{6,140})"', text) if s.strip()]


REAL_SEEDS = REPO / "datasets" / "style" / "viewers-seeds.txt"


def real_seeds() -> list[str]:
    """Comments real viewers actually left, if they have been harvested.

    SEEDS above is hand-written and says so, with the admission that real comments are shorter,
    blunter and more varied than anything a model invents unprompted. These are the real ones,
    pulled through the YouTube Data API from the same videos the style corpus came from.

    They SUPPLEMENT rather than replace. The written seeds deliberately cover situations the
    comment section does not supply on demand -- somebody weighing a decision, somebody having
    a bad day -- and losing that coverage to gain variety would be a poor trade.
    """
    if not REAL_SEEDS.is_file():
        return []
    return [l.strip() for l in REAL_SEEDS.read_text(encoding="utf-8").splitlines() if l.strip()]


def fan_messages(n: int, model: str) -> list[str]:
    """Seeds plus generated variations, deduplicated.

    Real viewer comments go in first when they have been harvested, then the written seeds, then
    generated ones only if the count is still short. The order is the point: the generated ones
    are the weakest material here and should be the part that gets displaced.
    """
    real = real_seeds()
    msgs = list(dict.fromkeys(real + SEEDS))
    if real:
        print(f"  seeds: {len(real)} real viewer comments + {len(SEEDS)} written", flush=True)
    client = _client()
    empty = 0
    # Bounded retries rather than break-on-first-failure: one badly formatted batch is normal
    # and is not evidence that the next one will fail too.
    while len(msgs) < n and empty < 4:
        want = min(30, n - len(msgs) + 10)
        try:
            r = client.chat.completions.create(
                model=model, temperature=1.0, max_tokens=900,
                messages=[{"role": "system", "content": MORE_FANS.format(n=want)},
                          {"role": "user", "content": "Write them."}])
            got = parse_strings(r.choices[0].message.content or "")
        except Exception:
            got = []
        # Emoji get stripped before speech anyway, and a comment that is only an emoji teaches
        # nothing; length bounds drop both that and the occasional essay.
        got = [g for g in got if 6 <= len(g) <= 140]
        if not got:
            empty += 1
            continue
        empty = 0
        msgs.extend(got)
        seen, uniq = set(), []
        for x in msgs:
            k = re.sub(r"\W+", " ", x.lower()).strip()
            if k and k not in seen:
                seen.add(k)
                uniq.append(x)
        msgs = uniq
    return msgs[:n]


def judge(reply: str, user_msg: str, *, mid: bool = False) -> tuple[bool, list[str]]:
    """Would this be safe to speak, and does it sound like a person?

    `mid` marks a reply that lands inside a running conversation, where a greeting is a defect
    rather than a courtesy.
    """
    from persona_brain import check_reply
    why = []
    if not reply or not reply.strip():
        return False, ["empty"]
    r = reply.strip()
    bad = check_reply(user_msg, r)
    why += [f"rule:{b}" for b in bad]
    for name, rx in TICS + (MID_TICS if mid else []):
        if re.search(rx, r, re.IGNORECASE):
            why.append(f"tic:{name}")
    if len(r) < MIN_LEN:
        why.append("too_short")
    if len(r) > MAX_LEN:
        why.append("too_long")
    if "\n" in r.strip():
        why.append("multi_line")
    # A positive requirement, not a prohibition — the one thing the previous round was missing.
    if _ASKS_ADVICE.search(user_msg or "") and not _HAS_OPINION.search(r):
        why.append("no_opinion")
    return (not why), why


def candidates(kol_id: str, msg: str, k: int, model: str,
               thread: list[dict] | None = None) -> list[str]:
    """Several answers to the same comment, generated under the full persona.

    `thread` is the conversation so far. It is passed through so a mid-conversation candidate is
    generated in the situation it will be judged in — asking for a reply with no context and then
    penalising it for saying hello would be testing something the model was never shown.
    """
    from persona_brain import (build_system_prompt, language_directive, sanitize_for_speech,
                               wants_traditional)
    from stage import MODES
    trad = wants_traditional(kol_id)
    extra = ("You are already mid-conversation with this person. Do not greet them again and do "
             "not introduce yourself." if thread else "")
    # The chat's friend-voice instructions go into generation too. Candidates are filtered on
    # exactly the habits it describes, so generating without it wastes most of the samples —
    # rejection sampling only works when the generator sometimes produces the target.
    try:
        sys.path.insert(0, str(REPO / "tools" / "chat"))
        from server import STYLE as CHAT_STYLE
    except Exception:
        CHAT_STYLE = ""
    # Her life goes into generation for the same reason the style instructions do: candidates
    # are selected for telling something that happened to her, and a generator with no life to
    # draw on can only invent one or omit it. Measured, this is the difference between 5% and
    # 10% of replies carrying an anecdote before any filtering happens at all — and the target
    # is 25.3%, so the filter needs something to find.
    try:
        from stage import life_threads
        LIFE = life_threads(kol_id, message=msg)
    except Exception:
        LIFE = ""
    msgs = [{"role": "system", "content": build_system_prompt(kol_id)},
            {"role": "system", "content": MODES["comment"]["system"] + (" " + extra if extra else "")},
            {"role": "system", "content": language_directive(msg, trad)}]
    if CHAT_STYLE:
        msgs.insert(1, {"role": "system", "content": CHAT_STYLE})
    if LIFE:
        msgs.insert(2, {"role": "system", "content": LIFE})
    msgs += list(thread or [])
    msgs.append({"role": "user", "content": msg})
    client = _client()
    out = []
    for i in range(k):
        try:
            r = client.chat.completions.create(model=model, messages=msgs,
                                               temperature=0.7 + 0.15 * i, max_tokens=150)
            out.append(sanitize_for_speech(r.choices[0].message.content or "", trad).strip())
        except Exception:
            continue
    return out


def follow_up(thread: list[dict], model: str) -> str | None:
    """The fan's next message, given how the conversation has gone."""
    shown = "\n".join(f"{'YOU' if m['role'] == 'user' else 'HER'}: {m['content']}"
                      for m in thread)
    try:
        r = _client().chat.completions.create(
            model=model, temperature=1.0, max_tokens=60,
            messages=[{"role": "system", "content": FOLLOWUP},
                      {"role": "user", "content": shown + "\n\nYOU:"}])
    except Exception:
        return None
    t = (r.choices[0].message.content or "").strip().strip('"').split("\n")[0].strip()
    t = re.sub(r"^(?:YOU|FAN)\s*:\s*", "", t, flags=re.IGNORECASE).strip()
    return t if 4 <= len(t) <= 160 else None


JUDGE = """You are picking which reply a specific person would actually have sent.

She is warm, nosy in a friendly way, opinionated, and funny — funny in how she says ordinary
things, not by telling jokes. She takes her friend's side. She wants the details of what
happened. She never offers generic comfort.

You will see a message and several candidate replies. Pick the ONE that is most:
  1. FUNNY — self-deprecating, absurdly specific, or it goes somewhere unexpected
  2. ENGAGED — reacts to the specific thing said, takes a side, brings in something of her
     own. A reply that ends by asking the other person a question is NOT more engaged for
     it; prefer the one that lands on something she said. Real people hand the turn back
     about one time in twenty.
  3. NOT GENERIC — a reply that would fit any other message is the worst one, always

If the message is genuinely sad news, ignore criterion 1 entirely and pick the one that stays
with them without inventing a matching loss of its own.

Answer with ONLY the number of the best candidate. No explanation."""


# Measured on 1,956 turns of real sit-down talk (datasets/style/heart2heart.jsonl, built by
# harvest_talk.py). These are the three shapes she was measurably wrong on; the two she was
# already fine on — turn length and concrete detail — are deliberately not steered, because
# steering a metric that is already correct only moves it off.
#
# The detectors are imported from the measurement rather than rewritten here. Two copies of
# "what counts as an opinion" would drift, and then the dataset would be optimised against one
# definition and reported against another.
# `spoken` was added after harvesting a podcast corpus to see whether the genre taught
# anything the sit-down one did not. It did not replace the target — podcast captions carry
# no speaker labels, so two people merge into one measured turn and every figure from them
# is a blend. What it did do is corroborate: 49.2% of podcast turns carry a spoken marker
# against 60.5% of sit-down turns, two independent corpora bracketing the same thing, where
# hers carry one in 21.3%. The target sits between them rather than on either.
# Targets measured on ANSWERS to real questions, not on people talking to camera.
#
# Everything before this was measured on a sit-down corpus, which is monologue: somebody with
# nobody waiting, telling stories and taking positions. Sofia answers a comment, and 393 real
# question-and-answer pairs from live streams say the two behave differently -- story shape 4.3%
# against 14.5%, opinions 19.3% against 26.5%. Steering toward the monologue numbers pushed her
# well past the answering ones: she now tells a story three times too often and states an
# opinion nearly twice too often.
#
# The sample size mattered here and is worth recording. At 174 pairs the question-back rate for
# answers measured 9.8%, HIGHER than monologue, and the conclusion drawn from it -- that she was
# essentially finished on that metric -- was wrong. At 393 it is 4.8%, and she is still 2.6x
# above it. Half the numbers moved materially between the two samples.
#
# `story` replaces `experience` rather than joining it, and the swap was forced by evidence.
#
# Adding `spoken` as a fourth target diluted the steering measurably: question-backs went from
# 18.8% of the dataset back up to 33.1%, and own-experience fell from 20.8% to 15.2%, against
# targets of 4.8% and 32.1%. Four objectives were competing over four candidates, and each one
# narrowed the pool for the next until the last had nothing left to choose from.
#
# So the count stays at four and the objectives get sharper instead. Telling something that
# happened is the weaker half of the same idea — is_story requires the past-tense marker AND
# structure, so steering on it steers both. The target comes from the sit-down corpus, where
# 14.5% of turns are shaped as a story against 1.9% of hers.
#
# The pool is doubled at the same time (k=8). With the generator ending on a question about
# 70% of the time, four candidates leave a floor of 0.7^4 = 24% that no amount of selection can
# get under; eight leaves 5.8%, which is the first time the floor sits below the target.
SHAPE_TARGET = {"qback": 0.048, "story": 0.043, "opinion": 0.193, "spoken": 0.46}


class Shape:
    """Steer the accepted set toward the measured shape of real speech.

    Rejection sampling filters each reply on its own, which cannot express "one turn in twenty
    ends with a question". That is a property of the set, not of a reply — and it is the biggest
    single defect measured: she hands the conversation back in 71.4% of replies where a real
    person does it in 4.8%.

    So this narrows the survivors before the ranking judge sees them, always toward whichever
    rate is furthest from its target, and never to nothing. A reply that ends in a question is
    not wrong; seven in ten of them is.
    """

    def __init__(self, target: dict | None = None):
        self.t = dict(target or SHAPE_TARGET)
        self.n = 0
        self.c = {k: 0 for k in self.t}

    @staticmethod
    def feats(text: str) -> dict:
        from harvest_talk import _FILLER, _OPINION, _QBACK, is_story
        return {"qback": bool(_QBACK.search(text)),
                "story": is_story(text),
                "opinion": bool(_OPINION.search(text)),
                "spoken": bool(_FILLER.search(text))}

    def rate(self, key: str) -> float:
        return self.c[key] / self.n if self.n else 0.0

    def prefer(self, cands: list[str]) -> list[str]:
        if len(cands) <= 1 or not self.n:
            return cands
        feats = {c: self.feats(c) for c in cands}
        # Largest deviation first: fixing the 67-point question-back gap matters more than
        # nudging opinions by three points, and applying them in order lets the later ones act
        # only on what the earlier one left.
        for key in sorted(self.t, key=lambda k: -abs(self.rate(k) - self.t[k])):
            want = self.rate(key) < self.t[key]
            subset = [c for c in cands if feats[c][key] == want]
            if subset and len(subset) < len(cands):
                cands = subset
        return cands

    def add(self, text: str) -> None:
        f = self.feats(text)
        self.n += 1
        for k in self.c:
            self.c[k] += int(f[k])

    def report(self) -> str:
        return "  ".join(f"{k} {self.rate(k)*100:.1f}% (target {self.t[k]*100:.1f}%)"
                         for k in self.t)


def pick_best(message: str, cands: list[str], model: str) -> str:
    """Choose among survivors by asking the model which one a person would have sent.

    The earlier rule was "shortest survivor", which optimised for speech length and nothing else.
    Every regex filter built since catches a phrasing and misses the behaviour behind it: with
    "take a walk" banned by name the next reply was "maybe a change of scenery would do you
    good", and with the banned list extended it became a tidy question with no opinion in it.

    Humour and taking someone's side do not have a surface form to match on, so they cannot be
    filtered for. They can be RANKED, which is what this does — the same rejection sampling,
    with a judge where a regex cannot reach.
    """
    if len(cands) <= 1:
        return cands[0] if cands else ""
    listed = "\n".join(f"{i+1}. {c}" for i, c in enumerate(cands))
    try:
        r = _client().chat.completions.create(
            model=model, temperature=0.0, max_tokens=6,
            messages=[{"role": "system", "content": JUDGE},
                      {"role": "user", "content": f"MESSAGE: {message}\n\nCANDIDATES:\n{listed}"}])
        m = re.search(r"\d+", r.choices[0].message.content or "")
        if m:
            i = int(m.group(0)) - 1
            if 0 <= i < len(cands):
                return cands[i]
    except Exception:
        pass
    # A judge that fails should not lose the sample — fall back to the old rule rather than
    # dropping a reply that already passed every hard filter.
    return min(cands, key=len)


def build_conversations(kol_id: str, openers: list[str], turns: int, k: int,
                        model: str, sysmsg: str,
                        shape: "Shape | None" = None) -> tuple[list[dict], int, dict]:
    """Walk each opener into a short conversation, keeping every reply that survives the judge.

    Only turns after the first are marked `mid`, and only those carry the greeting rule. The
    first reply of a conversation is kept too — it is a real example of how to open.
    """
    rows, rejected, tally = [], 0, {}
    for opener in openers:
        thread: list[dict] = []
        msg = opener
        for turn in range(turns):
            survivors = []
            for c in candidates(kol_id, msg, k, model, thread=thread):
                # Clean the candidate the way production cleans a reply, BEFORE judging it.
                #
                # Selection alone cannot get under its own floor: the generator ends on a
                # question about 83% of the time, so eight candidates leave 0.83^8 = 25% where
                # every one of them asks, and that is roughly where the run sat. Sixteen
                # candidates would buy 4.8% at twice the cost, which is the expensive way to
                # fix it.
                #
                # The cheap way is already written and already running in production, where it
                # takes the same defect from 58.3% to 12.5%. Applying it here means the model
                # learns the cleaned distribution instead of learning the raw one and relying
                # on a cleaner at inference — and a habit removed from the weights costs
                # nothing per reply, where a cleaner costs a rule that can be wrong.
                c, _ = fix_vocative(c, None, kol_id)
                c, _ = strip_tics(c, first_message=(turn == 0), message=msg)
                if not c:
                    continue
                ok, why = judge(c, msg, mid=(turn > 0))
                if ok:
                    survivors.append(c)
                else:
                    rejected += 1
                    for w in why:
                        tally[w] = tally.get(w, 0) + 1
            if shape is not None:
                survivors = shape.prefer(survivors)
            best = pick_best(msg, survivors, model) if survivors else None
            if not best:
                break
            if shape is not None:
                shape.add(best)
            rows.append({"messages": [{"role": "system", "content": sysmsg}]
                                     + thread
                                     + [{"role": "user", "content": msg},
                                        {"role": "assistant", "content": best}]})
            thread = thread + [{"role": "user", "content": msg},
                               {"role": "assistant", "content": best}]
            nxt = follow_up(thread, model)
            if not nxt:
                break
            msg = nxt
    return rows, rejected, tally


def build(kol_id: str, n: int, k: int, model: str, turns: int = 1) -> dict:
    from persona_brain import load_profile
    name = (load_profile(kol_id).get("identity", {}) or {}).get("name") or kol_id
    sysmsg = TRAIN_SYSTEM.format(name=name)

    msgs = fan_messages(n, model)
    rows, rejected, tally = [], 0, {}
    # One tracker across the whole run: the rates it steers are properties of the finished
    # dataset, so a per-batch instance would let every batch drift the same way and cancel out.
    shape = Shape()
    started = time.perf_counter()

    if turns > 1:
        # Conversations in batches, so progress is visible on a job that takes far longer than
        # the single-turn one — each opener costs `turns` replies plus `turns` follow-ups.
        step = max(1, len(msgs) // 12)
        for i in range(0, len(msgs), step):
            chunk = msgs[i:i + step]
            r, rej, t = build_conversations(kol_id, chunk, turns, k, model, sysmsg, shape)
            rows += r
            rejected += rej
            for key, v in t.items():
                tally[key] = tally.get(key, 0) + v
            el = time.perf_counter() - started
            done = min(i + step, len(msgs))
            print(f"  {done}/{len(msgs)} openers, {len(rows)} examples, "
                  f"~{el/done*(len(msgs)-done)/60:.1f} min left", flush=True)
            print(f"      shape: {shape.report()}", flush=True)
        return _write(kol_id, rows, rejected, tally, started)

    for i, m in enumerate(msgs):
        best = None
        for c in candidates(kol_id, m, k, model):
            ok, why = judge(c, m)
            if ok:
                # Shortest survivor. Length is latency downstream, and on this material the
                # longer candidates were the ones drifting toward a product description.
                if best is None or len(c) < len(best):
                    best = c
            else:
                rejected += 1
                for w in why:
                    tally[w] = tally.get(w, 0) + 1
        if best:
            rows.append({"messages": [{"role": "system", "content": sysmsg},
                                      {"role": "user", "content": m},
                                      {"role": "assistant", "content": best}]})
        if (i + 1) % 20 == 0:
            el = time.perf_counter() - started
            print(f"  {i+1}/{len(msgs)}  kept {len(rows)}  "
                  f"~{el/(i+1)*(len(msgs)-i-1)/60:.1f} min left", flush=True)

    return _write(kol_id, rows, rejected, tally, started)


def _write(kol_id: str, rows: list[dict], rejected: int, tally: dict, started: float) -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    random.Random(0).shuffle(rows)
    cut = max(1, int(len(rows) * 0.1))
    val, train = rows[:cut], rows[cut:]
    for part, data in (("train", train), ("val", val)):
        p = OUT / f"{kol_id}-chat-{part}.jsonl"
        p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in data),
                     encoding="utf-8")
    mids = sum(1 for r in rows if len(r["messages"]) > 3)
    return {"kept": len(rows), "train": len(train), "val": len(val), "mid": mids,
            "rejected": rejected, "why": dict(sorted(tally.items(), key=lambda x: -x[1])),
            "minutes": (time.perf_counter() - started) / 60}


def main() -> int:
    # Model output carries emoji and this console is cp950. Printing a sample must not be able
    # to destroy a run whose numbers are already computed — it happened here, and in
    # harvest_talk before it.
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("kol_id")
    ap.add_argument("--n", type=int, default=250, help="how many fan messages")
    ap.add_argument("--k", type=int, default=3, help="candidates per message")
    ap.add_argument("--turns", type=int, default=1,
                    help="turns per conversation; >1 produces mid-conversation examples")
    ap.add_argument("--model", default=os.getenv("KOL_LLM_MODEL", "qwen2.5:7b"))
    args = ap.parse_args()

    r = build(args.kol_id, args.n, args.k, args.model, args.turns)
    print(f"\n  kept {r['kept']} ({r['train']} train / {r['val']} val, "
          f"{r.get('mid', 0)} mid-conversation), "
          f"rejected {r['rejected']}, {r['minutes']:.1f} min")
    print("  why rejected:")
    for w, c in r["why"].items():
        print(f"    {w:<26} {c}")
    print(f"\n  -> {OUT / (args.kol_id + '-chat-train.jsonl')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
