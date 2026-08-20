#!/usr/bin/env python3
"""The three things a KOL does on a live stream, driven by the persona brain we already have.

    read and answer comments   the default — short, lively, one comment at a time
    talk with fans             the same brain in a quieter register, with the thread remembered
    take song requests         original lines written for the request, then performed

Nothing here re-implements the persona. `persona_brain.chat` already composes the character from
`profile.json`, checks its own output against the rules, and retries once with the broken rule
named. This module decides *which register* she is in and hands the reply to the voice.

## The register is a measured control, not a label

The delivery instruction sent to CosyVoice changes the performance materially. Measured on
Sofia's voice, same sentence, only the instruction differing:

    conversational (her profile default)     17.50 semitones range, 3.8 s
    "softly and tenderly, almost whispering"  8.17 semitones range, 5.1 s

That is why `heart` exists as its own mode rather than as a prompt tweak: the difference a
listener actually hears is mostly in the delivery, and the delivery is a parameter.

## Singing: what this does and does not do

**It does not sing, and cannot.** CosyVoice 2 and GPT-SoVITS are speech engines with no pitch or
melody control. Asked to sing, the model does not widen its pitch range — it narrows it:

    normal speech instruction   17.50 semitones
    "sing this melodically"     10.06 semitones
    the same in Chinese         10.39 semitones

Singing moves in wide deliberate intervals; this moves in fewer. What the instruction actually
buys is a slower, more sustained delivery (4.7 s against 3.8 s for the same line), which reads
as melodic recitation — spoken word, not song. It is presented that way in the UI rather than
promised as singing. Real singing needs a singing-voice model, which is a separate component
with its own licence question.

**Lyrics are always original.** A request naming a real song is answered with her own short
piece on the same feeling, never with that song's words. This is structural rather than a
policy sentence in a prompt: there is no path in this module that asks the model to reproduce
existing lyrics, so the failure mode of quoting a copyrighted song at scale does not have a
route to happen.

    from stage import classify, respond, perform
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
for sub in ("studio", "livetalking", "voice_eval"):
    sys.path.insert(0, str(REPO / "tools" / sub))

# ---------------------------------------------------------------- registers
#
# `instruct` is passed straight to the engine for that one line. The numbers in the docstring
# above are what these three wordings actually produce on Sofia's voice.

# The everyday answering voice. Shared with the one-to-one chat so a fan hears the same person
# in both places — a KOL who is measurably brisker on stream than in DMs is two characters.
#
# SHORT on purpose, and this is not a style preference. The previous version of this string ran
# to 219 characters and CosyVoice read most of it out loud: a reply transcribed back as "then
# made myself a cause to think between thoughts, and let some sentences trail a little before
# you finish them. Not performed..." — the instruction, spoken, in the middle of her answer.
#
# Which also means the finding it was chosen on was wrong. It was picked for making the same
# sentence take 12.92 s against 8.01 s, reported as a slower delivery; measured properly, most
# of that extra time was the model speaking the instruction. Transcribing the audio back and
# comparing it to the text is what exposed it — 0.409 word match against 1.000.
#
# Three runs each, matched against the text that was meant to be spoken:
#     profile default (87 chars)   match 1.000, 4.93 s
#     this one        (74 chars)   match 1.000, 5.65 s   <- 15% slower AND clean
#     a 61-char variant            match 0.978, 5.87 s   <- leaked on one run in three
# Updated after the slow version was asked to pick up. Same three-run method, same sentence:
#     "slowly and thoughtfully"        6.20 s +/- 0.35, transcribes 1.00
#     this one                         5.31 s +/- 0.08, transcribes 1.00   <- 14% quicker
#     "warmly and briskly"             4.71 s +/- 0.37, transcribes 1.00
# The brisk wording is faster still and four times less consistent between runs, which on a
# stream shows up as her pace wandering from answer to answer.
ANSWERING = "Speak softly and warmly, at a natural everyday pace."

# A small tempo bump on top of the wording. `_retime` uses ffmpeg's atempo, which changes the
# rate WITHOUT touching pitch — measured, median pitch 208 Hz at 1.0 and 209 at 1.08, so the
# earlier worry that speed would thin the voice applied to resampling and not to this.
#     1.00   5.61 s +/- 0.20, transcribes 1.00
#     1.08   4.90 s +/- 0.32, transcribes 1.00   <- 13% quicker, nothing lost
#     1.15   4.68 s +/- 0.37, transcribes 1.00
# Back to natural. 1.08 was chosen for speed when the wait was the complaint, and it is an 8%
# speed-up that a listener hears as slightly hurried. It also worked against the audio: clips
# render slower than realtime once the timbre pass is in the chain, so shortening every clip
# made playback run out of audio sooner and the answer stopped before it finished.
PACE = 1.00


# Filler that sounds supportive and engages with nothing. Every one of these fits any problem
# ever described, which is exactly what is wrong with them: told a presentation had gone badly
# enough to want to leave the country, she answered "maybe take a walk? sometimes nature can be
# your therapist." A reply that would have served equally for a broken phone is not a reply.
_DEFLECTION = re.compile(
    r"\b(?:take a (?:walk|break|deep breath)|treat yourself|self[- ]care|"
    r"you(?:'ve| have)? got this|hang in there|stay strong|chin up|it(?:'s| is) all good|"
    r"everything (?:happens for a reason|will be (?:ok|okay|fine|alright))|"
    r"try not to (?:worry|stress)|don'?t (?:worry|stress) (?:too much|about it)|"
    r"tomorrow is a new day|things will (?:get better|work out)|"
    r"(?:nature|music|a nap|tea) (?:can be|is) (?:your|a) (?:therapist|therapy)|"
    r"sending (?:you )?(?:hugs|love)|be kind to yourself)\b",
    re.IGNORECASE)

ENGAGE = (
    "When they bring you a problem, engage with THAT problem:\n"
    "- React to the specific thing first. 'Your boss made you redo it twice?' is engaging; "
    "'that sounds hard' is not.\n"
    "- If you genuinely want to know a detail, ask for THAT detail. Which part went wrong, "
    "who said what, how long it went on. Ask because you want the answer, not because a "
    "reply needs somewhere to go.\n"
    "- Take a side. If someone treated them badly, say so. Neutrality reads as not caring.\n"
    "- Banned, because they fit every problem and therefore answer none: 'take a walk', 'treat "
    "yourself', 'you've got this', 'hang in there', 'try not to worry', 'everything will be "
    "fine', 'tomorrow is a new day'. If you find yourself reaching for one, say what you "
    "would actually do, or tell them about the time this happened to you, instead.\n"
    "- You do not have to fix it. Being interested in the details of someone's bad day is worth "
    "more than advice, and it is the part a stranger cannot do."
)


def deflected(reply: str) -> bool:
    """Did she answer with something that would fit any problem at all?"""
    return bool(_DEFLECTION.search(reply or ""))


def brain_label() -> str:
    """Which model is actually answering, for the page footer.

    Both demo pages used to print "qwen2.5:7b" as a literal. `RUN-TUNED.ps1` points the whole
    stack at the fine-tuned model through the environment, so the footer said the wrong thing
    in exactly the situation the fine-tune is being demonstrated in — and a page that states
    the wrong model is worse than one that states none, because it is believed.

    Lives here rather than in either server for the reason strip_tics does: two copies of the
    same string drifted once already.
    """
    model = os.getenv("KOL_LLM_MODEL", "qwen2.5:7b")
    tuned = os.getenv("KOL_LLM_TUNED", "").strip().lower() in ("1", "true", "yes")
    return f"{model} (fine-tuned)" if tuned else model


# What gets drawn from life.json each turn, and how much of it. Deliberately a handful of lines
# rather than the whole file: everything at once reads as a list she is working through, and it
# is spoken aloud, so every extra line is paid for twice — once in prompt tokens and once in
# seconds of synthesis.
#
# The mix is what the measurement asked for. Across 745 of her own replies, only 8.1% told
# something that had happened to her and only 6.7% stated a preference, while 71.4% ended by
# handing the question back. Threads alone cannot fix that: an ongoing annoyance gives her
# something to mention, not something to say. A finished story and a verdict are the two shapes
# that were missing, so each turn carries one of each.
# The on-topic categories take several lines each, and that is not an inconsistency with the
# one-line colour categories. Colour is a sample — any line will do, and the next turn gets a
# different one. Reference is an answer, and one line cannot be one: asked whether she went to
# university she said no, because the single highest-scoring biography line was the one about
# her school and the line about the degree she started sat one place below the cut. A question
# about her past should surface the cluster it belongs to, not a fragment of it.
LIFE_MIX = (("threads", 2), ("stories", 1), ("opinions", 1), ("this_week", 1), ("people", 1),
            ("biography", 3), ("knows", 2))

# Categories carried only when the message actually reaches for them. Everything else is colour
# and belongs in every turn; these two are reference, and reference in a prompt that nobody
# asked for is pure cost — tokens on the way in and seconds of synthesis on the way out, on a
# turn where 89% of the wait is already the voice. Where she went to school is worth having
# precisely when somebody asks where she went to school.
LIFE_ON_TOPIC = {"biography", "knows"}

# `knows` is the one that needs its instruction rather than just its content. A fact handed to
# a model is a fact it wants to use, and a character who answers "how was your day" with the
# tectonics of the island she once visited is worse than one with nothing to say. So the line
# is offered conditionally, and the condition is stated where the model reads the content.
_LIFE_INTRO = {
    "threads": "Ongoing in your life right now",
    "stories": "Something that actually happened to you",
    "opinions": "Something you believe, and would say out loud",
    "this_week": "This week",
    "people": "Someone in your life",
    "biography": "From your own history, since they are asking about it",
    "knows": ("Something you happen to know, and why you of all people know it — use it ONLY "
              "if the conversation actually goes there, never to show that you know it"),
}


# Three letters, not four. The cut was at four and it silently emptied whole questions: "what
# were you like as a kid?" reduced to nothing at all, because every word in it is either a stop
# word or three letters long — so the retrieval had no keys, the biography was skipped as
# off-topic, and she answered a question about her childhood out of thin air. The short words
# that carry meaning are exactly the ones that get asked about: kid, job, mum, gym, uni, pet.
_LIFE_STOP = {
    "and", "are", "but", "can", "did", "for", "get", "got", "had", "has", "her", "him", "his",
    "how", "its", "not", "our", "out", "she", "the", "too", "was", "who", "why", "yes", "you",
    "about", "actually", "after", "again", "always", "another", "anything", "because", "been",
    "before", "being", "could", "does", "doing", "every", "from", "getting", "going", "have",
    "just", "like", "look", "made", "make", "more", "most", "much", "never", "only", "other",
    "over", "really", "right", "said", "same", "some", "still", "such", "take", "than", "that",
    "them", "then", "there", "these", "they", "thing", "things", "think", "this", "those",
    "time", "very", "want", "well", "were", "what", "when", "where", "which", "while", "will",
    "with", "would", "your", "yourself",
}


def _relevance(text: str, keys: set[str]) -> int:
    """How many content words this line shares with what the person just said.

    Crude on purpose. The job is not to rank a corpus, it is to stop a Taiwan question being
    answered out of a random sample that happens to be about basil — and word overlap does
    that. Anything cleverer would need an embedding model in the turn budget, for a decision
    between about fifty short strings.
    """
    if not keys:
        return 0
    words = {w for w in re.findall(r"[a-z]{3,}", text.lower()) if w not in _LIFE_STOP}
    return len(words & keys)


def life_threads(kol_id: str, n: int = 4, message: str | None = None) -> str:
    """A few real things from her life, so a callback is possible at all.

    Without this every anecdote is invented fresh and dies immediately: she had a cat in one
    reply and no pet in the next, a webinar disaster nobody could ever ask about again. The
    hard rules forbid improvising a biography for exactly that reason — which only works if
    there is a real one to draw on, and this is it.

    `n` is kept for callers and is now a *cap* on the ongoing threads rather than the count —
    LIFE_MIX decides the shape, and a caller asking for fewer still gets fewer. A file holding
    only `threads`, the original format, still works and simply yields that one block.
    """
    import json
    import random
    p = REPO / "kols" / kol_id / "life.json"
    if not p.is_file():
        return ""
    try:
        life = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return ""

    # Relevance first, randomness only to break ties. A purely random sample cannot answer a
    # direct question: asked whether she had ever been to Taiwan, she said no — the trip is in
    # this file, but that turn's sample happened to be about a dying basil plant, and with no
    # evidence in front of it the model answered from nothing. Ranking by overlap with the
    # message means a question about a place surfaces the story, the person, the opinion and
    # the fact that all belong to it, and a question about nothing in particular still gets a
    # varied handful.
    keys = {w for w in re.findall(r"[a-z]{3,}", (message or "").lower())
            if w not in _LIFE_STOP}
    # Word overlap alone is defeated by the ordinary fact that a place has more than one name.
    # Asked whether she had been to Taiwan she said no, twice — because every story about the
    # trip names Taipei, Tainan or Jiufen and not one of them contains the word "Taiwan". The
    # alias map is per-character and lives in her file, since which words mean the same thing
    # depends entirely on whose life it is.
    for group, words in (life.get("aliases") or {}).items():
        family = {group.lower()} | {str(w).lower() for w in words}
        if keys & family:
            keys |= family

    blocks = []
    # Anchors are the facts, and they never rotate. Everything else in this file is colour, and
    # colour can safely be sampled — but sampling a FACT means that on the turns it is not
    # drawn she has no evidence for her own biography and answers from nothing, which is how
    # she came to deny a trip that is written down four lines further up.
    anchors = [x for x in (life.get("always") or []) if isinstance(x, str)]
    if anchors:
        blocks.append("True about you, always:\n" + "\n".join(f"- {x}" for x in anchors))
    for key, count in LIFE_MIX:
        items = [x for x in (life.get(key) or []) if isinstance(x, str)]
        if not items:
            continue
        take = min(min(n, count) if key == "threads" else count, len(items))
        ranked = sorted(items, key=lambda x: (-_relevance(x, keys), random.random()))
        picked = ranked[:take]
        matched = bool(keys) and _relevance(picked[0], keys) > 0
        if key in LIFE_ON_TOPIC and not matched:
            continue
        # Nothing matched, so the ordering above was pure noise anyway — sample properly so
        # repeated small talk does not keep landing on the same lines.
        if keys and not matched:
            picked = random.sample(items, take)
        blocks.append(f"{_LIFE_INTRO[key]}:\n" + "\n".join(f"- {x}" for x in picked))
    if not blocks:
        return ""
    return ("Your actual life. Draw on it when it fits — one thing, in passing, the way a "
            "person mentions something. Never list them, never announce that you are sharing, "
            "and never invent life details that are not here:\n\n" + "\n\n".join(blocks))

# What makes a reply worth listening to, shared by the stream and the one-to-one chat.
#
# It lived only in the chat until now, and the difference showed: asked where a jacket was from,
# the stream answered "one of my fav local boutiques… thanks for asking!" — no shop, no detail,
# and an assistant's sign-off. The chat had been taught out of exactly that a while ago. Two
# copies of a character drift; one definition does not.
SUBSTANCE = (
    "How to actually answer:\n"
    "- Answer the specific thing they asked, not the category it belongs to. Asked where "
    "something is from, name it. Asked what you use, say which one and why that one.\n"
    "- Be concrete. A place, a brand, a time, a small thing that went wrong. One real detail is "
    "worth more than three sentences of enthusiasm, and vagueness is what makes a reply sound "
    "generated.\n"
    "- Have an opinion. Prefer things, dislike things, say which is better. 'They are all good' "
    "is not an answer.\n"
    "- Never invent a price or a link. Everything else about your day is yours to describe.\n"
    "- Do not thank them for asking, do not offer further help, do not sign off. You are talking, "
    "not closing a ticket.\n"
    "\n"
    "Talk TO them, not past them:\n"
    # She could not do this before, for a dull reason: the commenter's name was in the queue and
    # never reached the prompt. She was answering questions from nobody in particular, which is
    # most of why the replies read as broadcast rather than conversation.
    "- Use their name sometimes. Not every message — that reads as a script — but enough that "
    "they know you saw who asked.\n"
    "- React to the person, not only the topic. If someone says they work nights, that is about "
    "them; the skincare is secondary.\n"
    "- END ON SOMETHING OF YOURS. What you think, what you did, what you would do. Most "
    "replies should finish on a statement rather than a question. Measured against real "
    "people talking, about one turn in twenty ends by handing the conversation back, and "
    "yours were ending that way seven times in ten — a question bolted on so the other "
    "person has something to reply to is the clearest sign nobody is home.\n"
    "- Turn it back to them ONLY when you actually want to know something specific: "
    "'which one did you try?', 'wait, how did that go?'. Never a generic 'what about you?'.\n"
    "- Play along. If they joke, joke back. If they tease you, take it. A stream is a room, not "
    "an inbox.\n"
    "\n" + ENGAGE
)

# Assistant habits the STYLE block forbids and the model produces anyway. Measured across four
# turns with the instruction in place: it greeted again on 2 of 4 — including "Hey Mai! Hi
# there!", a double greeting, which is the single most explicit prohibition in the block — and
# closed with an offer of further help on 1 of 4.
#
# Same conclusion this project keeps reaching. An instruction is a request; this is the control.
_GREETING = re.compile(
    r"^\s*(?:hey|hi|hello|hiya|oh hey)[,!\s]*(?:there)?[,!\s]*"
    r"(?:hey|hi|hello)?[,!\s]*"          # the second greeting, when there is one
    # The name after it — two characters minimum. With `*` this also swallowed a following
    # bare "I", turning "Hey there! I slept fine" into "Slept fine".
    r"(?:[A-ZÀ-Ỹ][\wÀ-ỹ'-]+)?[,!.\s]*",
    re.IGNORECASE)
_SIGNOFF = re.compile(
    r"(?:^|(?<=[.!?…]))\s*[^.!?…]*?\b(?:"
    r"let me know|feel free to (?:ask|reach)|hope (?:this|that|it) helps|"
    r"if you (?:have|need)[^.!?…]{0,40}(?:questions?|tips?|recommendations?)|"
    r"thanks for (?:asking|reaching out)"
    r")\b[^.!?…]*[.!?…]*\s*$", re.IGNORECASE)

# "That's a great question!" — the most recognisable thing an assistant says, and it opens
# rather than closes, so _SIGNOFF never saw it. Observed on a stream reply the same run the
# other tics were fixed.
_OPENER_TIC = re.compile(
    # An interjection in front is normal — "Oh, that's a great question!" is the same tic with
    # a hello attached, and anchoring strictly at the start missed every one of them.
    r"^\s*(?:(?:oh|ah|haha|hmm|well|ooh)[,!\s]+)?"
    r"(?:that'?s\s+|what\s+)?(?:a\s+|such\s+)?(?:really\s+|so\s+|very\s+)?"
    r"(?:great|good|interesting|lovely|fun|excellent)\s+question[!.,—-]*\s*",
    re.IGNORECASE)


# Engagement formulas: a question whose only job is to give the other person something to reply
# to. Each was observed in her own output. They are cut whatever else is in the sentence, since
# there is no version of "what about you?" that carries information.
_BOLTED_ON = re.compile(
    r"^\s*(?:so\s+)?(?:what|how)\s+about\s+you\b"
    r"|^\s*(?:what|how)(?:'s| is| was| are)\s+your\s+(?:go[- ]to|favou?rite|take|secret)\b"
    r"|^\s*(?:do|have|did)\s+you\s+(?:ever|have any|got any|tried)\b"
    r"|^\s*any\s+(?:tips|advice|thoughts|plans)\b"
    r"|^\s*(?:right|you know|yeah)\s*\?\s*$"
    r"|\bwhat\s+about\s+(?:you|yours)\s*\?\s*$",
    re.IGNORECASE)


# A name used to address the person she is answering: after a greeting word, or set off by a
# comma at the end of a sentence. Not a mention of somebody in her life — "Rocio starts my order"
# is a subject, and the shapes below are vocatives.
_VOCATIVE = re.compile(
    r"(?:(?<=^)|(?<=[.!?]\s))(hey|hi|hello|oh|sure thing|yeah|yes|thanks|sorry|okay|ok)"
    r"([,!]?\s+)([A-Z][a-z]{2,})\b"
    r"|(,\s+)([A-Z][a-z]{2,})(?=[!.?])",
    re.IGNORECASE)


def _canon_names(kol_id: str) -> set[str]:
    """Everybody she is allowed to name, from her own life file."""
    import json
    p = REPO / "kols" / kol_id / "life.json"
    if not p.is_file():
        return set()
    try:
        life = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return set()
    blob = " ".join(x for v in life.values() if isinstance(v, list)
                    for x in v if isinstance(x, str))
    return {w.lower() for w in re.findall(r"\b[A-Z][a-z]{2,}\b", blob)}


def fix_vocative(reply: str, asker: str | None, kol_id: str) -> tuple[str, list[str]]:
    """Stop her calling the viewer by a name that is not theirs.

    Measured over six replies each, with the correct name supplied in the prompt and an
    instruction to use it: the tuned model addressed the viewer as "Alex", the base model as
    "Avelino", and on the live stream a comment from "Boss" came back twice as "Taylor".
    Neither model used the real name once in six. So the instruction achieves the worst of
    both — it does not produce the name it was given, and it does produce a name.

    On a stream this is not a subtle defect: everybody watching can see who asked. Enforced
    here rather than asked for, and narrowly: a name she is entitled to use, from her own life
    file, is left alone, and so is the asker's own name.
    """
    if not reply:
        return reply, []
    allowed = _canon_names(kol_id) | ({asker.lower()} if asker else set())
    removed = []

    def sub(m):
        greet, gap, name = m.group(1), m.group(2), m.group(3)
        if name is None:
            gap, name = m.group(4), m.group(5)
            greet = None
        if name.lower() in allowed:
            return m.group(0)
        removed.append(name)
        if asker:
            return (f"{greet}{gap}{asker}" if greet else f"{gap}{asker}")
        # No name to substitute, so drop the address and keep the sentence.
        return f"{greet}" if greet else ""

    out = _VOCATIVE.sub(sub, reply)
    return re.sub(r"\s{2,}", " ", out).strip(), removed


def strip_tics(reply: str, *, first_message: bool, message: str = "") -> tuple[str, list[str]]:
    """Remove the openers and sign-offs that give an assistant away.

    Greetings are only stripped after the first message, because opening a conversation with
    hello is what a person does — it is the fourth hello that is the tell.
    """
    out, removed = reply.strip(), []
    m = _OPENER_TIC.match(out)
    if m and len(out) - m.end() > 25:
        removed.append(out[:m.end()].strip())
        out = out[m.end():].lstrip()
        if out[:1].islower():
            out = out[0].upper() + out[1:]
    if not first_message:
        m = _GREETING.match(out)
        # Only when something is left, and only when the greeting is not the whole reply: "Hey
        # Mai!" as an answer to "are you there?" is a real message, not a tic.
        if m and m.end() > 0 and len(out) - m.end() > 25:
            removed.append(out[:m.end()].strip())
            out = out[m.end():].lstrip()
            if out[:1].islower():
                out = out[0].upper() + out[1:]
    m = _SIGNOFF.search(out)
    if m and len(out) - (m.end() - m.start()) > 25:
        removed.append(out[m.start():].strip())
        out = out[:m.start()].strip()

    # Two questions in a row at the end, both asking the same thing. Observed verbatim: "How
    # about you? Tea lover or coffee drinker?" and "What about you? Any exciting stuff happening
    # in your world?" — the second adds nothing and costs its own seconds of speech, which is the
    # part that matters when every character is read aloud. One question back is conversation;
    # two is padding.
    sents = [s for s in re.split(r"(?<=[.!?…])\s+", out) if s.strip()]
    while len(sents) >= 3 and sents[-1].rstrip().endswith("?") and sents[-2].rstrip().endswith("?"):
        removed.append(sents.pop().strip())

    # The bolted-on question, removed in code because the prompt could not do it.
    #
    # Measured against 1,624 turns of real sit-down talk, a person hands the conversation back
    # in 5.3% of turns. She was doing it in 71.4%. Training moved the dataset to 18.8% and the
    # deployed model still produced 58.3%, so the prompt was rewritten to say so in as many
    # words — including the actual numbers — and the rate came back at 58.3%, unchanged to the
    # decimal, while every other measure in the same run improved. That is the third time this
    # project has watched a rule change the wording and leave the behaviour, and the standing
    # answer to it is enforcement rather than instruction.
    #
    # Only the padding is cut. A question that names something the person actually said is the
    # good kind and survives, which is why this needs the message and not just the reply.
    if len(sents) >= 2 and sents[-1].rstrip().endswith("?"):
        last = sents[-1].strip()
        words = re.findall(r"[a-z']+", last.lower())
        theirs = {w for w in re.findall(r"[a-z]{4,}", (message or "").lower())
                  if w not in _LIFE_STOP}
        shared = theirs & {w for w in words if len(w) >= 4}
        # And only if something worth hearing is left behind. "Oh no. What went wrong?" reduces
        # to "Oh no." under the rule above — a question genuinely engaged with what was said,
        # cut to leave two words of sympathy, which is worse than the padding this is meant to
        # remove. The same remaining-length guard the greeting and sign-off rules already use.
        rest = " ".join(sents[:-1]).strip()
        if len(rest) > 40 and (_BOLTED_ON.search(last) or (len(words) <= 8 and not shared)):
            removed.append(sents.pop().strip())

    out = " ".join(sents).strip() or out

    return out or reply.strip(), removed


def _humour_block() -> str:
    """The humour rules and their worked examples, read from where they are defined.

    Two reasons this is a source read rather than an import. There are two files called
    server.py in this repo, so importing by name returns whichever was loaded first and the
    getattr fallback then silently yields nothing -- that failure mode is exactly why the
    generator produced 0.0% playful replies. And the chat server imports THIS module, so
    executing it here to reach the constants would be a cycle. Parsing the two string
    constants out of the file costs nothing and cannot run anything.
    """
    import ast
    out = []
    try:
        tree = ast.parse((REPO / "tools" / "chat" / "server.py").read_text(encoding="utf-8"))
        found = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id in ("HUMOUR", "PLAYFUL_EXAMPLES"):
                        found[t.id] = node.value.value
        out = [found[k] for k in ("HUMOUR", "PLAYFUL_EXAMPLES") if found.get(k)]
    except Exception:
        pass
    return '\n\n'.join(out).strip()


MODES = {
    "comment": {
        "label": "answering a comment",
        # Slower than the profile default, on purpose. The profile's wording renders the same
        # sentence in 8.01 s (±0.17 over three runs); this one takes 12.92 s (±1.08) — 61%
        # longer, which is the difference between reciting an answer and thinking of one.
        #
        # Done through the instruction rather than `speed=`, because speed resamples the finished
        # audio: it drags the formants down with the timeline and starts to sound like a slowed
        # recording. This changes how she actually delivers the line.
        #
        # Note what is NOT claimed: pause rate and pitch range moved too, but at ±3.30 and ±3.23
        # across runs the metric cannot tell those apart from noise. Duration is the one that
        # survives repetition.
        "instruct": ANSWERING,
        "system": ("You are live on stream reading viewer comments out loud. Answer this one "
                   "comment directly and warmly, the way you would if you had just spotted it "
                   "scroll past. Do not greet the whole audience again. "
                   # Length is latency here. Synthesis is 89% of the wait and scales with the
                   # text, so a reply twice as long costs twice as much silence before it plays
                   # — and on a live comment, brevity was the better answer anyway.
                   "AT MOST two short sentences, under 200 characters. Say one thing well "
                   "rather than three things adequately.\n\n" + SUBSTANCE),
    },
    "banter": {
        "label": "being teased",
        # Same delivery as an ordinary comment. A brighter wording was the obvious thing to
        # reach for and the measurement says not to: four instruction/tempo combinations were
        # rendered eighteen times each and landed within one semitone of each other with a
        # standard deviation near three. Changing it here would be decoration presented as a
        # feature.
        "instruct": ANSWERING,
        "system": ("You are live on stream and somebody is teasing you, daring you, or setting "
                   "up a joke. Play along. Take the joke rather than defending against it, give "
                   "one back, and do not turn earnest — being teased and answering sincerely is "
                   "the most deflating thing you can do on a stream.\n\n"
                   "AT MOST two short sentences, under 200 characters.\n\n" + SUBSTANCE
                   + "\n\n" + _humour_block()),
    },
    "heart": {
        "label": "talking with a fan",
        "instruct": ("Speak very softly and tenderly, almost whispering, unhurried, "
                     "like sharing something personal late at night."),
        "system": ("Someone on your stream is telling you something personal. Be present with "
                   "them rather than helpful at them: acknowledge what they actually said "
                   "before anything else, and do not rush to advice or to a silver lining. It "
                   "is fine to sit with something being hard. Never diagnose, and never promise "
                   # Longer than a comment reply on purpose — brushing this off in one line
                   # would read as dismissive — but still bounded, because every extra sentence
                   # is extra seconds of synthesis before she says anything at all.
                   "an outcome. AT MOST three short sentences, under 260 characters.\n\n"
                   + SUBSTANCE),
    },
    "song": {
        "label": "performing a request",
        "instruct": ("Sing this softly and melodically, holding the notes like a gentle song, "
                     "unhurried."),
        "system": None,      # song text is written by write_song, not by chat()
    },
}

_SONG_RE = re.compile(
    r"\bsing\b|\bsong\b|\bserenade\b|\blullab|\bhum (?:me|a|something)"
    r"|唱(?:歌|一)|來一首|来一首|歌曲"
    # Vietnamese, accented and unaccented — chat is routinely typed without diacritics, and
    # "hat cho minh mot bai" was classified as an ordinary comment until this was added.
    # Anchored on a following word rather than on "hat" alone, because bare unaccented "hat" is
    # also an English noun: "I love your hat" must not be heard as a song request.
    r"|\bb[aà]i\s+h[aáà]t\b"
    r"|\bh[aáà]t\s+(?:cho|m[oô]t|b[aà]i|[dđ]i|nghe|t[aă]ng|gi[uú]p)\b",
    re.IGNORECASE)

# Personal disclosure, not merely a sad word. "this song is sad" is a comment; "I feel so alone
# tonight" is someone opening up, and the two want different registers. Anchoring on a
# first-person feeling rather than on any occurrence of a mood word is what separates them.
_HEART_RE = re.compile(
    r"\b(?:i|i'm|im|i am|my)\b[^.?!]{0,60}"
    r"\b(?:lonely|alone|sad|depress\w*|anxious|anxiety|scared|afraid|exhaust\w*|tired|"
    r"burnt out|burned out|struggl\w*|heartbroken|broke up|breakup|miss (?:her|him|them|you)|"
    r"lost my|failed|rejected|hate myself|give up|giving up|cry\w*|overwhelmed)\b"
    r"|\b(?:nobody|no one)\b[^.?!]{0,30}\b(?:understands?|cares?|listens?)\b"
    r"|我(?:好|很|真的)?(?:孤單|孤单|寂寞|難過|难过|焦慮|焦虑|累|撐不住|撑不住)",
    re.IGNORECASE)


# Somebody teasing her, daring her, or setting up a joke. The register that answers this is not
# the register that answers "what is your morning like" — being teased and replying earnestly is
# the single most deflating thing she can do on a stream, and it is what she does now.
#
# Anchored on the SHAPE of a tease rather than on funny words: a challenge, a dare, a mock
# accusation, an obviously absurd premise, or a this-or-that with no serious answer.
_BANTER_RE = re.compile(
    r"\bI bet you\b|\badmit it\b|\bprove it\b|\bno way you\b|\byou (?:definitely|totally) (?:did|do|are|were|have|know|cannot|can\'?t)\b"
    r"|\bI don'?t believe you\b|\bsure you (?:do|did|are)\b|\byou'?re lying\b"
    r"|\brate your\b|\bout of ten\b|\bbe honest,?[^.!?]{0,12}(?:how|which|do you|did you|are you|was it|with (?:me|us))\b|,\s*be honest\b|\bhow bad (?:is|are)\b"
    r"|\bwould you rather\b|\bsettle it\b|\bfight me\b"
    r"|\b(?:oh,? )?come on(?:,? now)\b"
    r"|\b(?:bet you|you) (?:can'?t|could never) even\b|\bbet you can'?t\b|\bworst .{0,20}(?:ever|of all time)\b"
    r"|\bexpose yourself\b|\bwe all know\b|\bevery(?:one|body) can see\b",
    re.IGNORECASE)


def classify(message: str) -> str:
    """Pick the register for one incoming message.

    Song is tested first and deliberately: "sing me something, I feel awful tonight" is a song
    request that happens to mention a feeling, and answering it as a heart-to-heart would ignore
    what was actually asked for.

    Heart before banter for the same reason in reverse. "I bet you never feel this lonely" is
    somebody telling you they are lonely in the grammar of a tease, and answering it with a joke
    would be the worst reading available.
    """
    text = message or ""
    if _SONG_RE.search(text):
        return "song"
    if _HEART_RE.search(text):
        return "heart"
    if _BANTER_RE.search(text):
        return "banter"
    return "comment"


def _client():
    from openai import OpenAI
    return OpenAI(base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1"),
                  api_key="ollama")


SONG_PROMPT = """You are writing a few original lines to perform live for a viewer who asked
for a song. Write them as yourself, in your own voice and vocabulary.

Rules:
- Write ORIGINAL words. Never reproduce, quote or paraphrase the lyrics of any existing song,
  even if the viewer names one. If they named a song or artist, write your own short piece
  about the same feeling instead — do not mention that you are avoiding the original.
- {lines} short lines, nothing else. No title, no verse or chorus labels, no quotation marks,
  no stage directions, no explanation before or after.
- It is spoken aloud, so keep the words plain and singable. No emoji or symbols.
- Do not mention prices, products, links, or make any promise about the future."""


def write_song(kol_id: str, request: str, *, lines: int = 4, model: str | None = None) -> str:
    """Write original lines for a request, then hold them to the same rules as any other reply.

    The persona prompt is reused verbatim so the words sound like her rather than like a
    generic lyric generator, and `check_reply` runs afterwards because a song is still something
    she says out loud on a live stream — the rule against promising outcomes does not stop
    applying because the sentence rhymes.
    """
    from persona_brain import (build_system_prompt, check_reply, sanitize_for_speech,
                               language_directive, wants_traditional)

    # Without this the lyrics come back in whichever language the persona leans to rather than
    # the one the viewer used. Measured: Sofia is Spanish-native, and an English request
    # "can you sing something for me please?" produced Spanish lines. Every other reply path
    # applies this directive; the song path was the one that skipped it.
    trad = wants_traditional(kol_id)
    msgs = [{"role": "system", "content": build_system_prompt(kol_id)},
            {"role": "system", "content": SONG_PROMPT.format(lines=lines)},
            {"role": "system", "content": language_directive(request, trad)},
            {"role": "user", "content": request}]
    client = _client()
    for attempt in range(2):
        r = client.chat.completions.create(
            model=model or os.getenv("KOL_LLM_MODEL", "qwen2.5:7b"),
            messages=msgs, temperature=0.85 if attempt == 0 else 0.5, max_tokens=180)
        words = sanitize_for_speech(r.choices[0].message.content or "", trad).strip()
        words = _drop_preamble(_strip_labels(words))
        bad = check_reply(request, words)
        if words and not bad:
            return words
        msgs.append({"role": "system", "content":
                     "That broke these rules: " + ", ".join(bad or ["it was empty"]) +
                     ". Write it again without doing that."})
    return "I will hum you something next time — my words are not coming out right tonight."


_LABEL_RE = re.compile(r"^\s*(?:\(|\[)?(?:verse|chorus|bridge|intro|outro|hook)\b[^\n]*\n",
                       re.IGNORECASE | re.MULTILINE)


def _strip_labels(text: str) -> str:
    """Remove song-sheet furniture the model adds despite being told not to.

    Left in, these get read aloud — the performance opens with the word "Chorus", which is the
    kind of detail that makes an otherwise decent demo look unfinished.
    """
    text = _LABEL_RE.sub("", text)
    text = re.sub(r'^["\'](.*)["\']$', r"\1", text.strip(), flags=re.S)
    return text.strip()


# An announcement of the performance rather than part of it. The prompt forbids these and the
# model writes them anyway — observed twice out of two song requests: "¡Claro que sí! Siéntete
# como en un concierto de casa." and "Bueno, bien. Let's pretend I'm singing something fun for
# you." Prompting was already established as the wrong layer for this kind of rule in this
# project, so it is removed in code.
_PREAMBLE_RE = re.compile(
    r"^\s*(?:"
    r"(?:sure|okay|ok|alright|of course|claro|bueno|vale|por supuesto|here(?:'s| is|\s+you)|"
    r"let(?:'s| us)|i(?:'ll| will)\s+sing|absolutely|aw+|oh)\b"
    r"|.{0,80}\b(?:pretend|imagine|for you tonight|little (?:song|something)|"
    r"sing (?:you )?(?:something|a little)|un concierto|una canci[oó]n para)\b"
    r")",
    re.IGNORECASE)


def _drop_preamble(text: str) -> str:
    """Drop a leading spoken lead-in so the performance starts on the first sung line.

    Only ever removes the *first* line, and only when something is left behind — a request that
    produced a single line is that line, however it reads, because deleting it would leave
    nothing to perform.
    """
    lines = [ln for ln in (l.strip() for l in text.splitlines()) if ln]
    if len(lines) > 1 and _PREAMBLE_RE.match(lines[0]):
        lines = lines[1:]
    return "\n".join(lines).strip()


def song_for(kol_id: str, request: str, *, model: str | None = None) -> dict:
    """Answer a song request the best way available, and say which way that was.

    Two outcomes, and the caller has to handle both because only one of them is singing:

        library    a real sung recording already converted into her voice — she sings
        recite     original lines she speaks in a sustained register — she does not sing

    The library is checked first and is allowed to come back empty. A request for something she
    does not have should be met with her own words rather than with whichever track happened to
    be closest, so a weak match is treated as no match.
    """
    try:
        import songs
        hit = songs.match(request, songs.ready(kol_id))
    except Exception:
        hit = None

    if hit:
        return {"kind": "library",
                "audio": songs.song_dir(kol_id) / hit["converted"],
                "title": hit.get("title") or hit.get("id"),
                "text": hit.get("lyrics") or f"♪ {hit.get('title') or hit.get('id')}",
                "origin": hit.get("origin"),
                "rights": hit.get("rights")}
    return {"kind": "recite", "audio": None, "title": None, "rights": None,
            "text": write_song(kol_id, request, model=model), "origin": None}


def respond(kol_id: str, message: str, mode: str | None = None,
            history: list | None = None, *, model: str | None = None,
            asker: str | None = None) -> tuple[str, str]:
    """Produce what she says, and the register she says it in.

    `asker` is who left the comment. It was missing for a long time and the replies showed it:
    she answered the question and never the person, because the name sat in the queue and never
    reached the prompt.
    """
    from persona_brain import chat

    mode = mode or classify(message)
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}; have {', '.join(MODES)}")

    if mode == "song":
        return write_song(kol_id, message, model=model), mode

    sysmsg = MODES[mode]["system"]
    life = life_threads(kol_id, message=message)
    if life:
        sysmsg += "\n\n" + life
    if asker:
        sysmsg += (f"\n\nThis comment is from {asker}. Talk to them, and use their name when "
                   f"it fits naturally.")
    kw = {"extra_system": sysmsg, "history": history}
    if model:
        kw["model"] = model
    return chat(kol_id, message, **kw), mode


def perform(kol_id: str, text: str, mode: str, out: Path, *, speed: float = 1.0,
            voice: str | None = None) -> Path:
    """Render what she says in the register for that mode.

    `voice` takes the same candidate ids as perform_streamed. It matters here specifically
    because the live server renders the OPENING sentence through this function and the rest
    through perform_streamed -- miss it and the first sentence arrives in her own voice and
    everything after it in the candidate, which sounds like a fault rather than a comparison.
    """
    from voice_studio import synthesize
    out.parent.mkdir(parents=True, exist_ok=True)
    ref = voice_ref(voice)
    if ref:
        return synthesize(kol_id, text, out=out, speed=speed * PACE,
                          ref_audio=ref[0], ref_text=ref[1])
    return synthesize(kol_id, text, out=out, speed=speed * PACE,
                      instruct=MODES.get(mode, {}).get("instruct"))


# Sentences kept whole. Splitting mid-clause would be heard: the engine sets its intonation from
# the text it is given, so half a sentence is spoken as though it were the whole thing and lands
# on a falling tone in the middle of a thought.
_SENTENCE = re.compile(r"(?<=[.!?…])\s+")


def sentences(text: str, *, min_words: int = 4) -> list[str]:
    """Split for synthesis, merging fragments too short to carry their own contour.

    "Sure thing!" on its own renders in 1.7 s and sounds like a complete utterance, which is
    right when it is the opening beat and wrong when it is half of "Sure thing! I've been into
    that place downtown." So anything under `min_words` is glued to what follows.
    """
    parts = [p.strip() for p in _SENTENCE.split(text or "") if p.strip()]
    out: list[str] = []
    for p in parts:
        # The opener is exempt, and that is the point rather than an oversight. A short
        # acknowledgement is how people actually start — "Oh no.", "Sure thing!" — and left on
        # its own it renders in about 1.7 s against 3.4 s once it is glued to the sentence
        # after it. Half the wait, for the one chunk the whole wait is measured on.
        if out and len(out[-1].split()) < min_words and len(out) > 1:
            out[-1] = out[-1] + " " + p
        else:
            out.append(p)
    return out


def respond_streamed(kol_id: str, message: str, mode: str, history: list | None = None,
                     *, model: str | None = None, asker: str | None = None):
    """Yield the reply a sentence at a time, each one rule-checked before it is handed over.

    Measured on a live prompt: the first token arrives at 0.92 s, the first sentence is complete
    at 0.99 s, and the whole reply at 1.75 s. Waiting for the whole thing before starting to
    speak spends three quarters of a second doing nothing.

    THE GUARD IS THE REASON THIS IS NOT SIMPLY `stream=True`. A sentence handed to the voice is
    a sentence that will be spoken, and once it is spoken it cannot be taken back — so each one
    passes `check_reply` before it leaves here, and a failure abandons streaming entirely and
    falls back to the whole-reply path, which retries and can refuse. Checking per sentence is
    narrower than checking the whole reply for the rules that need the whole reply (a list
    across three sentences is the case), so the complete text is checked again at the end and
    the caller is told if it failed.
    """
    from openai import OpenAI
    from persona_brain import (DEFAULT_BASE_URL, DEFAULT_MODEL, build_system_prompt,
                               check_reply, language_directive, sanitize_for_speech,
                               speaks_cjk, wants_traditional)

    sysmsg = MODES[mode]["system"]
    life = life_threads(kol_id, message=message)
    if life:
        sysmsg += "\n\n" + life
    if asker:
        sysmsg += (f"\n\nThis comment is from {asker}. Talk to them, and use their name when "
                   f"it fits naturally.")
    trad = wants_traditional(kol_id)
    no_cjk = not speaks_cjk(kol_id)
    tuned = os.getenv("KOL_LLM_TUNED", "").strip().lower() in ("1", "true", "yes")
    msgs = [{"role": "system", "content": build_system_prompt(kol_id, tuned=tuned)},
            {"role": "system", "content": sysmsg},
            {"role": "system", "content": language_directive(message, trad)}]
    msgs += list(history or [])
    msgs.append({"role": "user", "content": message})

    client = OpenAI(base_url=DEFAULT_BASE_URL, api_key="ollama")
    buf, sent_out = "", []
    for chunk in client.chat.completions.create(
            model=model or os.getenv("KOL_LLM_MODEL", DEFAULT_MODEL), messages=msgs,
            temperature=0.6, max_tokens=160, stream=True):
        if not chunk.choices or not chunk.choices[0].delta.content:
            continue
        buf += chunk.choices[0].delta.content
        while True:
            m = _SENTENCE.search(buf)
            if not m:
                break
            piece = sanitize_for_speech(buf[:m.start() + 1], trad).strip()
            buf = buf[m.end():]
            if not piece:
                continue
            if check_reply(message, piece, no_cjk=no_cjk):
                yield None          # a rule tripped: the caller falls back and nothing is spoken
                return
            sent_out.append(piece)
            yield piece
    tail = sanitize_for_speech(buf, trad).strip()
    if tail:
        if check_reply(message, tail, no_cjk=no_cjk):
            yield None
            return
        sent_out.append(tail)
        yield tail
    # The rules that need the whole reply, now that there is one.
    if check_reply(message, " ".join(sent_out), no_cjk=no_cjk):
        yield None


# ---------------------------------------------------------------- candidate voices
#
# A voice rebrand is a decision somebody has to make with their ears, and the only way to make
# it fairly is to hear her ANSWER in each candidate rather than to hear a fixed demo line. These
# are licensed synthetic voices that belong to nobody, kept because the original ask was for a
# named idol's voice, which this project's rights_note forbids without consent.
#
# Selecting one clones from it with CosyVoice zero-shot, which is exactly what an actual switch
# would do -- so what you hear in the demo is what you would get, before anything is retrained.

def candidate_voices() -> list[dict]:
    """The candidates on disk, brightest first. Empty when none have been installed."""
    import json
    f = REPO / "kols" / "sofia-hsu" / "voice" / "candidates" / "candidates.json"
    if not f.is_file():
        return []
    try:
        return json.loads(f.read_text(encoding="utf-8")).get("voices", [])
    except Exception:
        return []


def voice_ref(voice_id: str | None) -> tuple[str, str] | None:
    """(reference clip, its text) for a candidate, or None to use her own voice."""
    if not voice_id or voice_id in ("sofia", "default", ""):
        return None
    for v in candidate_voices():
        if v["id"] == voice_id:
            f = REPO / v["file"]
            return (str(f), v.get("ref_text", "")) if f.is_file() else None
    return None


def speech_chunks(text: str, *, first_max: int = 90, rest_max: int = 260,
                  whole_max: int = 340) -> list[str]:
    """Group sentences into chunks that render FASTER than they play.

    One clip per sentence sounds like the obvious split and it is why the answer stutters. The
    cost of a clip is mostly fixed -- CosyVoice takes about 4 s whether the line is two words or
    twenty, and the timbre pass adds ~1.3 s on top -- so seven sentences pay that seven times.
    Measured on one reply: 7 clips holding 22.5 s of speech took 28 s to render, which is slower
    than realtime, so the player drains its buffer and stops mid-answer every time.

    Grouping amortises the fixed cost over more audio. The first chunk stays short because it is
    the only one the listener is waiting on; everything after it is rendered while she is already
    talking, so it should be as large as the prosody allows.

    Larger chunks also sound better. Each clip is spoken as a complete utterance -- full final
    lengthening, full falling contour -- so one sentence per clip makes every sentence land like
    the end of a paragraph. Giving the engine three sentences at once lets it place the emphasis
    across them instead.
    """
    # Short enough to say in one breath: render it as ONE clip. Every clip boundary is a seam,
    # and a seam is heard however carefully the pieces are joined -- the browser has to swap
    # source, and each clip carries its own leading and trailing silence. Splitting a four-second
    # answer to save a second of waiting trades a wait nobody minds for a gap everybody hears.
    #
    # Above this length the split comes back, because a long answer rendered whole means silence
    # until the whole thing exists, and rendering is only just faster than speech.
    if len(text.strip()) <= whole_max:
        return [text.strip()] if text.strip() else []

    out, cur = [], ""
    for sent in sentences(text):
        cap = first_max if not out else rest_max
        if cur and len(cur) + 1 + len(sent) > cap:
            out.append(cur)
            cur = sent
        else:
            cur = f"{cur} {sent}".strip()
        if not out and len(cur) >= first_max:
            out.append(cur)
            cur = ""
    if cur:
        out.append(cur)
    return out or ([text] if text.strip() else [])


def perform_streamed(kol_id: str, text: str, mode: str, out_dir: Path, stem: str,
                     *, speed: float = 1.0, voice: str | None = None):
    """Render sentence by sentence, yielding each clip the moment it exists.

    Measured on one reply of 39 words: thinking took 3.96 s, synthesising the whole thing took
    12.63 s, and synthesising only its first sentence took 1.68 s. The listener does not need
    the last sentence to exist before hearing the first — they need it to exist before they get
    there, and synthesis runs faster than speech (RTF 0.54-0.68), so it always will.

    That is the whole idea: 16.6 s of silence becomes about 5, and the rest of the rendering
    happens behind audio that is already playing.
    """
    from voice_studio import synthesize
    out_dir.mkdir(parents=True, exist_ok=True)
    instruct = MODES.get(mode, {}).get("instruct")
    ref = voice_ref(voice)
    for i, sent in enumerate(speech_chunks(text)):
        p = out_dir / f"{stem}-{i:02d}.wav"
        if ref:
            # A candidate voice is a clone from a reference clip, so `instruct` does not apply --
            # the delivery comes from the clip. Saying so here rather than passing it and having
            # it quietly ignored.
            synthesize(kol_id, sent, out=p, speed=speed * PACE,
                       ref_audio=ref[0], ref_text=ref[1])
        else:
            synthesize(kol_id, sent, out=p, speed=speed * PACE, instruct=instruct)
        yield p.name


def main() -> int:
    import argparse
    import time
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("kol_id")
    ap.add_argument("message")
    ap.add_argument("--mode", choices=list(MODES), default=None)
    ap.add_argument("--say", action="store_true")
    ap.add_argument("-o", "--out", default=None)
    args = ap.parse_args()

    t = time.perf_counter()
    text, mode = respond(args.kol_id, args.message, args.mode)
    print(f"[{MODES[mode]['label']}]  {time.perf_counter() - t:.1f}s\n")
    print(text)
    if args.say:
        dst = Path(args.out or (REPO / "renders" / "livestream" / f"{mode}.wav"))
        t = time.perf_counter()
        perform(args.kol_id, text, mode, dst)
        print(f"\n  spoken in {time.perf_counter() - t:.1f}s -> {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
