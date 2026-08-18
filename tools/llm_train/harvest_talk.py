#!/usr/bin/env python3
"""Harvest real sit-down talking videos, and turn them into a target we can measure against.

The complaint this exists to answer is "she sounds stiff". That is not directly measurable, so
this borrows the approach `tools/voice_eval` already took for the voice: find the proxies that
actually differ between our output and the real thing, and make them numbers.

The genre matters. What is wanted is the register of somebody sitting down and talking —
a get-ready-with-me, a story time, a heart-to-heart, an unscripted live chat. Not a scripted
review and not an interview, because both of those are *performed at* an audience and the
whole gap we are chasing is the difference between performing and talking.

Three things come out, and they are deliberately separate because their risk is not the same:

    corpus     every utterance, with its source. Raw material.
    rubric     the measured shape of real talk — length, how often a concrete detail appears,
               how often somebody has an opinion, how often they hand the turn back. Numbers,
               no text. Safe to use anywhere, and the most useful output here.
    seeds      the questions and prompts the speaker responds to, where the source has them.

On what to train on. The rubric is a measurement of public speech and carries nothing of
anybody's expression; using it to score our own output is the reason this script exists. The
corpus is a different question: a named creator's words are theirs, and training a commercial
persona directly on them is the same category of exposure as cloning their voice, which this
project already declines to do without consent (see docs/DECISION-lipsync-licensing.md for how
that judgement has been made elsewhere). So the corpus is written to disk for analysis and for
few-shot *reference* during generation, and the decision to go further is left explicit rather
than made silently by a default flag.

    # collect (subtitles if the video has them, ASR if not)
    python tools/llm_train/harvest_talk.py fetch --url <URL> --url <URL> --tag storytime
    python tools/llm_train/harvest_talk.py fetch --urls-from urls.txt

    # what does real talk look like, in numbers
    python tools/llm_train/harvest_talk.py measure datasets/style/storytime.jsonl

    # how far is she from it, right now
    python tools/llm_train/harvest_talk.py compare sofia-vargas --against datasets/style/storytime.jsonl

Subtitle fetching and ASR need network and yt-dlp; `measure` and `compare` are offline and are
what the rest of the pipeline actually consumes.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "datasets" / "style"

# ---------------------------------------------------------------- fetching

def _subtitle_cues(path: Path) -> list[dict]:
    """Parse a subtitle file into {start, text} cues. Handles json3 and vtt.

    json3 is preferred and requested first: YouTube's automatic vtt captions are a rolling
    window, so consecutive cues repeat most of their text and a naive concatenation triples
    the corpus. json3 carries each word once with its own timing.
    """
    raw = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix == ".json3" or raw.lstrip().startswith("{"):
        data = json.loads(raw)
        cues = []
        for ev in data.get("events") or []:
            segs = ev.get("segs") or []
            text = "".join(s.get("utf8", "") for s in segs).strip()
            if text and text != "\n":
                cues.append({"start": (ev.get("tStartMs") or 0) / 1000.0, "text": text})
        return cues

    # vtt fallback. Deduplicate against the previous cue: the rolling window means cue N+1
    # usually *starts with* all of cue N, and keeping both would count every word twice.
    cues, cur_start, buf = [], None, []
    for line in raw.splitlines():
        line = line.strip()
        m = re.match(r"(\d+):(\d+):(\d+)[.,](\d+)\s+-->", line)
        if m:
            if buf and cur_start is not None:
                cues.append({"start": cur_start, "text": " ".join(buf)})
            h, mi, s, ms = (int(x) for x in m.groups())
            cur_start, buf = h * 3600 + mi * 60 + s + ms / 1000.0, []
            continue
        if not line or line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")):
            continue
        buf.append(re.sub(r"<[^>]+>", "", line))
    if buf and cur_start is not None:
        cues.append({"start": cur_start, "text": " ".join(buf)})

    out = []
    for c in cues:
        t = c["text"].strip()
        if out and t.startswith(out[-1]["text"]):    # rolling window: keep the longer one
            out[-1] = {"start": out[-1]["start"], "text": t}
        elif t:
            out.append({"start": c["start"], "text": t})
    return out


def search(query: str, limit: int = 10, *, min_secs: int = 240, max_secs: int = 3600) -> list[str]:
    """Resolve a genre query to video URLs, using yt-dlp's own search.

    A hand-pasted list of links is not reproducible and quietly encodes whoever pasted it. A
    query is a statement of what the corpus is meant to be, it can be re-run when the corpus
    needs refreshing, and it goes in the commit message.

    Duration is filtered rather than trusted: under four minutes is a clip or a short and has no
    conversational shape to measure, and over an hour is usually a stream VOD whose captions
    take longer to fetch than they are worth here.
    """
    import yt_dlp

    opts = {"quiet": True, "no_warnings": True, "extract_flat": True, "skip_download": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        res = ydl.extract_info(f"ytsearch{limit * 3}:{query}", download=False)
    out = []
    for e in (res.get("entries") or []):
        dur = e.get("duration") or 0
        if not (min_secs <= dur <= max_secs):
            continue
        out.append(e.get("url") or f"https://www.youtube.com/watch?v={e['id']}")
        if len(out) >= limit:
            break
    return out


def fetch_one(url: str, *, asr_fallback: bool = True, whisper_model: str = "base.en") -> dict:
    """One video -> {title, id, cues}. Subtitles when they exist, ASR when they do not."""
    import yt_dlp

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        opts = {
            "skip_download": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": ["en", "en-US", "en-orig"],
            "subtitlesformat": "json3/vtt/best",
            "outtmpl": str(td / "%(id)s.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
        subs = sorted(td.glob("*.json3")) + sorted(td.glob("*.vtt"))
        if subs:
            return {"url": url, "id": info.get("id"), "title": info.get("title"),
                    "channel": info.get("uploader"), "source": "subtitles",
                    "cues": _subtitle_cues(subs[0])}

    if not asr_fallback:
        return {"url": url, "id": info.get("id"), "title": info.get("title"),
                "channel": info.get("uploader"), "source": "none", "cues": []}

    # No captions. Pull the audio and transcribe it — the same faster-whisper the voice
    # crawler uses. Forced onto CPU int8 because the GPU is usually holding the voice and the
    # avatar, and a transcription job is not worth evicting them for.
    from faster_whisper import WhisperModel
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        opts = {"format": "bestaudio/best", "outtmpl": str(td / "%(id)s.%(ext)s"),
                "quiet": True, "no_warnings": True,
                "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "wav"}]}
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
        wavs = sorted(td.glob("*.wav"))
        if not wavs:
            raise RuntimeError(f"no audio produced for {url}")
        model = WhisperModel(whisper_model, device="cpu", compute_type="int8")
        segs, _ = model.transcribe(str(wavs[0]), language="en", vad_filter=True)
        cues = [{"start": s.start, "text": s.text.strip()} for s in segs if s.text.strip()]
    return {"url": url, "id": info.get("id"), "title": info.get("title"),
            "channel": info.get("uploader"), "source": f"asr:{whisper_model}", "cues": cues}


# ---------------------------------------------------------------- turns

_SENT_END = re.compile(r"[.!?…]$")

# Broadcast-style captions mark a change of speaker with ">>" (and a named one with ">> NAME:").
# Two people's speech merged into one measured turn is not one person talking, and the whole
# point of the measurement is the shape of one person talking. Seen in the first harvest: a
# turn reading ">> Always. This is You know, you just speaking to you, I'm feeling like..." is
# two halves of an interview glued together, and it would be scored as somebody's sentence.
_SPEAKER_CHANGE = re.compile(r"\s*>>+\s*(?:[A-Z][A-Za-z .'-]{0,24}:)?\s*")


def _delivery(cues: list[dict], text: str) -> dict:
    """Where the speaker stopped, and for how long, inside one turn.

    The timing is the whole reason to read subtitles rather than a transcript, and until now it
    was being thrown away at the end of `turns()`. A caption cue carries the moment speech
    resumed, so the gap between the end of one cue and the start of the next is a real silence
    the speaker left — the thing that separates talking from reading aloud, and the thing this
    project has already measured as its largest voice defect (2.09 pauses per 10 s of synthetic
    speech against 6.79 for a human).

    Cue ends are approximated from word count at a normal speaking rate, because json3 events
    carry a start and not a duration. That biases every measurement the same way on both sides
    of the comparison, which is what matters — this is a difference, not an absolute.
    """
    pauses, span = [], 0.0
    for a, b in zip(cues, cues[1:]):
        end_a = a["start"] + len(a["text"].split()) / 2.8
        gap = b["start"] - end_a
        if gap > 0.25:
            pauses.append(gap)
    if cues:
        last = cues[-1]
        span = (last["start"] + len(last["text"].split()) / 2.8) - cues[0]["start"]
    words = len(text.split())
    return {"secs": round(max(span, 0.1), 2),
            "pauses": [round(p, 2) for p in pauses],
            "wps": round(words / max(span, 0.1), 2)}


def turns(cues: list[dict], *, gap: float = 1.2, max_words: int = 70) -> list[dict]:
    """Merge cues into utterance-sized turns, the unit a chat reply is comparable to.

    A caption cue is a display artefact — it breaks every 3 to 7 words wherever the line ran
    out of room, which has nothing to do with how the person was speaking. Measuring those
    would say real people speak in six-word sentences, which is an artefact of the format and
    not a fact about speech. Cues are therefore merged until the speaker actually stops: a
    pause longer than `gap`, or a sentence ending, or a length cap so a monologue that never
    pauses still produces comparable units.
    """
    out, buf, last_end = [], [], None

    def flush():
        if not buf:
            return
        text = re.sub(r"\s+", " ", " ".join(c["text"] for c in buf)).strip()
        if len(text.split()) >= 4:
            out.append({"text": text, **_delivery(buf, text)})
        buf.clear()

    for c in cues:
        text = re.sub(r"\s+", " ", c["text"]).strip()
        if not text:
            continue
        # A speaker change ends the current turn as surely as a pause does, and more reliably.
        if _SPEAKER_CHANGE.search(text):
            parts = _SPEAKER_CHANGE.split(text)
            if buf and parts[0].strip():
                buf.append({"start": c["start"], "text": parts[0].strip()})
            flush()
            text = " ".join(p.strip() for p in parts[1:] if p.strip())
            if not text:
                last_end = c["start"]
                continue
        if last_end is not None and c["start"] - last_end > gap:
            flush()
        buf.append({"start": c["start"], "text": text})
        # A cue carries no duration in json3 events we keep, so approximate the end from the
        # word count at a normal speaking rate.
        last_end = c["start"] + len(text.split()) / 2.8
        if sum(len(x["text"].split()) for x in buf) >= max_words and _SENT_END.search(text):
            flush()
    flush()
    return out


# ---------------------------------------------------------------- the rubric
#
# Seven measures, each chosen because it is the difference somebody would actually name if
# asked why a reply sounded like a machine. They are counted on whole turns, so they are
# directly comparable between a real speaker's utterance and one of ours.

_PROPER = re.compile(r"(?<![.!?]\s)(?<!^)\b[A-Z][a-z]{2,}\b")
_NUMBER = re.compile(r"\b\d+(?:[.,]\d+)?\b|\b(?:one|two|three|four|five|six|seven|eight|nine|"
                     r"ten|eleven|twelve|twenty|thirty|forty|fifty|hundred)\b", re.I)
_TIME = re.compile(r"\b(?:yesterday|today|tonight|this morning|last (?:night|week|month|year|"
                   r"summer)|on (?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)|"
                   r"in (?:january|february|march|april|may|june|july|august|september|october|"
                   r"november|december)|at \d|o'?clock|ago)\b", re.I)
# First person, past tense — "something happened to me", the shape a story takes.
#
# This was a fixed list of twenty verbs, and it missed the ordinary ones: "I filmed four takes",
# "I spent the whole day", "I walked out". Caught while unit-testing the dataset steering, where
# a candidate that plainly told a story scored as not telling one. The `[a-z]+ed` alternative is
# what makes it a rule about tense rather than a list somebody has to keep extending; the
# irregular verbs still need naming, because English will not let them be derived.
_PAST_I = re.compile(r"\bI (?:[a-z]+ed|was|had|went|got|did|made|saw|said|took|found|bought|"
                     r"ate|felt|thought|ran|came|left|met|woke|slept|drove|wrote|spent|kept|"
                     r"told|gave|sat|stood|read|lost|won|broke|forgot|knew|grew|sent|built|"
                     r"put|paid|held|heard|understood)\b", re.I)
_OPINION = re.compile(r"\b(?:I think|I reckon|honestly|to be honest|I love|I hate|I prefer|"
                      r"my favou?rite|the best|the worst|way better|so much better|I cannot "
                      r"stand|I would rather|personally)\b", re.I)
_SURVEY = re.compile(r"\b(?:it depends|everyone is different|there are pros and cons|"
                     r"on the one hand|both have their|whatever works for you|"
                     r"it (?:really )?varies)\b", re.I)
_FILLER = re.compile(r"\b(?:like|you know|I mean|kind of|kinda|sort of|basically|literally|"
                     r"anyway|actually|honestly)\b", re.I)
_QBACK = re.compile(r"\?\s*$")


# ---------------------------------------------------------------- delivery
#
# The second rubric, and a different question from the first. The first asks what she says; this
# asks how it comes out — where she stops, how fast she goes, and where feeling lands. It exists
# because every reply currently leaves the system with one fixed delivery instruction, so a joke
# and a condolence are spoken identically, and because this project already measured pauses as
# the largest single difference between its synthetic speech and a human recording.

# Deliberately NOT measured from captions: laughter, exclamation, and where emotion lands.
#
# Checked rather than assumed, and the check killed three metrics that had already been written.
# Across 1,624 harvested turns there is not one exclamation mark — YouTube's automatic captions
# transcribe words and punctuate flatly, so an emotional peak and a shopping list come out
# identically. Bracketed sound cues appear in 38 turns out of 1,624, which is a rounding error
# rather than a signal.
#
# A metric that reads zero because the source cannot express the thing is worse than no metric:
# it looks like an answer. Emotion and pausing are properties of the audio, so `delivery` below
# measures them from the audio, with the same instrument tools/voice_eval already uses on ours.
_TRAIL = re.compile(r"(?:\.\.\.|…)\s*$|\b(?:you know|I don'?t know|whatever)\s*[.…]*\s*$", re.I)
# A restart or repair mid-thought: "I— I think", "it was, well, fine", "I mean".
_REPAIR = re.compile(r"\bI mean\b|\bor rather\b|\bwell,? actually\b|\bsorry,? I\b"
                     r"|\b(\w+)[,—-]+\s+\1\b", re.I)


def measure_delivery(rows: list[dict]) -> dict:
    """How the talk comes out, for rows that carry timing. Text-only corpora return {}."""
    timed = [r for r in rows if isinstance(r, dict) and r.get("secs")]
    if not timed:
        return {}
    secs = sum(r["secs"] for r in timed)
    pauses = [p for r in timed for p in (r.get("pauses") or [])]
    n = len(timed)
    texts = [r["text"] for r in timed]

    def pct(rx):
        return round(100.0 * sum(1 for t in texts if rx.search(t)) / n, 1)

    return {
        "turns": n,
        "pauses_per_10s": round(10.0 * len(pauses) / secs, 2) if secs else 0.0,
        "median_pause_s": round(sorted(pauses)[len(pauses) // 2], 2) if pauses else 0.0,
        "words_per_second": round(sum(len(t.split()) for t in texts) / secs, 2) if secs else 0.0,
        "trails_off_pct": pct(_TRAIL),
        "self_repair_pct": pct(_REPAIR),
    }


DELIVERY_LABELS = {
    "pauses_per_10s": "silences left per 10 seconds of speech",
    "median_pause_s": "how long a silence lasts, median seconds",
    "words_per_second": "speaking rate, words per second",
    "trails_off_pct": "turns that trail off rather than land",
    "self_repair_pct": "turns where she restarts or corrects herself",
}


def measure(texts: list[str]) -> dict:
    """The shape of a body of talk, as seven numbers plus the sample size."""
    texts = [t for t in texts if t and t.strip()]
    n = len(texts)
    if not n:
        return {"turns": 0}

    def pct(rx) -> float:
        return 100.0 * sum(1 for t in texts if rx.search(t)) / n

    words = sorted(len(t.split()) for t in texts)
    concrete = 100.0 * sum(
        1 for t in texts if _PROPER.search(t) or _NUMBER.search(t) or _TIME.search(t)) / n
    fillers = sum(len(_FILLER.findall(t)) for t in texts)
    total_words = sum(words) or 1
    return {
        "turns": n,
        "median_words": words[n // 2],
        "concrete_detail_pct": round(concrete, 1),
        "own_experience_pct": round(pct(_PAST_I), 1),
        "opinion_pct": round(pct(_OPINION), 1),
        "hands_turn_back_pct": round(pct(_QBACK), 1),
        "balanced_survey_pct": round(pct(_SURVEY), 1),
        "filler_per_100w": round(100.0 * fillers / total_words, 1),
    }


# Which direction is better for each measure. `balanced_survey_pct` is the only one where
# lower wins: answering with a survey of options is the single most reliable tell that nobody
# is home, and it is what "she is not interesting" means in practice.
LOWER_IS_BETTER = {"balanced_survey_pct"}
LABELS = {
    "median_words": "median words per turn",
    "concrete_detail_pct": "turns with a concrete detail (name, number, time)",
    "own_experience_pct": "turns telling something that happened to her",
    "opinion_pct": "turns stating a preference or a verdict",
    "hands_turn_back_pct": "turns that hand the conversation back",
    "balanced_survey_pct": "turns answering with a survey of options  (lower is better)",
    "filler_per_100w": "filler words per 100 words",
}


def our_replies(kol_id: str, limit: int | None = None) -> list[str]:
    """Her own replies, from the training split — what she sounds like today."""
    p = REPO / "datasets" / f"{kol_id}-chat-train.jsonl"
    if not p.is_file():
        raise FileNotFoundError(f"no reply corpus at {p} — run build_dataset.py first")
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        for m in json.loads(line).get("messages", []):
            if m.get("role") == "assistant" and m.get("content"):
                out.append(m["content"])
    return out[:limit] if limit else out


def corpus_rows(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def corpus_texts(path: Path) -> list[str]:
    return [r["text"] for r in corpus_rows(path)]


def print_table(rows: list[tuple], head: tuple) -> None:
    widths = [max(len(str(r[i])) for r in [head] + rows) for i in range(len(head))]
    line = "  ".join("-" * w for w in widths)
    print("  ".join(str(h).ljust(w) for h, w in zip(head, widths)))
    print(line)
    for r in rows:
        print("  ".join(str(c).ljust(w) for c, w in zip(r, widths)))


# ---------------------------------------------------------------- commands

def cmd_fetch(args) -> int:
    urls = list(args.url or [])
    if args.urls_from:
        urls += [l.strip() for l in Path(args.urls_from).read_text(encoding="utf-8").splitlines()
                 if l.strip() and not l.strip().startswith("#")]
    for q in (args.search or []):
        found = search(q, args.per_query)
        print(f"search {q!r} -> {len(found)} videos", flush=True)
        urls += found
    urls = list(dict.fromkeys(urls))       # keep order, drop repeats across queries
    if not urls:
        print("give --url, --urls-from or --search", file=sys.stderr)
        return 2

    OUT.mkdir(parents=True, exist_ok=True)
    out_path = OUT / f"{args.tag}.jsonl"
    seen = set()
    if out_path.is_file() and not args.overwrite:
        for l in out_path.read_text(encoding="utf-8").splitlines():
            if l.strip():
                seen.add(json.loads(l)["text"])
        print(f"appending to {out_path} ({len(seen)} turns already there)")

    rows, sources = [], []
    for i, url in enumerate(urls, 1):
        print(f"[{i}/{len(urls)}] {url}", flush=True)
        try:
            v = fetch_one(url, asr_fallback=not args.no_asr, whisper_model=args.whisper)
        except Exception as exc:
            print(f"      failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            continue
        tt = turns(v["cues"], gap=args.gap, max_words=args.max_words)
        fresh = [t for t in tt if t["text"] not in seen]
        seen.update(t["text"] for t in fresh)
        for t in fresh:
            rows.append({**t, "video_id": v["id"], "channel": v["channel"],
                         "title": v["title"], "source": v["source"], "tag": args.tag})
        sources.append((v["title"] or v["id"], v["source"], len(tt), len(fresh)))
        print(f"      {v['source']}: {len(v['cues'])} cues -> {len(tt)} turns "
              f"({len(fresh)} new)", flush=True)

    mode = "w" if (args.overwrite or not out_path.is_file()) else "a"
    with open(out_path, mode, encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    print()
    print_table([(t[:44], s, n, f) for t, s, n, f in sources],
                ("video", "via", "turns", "new"))
    print(f"\nwrote {len(rows)} turns -> {out_path}")
    print(f"next: python tools/llm_train/harvest_talk.py measure {out_path.as_posix()}")
    return 0


# Both sides are cut into windows of the same length, so a pause rate from a three-minute video
# and one from a twelve-second reply are the same measurement rather than two different ones.
WINDOW_S = 10.0
MAX_AUDIO_S = 240.0


def audio_delivery(paths: list[Path]) -> dict:
    """Pausing and pitch movement measured from real audio, per 4-7.5 s chunk.

    Uses tools/voice_eval/prosody.py rather than a second implementation, and not for tidiness:
    that module high-passes at 80 Hz and floors the pitch tracker at 110 Hz because an earlier
    hand-rolled version tracked a female voice an octave low and produced a fabricated figure
    that reached a written conclusion. Reusing it means the number for a stranger's speech and
    the number for ours were produced by the same instrument, which is the only way the
    comparison means anything.
    """
    sys.path.insert(0, str(REPO / "tools" / "voice_eval"))
    import prosody

    # Fixed windows, not prosody.chunk(). That helper splits on silence and keeps only segments
    # of four seconds or more, which is right for building a long corpus and wrong here: our
    # rendered replies are 10-14 s of speech broken by exactly the pauses being measured, so
    # every segment came out under the threshold and the whole side scored zero chunks. Silence
    # is the signal, so it must not be what decides where the window ends.
    rows = []
    win = int(WINDOW_S * prosody.SR)
    for p in paths:
        try:
            y = prosody.load_any(str(p))
        except Exception as exc:
            print(f"  skipped {p.name}: {type(exc).__name__}: {exc}", file=sys.stderr)
            continue
        y = y[: int(MAX_AUDIO_S * prosody.SR)]
        for i in range(0, max(len(y) - win // 2, 1), win):
            seg = y[i:i + win]
            if len(seg) < 4 * prosody.SR:
                continue
            f = prosody.feats(seg)
            if f and f.get("dur", 0) > 1.0:
                rows.append(f)
    if not rows:
        return {}

    def med(key):
        v = sorted(r[key] for r in rows if r.get(key) is not None)
        return round(v[len(v) // 2], 2) if v else 0.0

    return {"chunks": len(rows), "pauses_per_10s": med("pause_rate"),
            "pitch_range_st": med("f0_range_st"), "median_pitch_hz": med("f0_med"),
            "loudness_sd_db": med("db_sd")}


AUDIO_LABELS = {
    "pauses_per_10s": "pauses per 10 s  — where she stops",
    "pitch_range_st": "pitch range, semitones  — how much the voice moves",
    "median_pitch_hz": "median pitch, Hz",
    "loudness_sd_db": "loudness variation, dB  — where the emphasis lands",
}


def cmd_delivery(args) -> int:
    """Download audio for a sample of the corpus and measure how it is actually spoken."""
    import yt_dlp

    ids = []
    if args.corpus:
        for r in corpus_rows(Path(args.corpus)):
            if r.get("video_id") and r["video_id"] not in ids:
                ids.append(r["video_id"])
    ids = ids[:args.videos]
    if not ids and not args.audio:
        print("give --corpus or --audio", file=sys.stderr)
        return 2

    paths = [Path(a) for a in (args.audio or [])]
    tmp = None
    if ids:
        tmp = tempfile.TemporaryDirectory()
        td = Path(tmp.name)
        print(f"downloading audio for {len(ids)} videos (a sample, not the corpus)", flush=True)
        for vid in ids:
            # The whole audio track, then trimmed after loading. Clipping during download with
            # `download_ranges` + `force_keyframes_at_cuts` failed on half the videos with an
            # ffmpeg crash, and an audio-only track for a twenty-minute video is a few MB — the
            # clever version cost more than it saved.
            opts = {"format": "bestaudio/best", "outtmpl": str(td / "%(id)s.%(ext)s"),
                    "quiet": True, "no_warnings": True,
                    "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "wav"}]}
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    ydl.download([f"https://www.youtube.com/watch?v={vid}"])
            except Exception as exc:
                print(f"  {vid}: {type(exc).__name__}", file=sys.stderr)
        paths += sorted(td.glob("*.wav"))

    real = audio_delivery(paths)
    if tmp:
        tmp.cleanup()
    if not real:
        print("no audio could be measured", file=sys.stderr)
        return 1

    ours = {}
    if args.ours:
        clips = sorted(Path(args.ours).glob("*.wav"))[: args.videos * 4]
        ours = audio_delivery(clips)

    head = ("delivery", "real talk") + (("hers",) if ours else ())
    rows = [(AUDIO_LABELS[k], real[k]) + ((ours.get(k, "-"),) if ours else ())
            for k in AUDIO_LABELS]
    print(f"\nreal: {real['chunks']} chunks"
          + (f"    hers: {ours['chunks']} chunks" if ours else "") + "\n")
    print_table(rows, head)
    return 0


def cmd_measure(args) -> int:
    texts = corpus_texts(Path(args.corpus))
    m = measure(texts)
    if not m["turns"]:
        print("empty corpus", file=sys.stderr)
        return 1
    print(f"{Path(args.corpus).name} — {m['turns']} turns\n")
    print_table([(LABELS[k], m[k]) for k in LABELS], ("measure", "value"))
    d = measure_delivery(corpus_rows(Path(args.corpus)))
    if d:
        print()
        print_table([(DELIVERY_LABELS[k], d[k]) for k in DELIVERY_LABELS],
                    ("delivery", "value"))
    return 0


def cmd_compare(args) -> int:
    ours = measure(our_replies(args.kol_id))
    if not args.against:
        print(f"{args.kol_id} — {ours['turns']} replies (no target given)\n")
        print_table([(LABELS[k], ours[k]) for k in LABELS], ("measure", "hers"))
        return 0

    target = measure(corpus_texts(Path(args.against)))
    rows = []
    for k in LABELS:
        h, t = ours[k], target[k]
        if k in LOWER_IS_BETTER:
            verdict = "ok" if h <= t else f"{h - t:+.1f} too much"
        else:
            gap = h - t
            verdict = "ok" if abs(gap) < max(1.0, 0.15 * t) else f"{gap:+.1f}"
        rows.append((LABELS[k], h, t, verdict))
    print(f"{args.kol_id}: {ours['turns']} replies    target: {target['turns']} real turns "
          f"from {Path(args.against).name}\n")
    print_table(rows, ("measure", "hers", "real talk", "gap"))
    print("\nThe gap column is the brief: it says what to ask for more of, in a form that can "
          "be checked again after training rather than argued about.")
    return 0


def main() -> int:
    # Video titles carry emoji, and this console is cp950. The corpus had already been written
    # when the summary table raised UnicodeEncodeError on a teacup — a completed harvest that
    # reported itself as a crash. Replace what the console cannot draw rather than lose the run.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("fetch", help="download subtitles (or transcribe) into a style corpus")
    f.add_argument("--url", action="append", help="repeatable")
    f.add_argument("--urls-from", help="a file with one URL per line, # for comments")
    f.add_argument("--search", action="append",
                   help="a genre query resolved through YouTube search; repeatable")
    f.add_argument("--per-query", type=int, default=8, help="videos to keep per query")
    f.add_argument("--tag", default="talk", help="corpus name under datasets/style/")
    f.add_argument("--gap", type=float, default=1.2, help="pause that ends a turn, seconds")
    f.add_argument("--max-words", type=int, default=70)
    f.add_argument("--whisper", default="base.en", help="ASR model when there are no subtitles")
    f.add_argument("--no-asr", action="store_true", help="skip videos without subtitles")
    f.add_argument("--overwrite", action="store_true")
    f.set_defaults(func=cmd_fetch)

    m = sub.add_parser("measure", help="the seven numbers for one corpus")
    m.add_argument("corpus")
    m.set_defaults(func=cmd_measure)

    d = sub.add_parser("delivery", help="how it is spoken — pauses and pitch, from real audio")
    d.add_argument("--corpus", help="take a video sample from this corpus")
    d.add_argument("--audio", action="append", help="a local wav to measure instead; repeatable")
    d.add_argument("--ours", help="a directory of our rendered wavs to compare against")
    d.add_argument("--videos", type=int, default=6)
    d.add_argument("--secs", type=int, default=180, help="seconds of audio taken per video")
    d.set_defaults(func=cmd_delivery)

    c = sub.add_parser("compare", help="her replies against a real-talk corpus")
    c.add_argument("kol_id")
    c.add_argument("--against", help="a corpus from `fetch`; omit to just measure her")
    c.set_defaults(func=cmd_compare)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
