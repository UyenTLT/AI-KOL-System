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
PACE = 1.08


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
    "- Ask what actually happened. Which part went wrong, who said what, how long it went on. "
    "Curiosity about the detail is what shows you are listening.\n"
    "- Take a side. If someone treated them badly, say so. Neutrality reads as not caring.\n"
    "- Banned, because they fit every problem and therefore answer none: 'take a walk', 'treat "
    "yourself', 'you've got this', 'hang in there', 'try not to worry', 'everything will be "
    "fine', 'tomorrow is a new day'. If you find yourself reaching for one, ask a question "
    "about what happened instead.\n"
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
    "- Turn it back to them when you actually want to know something specific — 'which one did "
    "you try?', 'wait, how did that go?'. A generic 'what about you?' bolted onto the end is the "
    "opposite of interest.\n"
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


def strip_tics(reply: str, *, first_message: bool) -> tuple[str, list[str]]:
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
    out = " ".join(sents).strip() or out

    return out or reply.strip(), removed


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


def classify(message: str) -> str:
    """Pick the register for one incoming message.

    Song is tested first and deliberately: "sing me something, I feel awful tonight" is a song
    request that happens to mention a feeling, and answering it as a heart-to-heart would ignore
    what was actually asked for.
    """
    text = message or ""
    if _SONG_RE.search(text):
        return "song"
    if _HEART_RE.search(text):
        return "heart"
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


def perform(kol_id: str, text: str, mode: str, out: Path, *, speed: float = 1.0) -> Path:
    """Render what she says in the register for that mode."""
    from voice_studio import synthesize
    out.parent.mkdir(parents=True, exist_ok=True)
    return synthesize(kol_id, text, out=out, speed=speed * PACE,
                      instruct=MODES.get(mode, {}).get("instruct"))


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
