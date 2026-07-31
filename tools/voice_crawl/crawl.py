#!/usr/bin/env python3
"""Crawl speech from podcasts/videos/local files into a GPT-SoVITS training set.

    fetch -> normalize -> [separate vocals] -> ASR w/ word timestamps
          -> re-chunk on sentence + pause boundaries -> per-clip QC -> .list

Why this exists: the older scripts cut audio into *fixed-duration* chunks, which
slices words in half and keeps music and every other speaker in the recording.
GPT-SoVITS trains on `wav|speaker|LANG|text` rows, so every clip must be a clean,
whole utterance from one voice with a correct transcript. This does that.

The core path needs no torch -- faster-whisper (CTranslate2) handles both VAD and
ASR. Vocal separation (`--separate`, demucs) and diarization are optional add-ons
for messy multi-speaker sources.

Usage
-----
    python tools/voice_crawl/crawl.py <kol_id> --url <URL> [--url ...]
    python tools/voice_crawl/crawl.py <kol_id> --file path/to/audio.wav
    python tools/voice_crawl/crawl.py <kol_id> --file corpus/ --lang en --target-minutes 30

Outputs (under kols/<kol_id>/voice/):
    raw/            downloaded / source audio, untouched
    work/           normalized 32k mono WAVs (intermediate)
    dataset/*.wav   accepted training clips
    dataset/<kol_id>.list   GPT-SoVITS manifest
    dataset/manifest.json   full QC report incl. every rejected clip + reason
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ffmpeg_util  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SAMPLE_RATE = 32000

# A frame this far below the clip's speech level counts as silence (-30 dB).
SILENCE_FLOOR_RATIO = 10 ** (-30 / 20)

# whisper language code -> GPT-SoVITS .list language token
LANG_TOKENS = {"zh": "ZH", "en": "EN", "ja": "JA", "ko": "KO", "yue": "YUE"}

AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".opus", ".aac", ".wma",
              ".mp4", ".mkv", ".webm", ".mov"}

# A chunk should end here if it is already long enough.
SENTENCE_END = re.compile(r"[.!?。！？…]['\"”’)]?\s*$")
CLAUSE_END = re.compile(r"[,;:、，；：]['\"”’)]?\s*$")
HAS_CONTENT = re.compile(r"[0-9A-Za-z一-鿿぀-ヿ가-힯]")


@dataclass
class Clip:
    """One candidate training clip and everything QC decided about it."""
    index: int
    source: str
    start: float
    end: float
    text: str
    lang: str
    duration: float = 0.0
    rms_dbfs: float = 0.0
    peak: float = 0.0
    clip_ratio: float = 0.0
    snr_db: float = 0.0
    silence_ratio: float = 0.0
    asr_conf: float = 0.0
    path: str = ""
    accepted: bool = False
    reasons: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- fetch

def slugify(text: str, limit: int = 80) -> str:
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE).strip()
    text = re.sub(r"[\s_-]+", "-", text)
    return (text[:limit] or "audio").strip("-")


def fetch_url(url: str, dest_dir: Path) -> list[Path]:
    """Download best-available audio for `url`. Returns the written file paths."""
    try:
        import yt_dlp
    except ImportError as exc:
        raise ImportError("yt-dlp is required for --url. `pip install yt-dlp`") from exc

    dest_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    def _hook(status):
        if status["status"] == "finished":
            written.append(Path(status["filename"]))

    opts = {
        "format": "bestaudio/best",
        "outtmpl": str(dest_dir / "%(title).80s [%(id)s].%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "ffmpeg_location": str(Path(ffmpeg_util.resolve("ffmpeg")).parent),
        "progress_hooks": [_hook],
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": "m4a", "preferredquality": "192"}
        ],
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)

    # The postprocessor renames the file, so prefer its reported path over the hook's.
    finals: list[Path] = []
    for entry in (info.get("requested_downloads") or []):
        p = Path(entry.get("filepath") or entry.get("_filename", ""))
        if p.is_file():
            finals.append(p)
    if not finals:
        finals = [p for p in written if p.is_file()]
    if not finals:
        raise RuntimeError(f"yt-dlp reported success but produced no file for {url}")
    return finals


def collect_local(paths: list[str]) -> list[Path]:
    out: list[Path] = []
    for raw in paths:
        p = Path(raw).expanduser()
        if p.is_dir():
            out += sorted(q for q in p.rglob("*") if q.suffix.lower() in AUDIO_EXTS)
        elif p.is_file():
            out.append(p)
        else:
            raise FileNotFoundError(f"--file path does not exist: {p}")
    return out


# ------------------------------------------------------------------ vocal separation

def separate_vocals(src: Path, work_dir: Path) -> Path:
    """Strip music/effects with demucs, returning the vocals stem.

    Optional: only worth running on sources with background music. Falls back to
    the input untouched (with a warning) if demucs is unavailable.
    """
    import subprocess

    out_dir = work_dir / "demucs"
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "demucs", "--two-stems", "vocals",
           "-o", str(out_dir), str(src)]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()[-6:]
        print(f"  ! demucs failed, using un-separated audio:\n    " + "\n    ".join(tail))
        return src
    found = sorted(out_dir.rglob("vocals.wav"))
    if not found:
        print("  ! demucs produced no vocals stem, using un-separated audio")
        return src
    return found[-1]


# --------------------------------------------------------------------------- ASR

def load_asr(model_size: str, device: str):
    """Load faster-whisper, degrading cuda -> cpu rather than crashing.

    CTranslate2 needs cuDNN 9 alongside CUDA 12; that is frequently missing on a
    fresh Windows box even when the driver is fine.
    """
    from faster_whisper import WhisperModel

    order = [("cuda", "float16"), ("cpu", "int8")] if device in ("auto", "cuda") else [("cpu", "int8")]
    if device == "cpu":
        order = [("cpu", "int8")]
    last: Exception | None = None
    for dev, compute in order:
        try:
            model = WhisperModel(model_size, device=dev, compute_type=compute)
            print(f"  ASR: {model_size} on {dev} ({compute})")
            return model
        except Exception as exc:  # noqa: BLE001 - want the fallback, report at the end
            last = exc
            if dev == "cuda":
                print(f"  ! CUDA unavailable for faster-whisper ({type(exc).__name__}), falling back to CPU")
    raise RuntimeError(f"could not load faster-whisper model {model_size!r}: {last}")


def transcribe_words(model, audio_path: Path, lang: str | None):
    """Run ASR and return (flat word list, detected language)."""
    segments, info = model.transcribe(
        str(audio_path),
        language=lang,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 300, "speech_pad_ms": 100},
        word_timestamps=True,
        condition_on_previous_text=False,
    )
    words = []
    for seg in segments:
        if seg.no_speech_prob is not None and seg.no_speech_prob > 0.6:
            continue
        for w in (seg.words or []):
            words.append({"start": w.start, "end": w.end, "text": w.word,
                          "prob": float(w.probability or 0.0)})
    return words, (info.language or lang or "en")


def chunk_words(words: list[dict], min_sec: float, max_sec: float, pause_gap: float) -> list[dict]:
    """Group words into ~min..max second utterances, breaking at natural boundaries.

    Preference order for a break, once the chunk is at least `min_sec` long:
    sentence punctuation > a silence gap > clause punctuation. A chunk is forced
    to close at `max_sec` regardless.
    """
    chunks: list[dict] = []
    buf: list[dict] = []

    def flush():
        if not buf:
            return
        text = "".join(w["text"] for w in buf).strip()
        if not text:
            buf.clear()
            return
        chunks.append({
            "start": buf[0]["start"],
            "end": buf[-1]["end"],
            "text": text,
            "conf": float(np.mean([w["prob"] for w in buf])) if buf else 0.0,
        })
        buf.clear()

    for i, w in enumerate(words):
        # Prefer to break on a long silence -- but only once the chunk is usable,
        # otherwise a pause early in an utterance would emit a sub-min_sec sliver.
        # Chunks that do span a silence get caught later by the silence_ratio gate.
        if buf and (w["start"] - buf[-1]["end"]) > pause_gap and (buf[-1]["end"] - buf[0]["start"]) >= min_sec:
            flush()
        buf.append(w)
        dur = buf[-1]["end"] - buf[0]["start"]
        if dur >= max_sec:
            flush()
            continue
        if dur < min_sec:
            continue
        nxt_gap = (words[i + 1]["start"] - w["end"]) if i + 1 < len(words) else math.inf
        if SENTENCE_END.search(w["text"]) or nxt_gap > pause_gap or CLAUSE_END.search(w["text"]):
            flush()
    flush()
    return [c for c in chunks if (c["end"] - c["start"]) >= min_sec]


# ---------------------------------------------------------------------------- QC

def measure(audio: np.ndarray, sr: int) -> dict:
    """Per-clip signal metrics used to accept or reject it."""
    if audio.size == 0:
        return {"rms_dbfs": -120.0, "peak": 0.0, "clip_ratio": 0.0,
                "snr_db": 0.0, "silence_ratio": 1.0}

    peak = float(np.max(np.abs(audio)))
    clip_ratio = float(np.mean(np.abs(audio) >= 0.99))
    rms = float(np.sqrt(np.mean(audio ** 2)))
    rms_dbfs = 20 * math.log10(max(rms, 1e-9))

    # Frame energies -> noise floor vs speech level. 25 ms frames, 10 ms hop.
    frame, hop = int(0.025 * sr), int(0.010 * sr)
    if audio.size < frame:
        frames = audio[None, :]
    else:
        n = 1 + (audio.size - frame) // hop
        idx = np.arange(frame)[None, :] + hop * np.arange(n)[:, None]
        frames = audio[idx]
    fe = np.sqrt(np.mean(frames ** 2, axis=1)) + 1e-9
    noise = float(np.percentile(fe, 10))
    speech = float(np.percentile(fe, 95))
    snr_db = 20 * math.log10(speech / max(noise, 1e-9))
    # Silence must be judged against the clip's own SPEECH level, not its noise
    # floor: speech frame energy spans a wide range, so a noise-relative
    # threshold marks ordinary voiced audio as silent (measured: it scored 1.00
    # on continuous full-level speech). 30 dB below the 95th-percentile speech
    # level cleanly separates real dead air from quiet consonants.
    silence_ratio = float(np.mean(fe < speech * SILENCE_FLOOR_RATIO))

    return {"rms_dbfs": rms_dbfs, "peak": peak, "clip_ratio": clip_ratio,
            "snr_db": snr_db, "silence_ratio": silence_ratio}


def judge(clip: Clip, args) -> list[str]:
    """Return the list of QC failures for a clip (empty == accepted)."""
    bad: list[str] = []
    if clip.duration < args.min_sec:
        bad.append(f"too_short({clip.duration:.2f}s)")
    if clip.duration > args.max_sec + 0.5:
        bad.append(f"too_long({clip.duration:.2f}s)")
    if clip.rms_dbfs < args.min_rms_dbfs:
        bad.append(f"too_quiet({clip.rms_dbfs:.1f}dBFS)")
    if clip.clip_ratio > 0.005:
        bad.append(f"clipped({clip.clip_ratio*100:.2f}%)")
    if clip.snr_db < args.min_snr:
        bad.append(f"low_snr({clip.snr_db:.1f}dB)")
    if clip.silence_ratio > args.max_silence:
        bad.append(f"mostly_silence({clip.silence_ratio*100:.0f}%)")
    if clip.asr_conf < args.min_conf:
        bad.append(f"low_asr_conf({clip.asr_conf:.2f})")
    if not HAS_CONTENT.search(clip.text):
        bad.append("empty_text")
    return bad


# -------------------------------------------------------------------------- driver

def process_source(src: Path, kol: str, dirs: dict[str, Path], model, args,
                   counter: list[int]) -> list[Clip]:
    print(f"\n[source] {src.name}")
    work = dirs["work"] / slugify(src.stem)
    work.mkdir(parents=True, exist_ok=True)

    norm = work / "normalized.wav"
    print("  normalizing -> 32k mono" + (" + loudnorm" if not args.no_loudnorm else ""))
    ffmpeg_util.to_mono_wav(src, norm, SAMPLE_RATE, loudnorm=not args.no_loudnorm)

    asr_input = norm
    if args.separate:
        print("  separating vocals (demucs)")
        stem = separate_vocals(norm, work)
        if stem != norm:
            asr_input = work / "vocals_32k.wav"
            ffmpeg_util.to_mono_wav(stem, asr_input, SAMPLE_RATE, loudnorm=False)

    print("  transcribing (word timestamps + VAD)")
    words, detected = transcribe_words(model, asr_input, None if args.lang == "auto" else args.lang)
    if not words:
        print("  ! no speech found, skipping")
        return []
    lang_token = LANG_TOKENS.get(detected, "EN")
    print(f"  language: {detected} -> {lang_token}; {len(words)} words")

    groups = chunk_words(words, args.min_sec, args.max_sec, args.pause_gap)
    print(f"  {len(groups)} candidate clips")

    audio, sr = sf.read(str(asr_input), dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)

    clips: list[Clip] = []
    for g in groups:
        counter[0] += 1
        idx = counter[0]
        a, b = int(g["start"] * sr), int(g["end"] * sr)
        seg = audio[max(a, 0):min(b, audio.size)]
        clip = Clip(index=idx, source=src.name, start=g["start"], end=g["end"],
                    text=g["text"], lang=lang_token, asr_conf=g["conf"],
                    duration=seg.size / sr)
        clip.__dict__.update(measure(seg, sr))
        clip.reasons = judge(clip, args)
        clip.accepted = not clip.reasons
        if clip.accepted:
            out = dirs["dataset"] / f"{kol}_{idx:05d}.wav"
            sf.write(str(out), seg, sr, subtype="PCM_16")
            clip.path = str(out)
        clips.append(clip)
    return clips


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Crawl podcast/video/local audio into a GPT-SoVITS training set.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("kol_id", help="KOL id, e.g. sofia-vargas")
    ap.add_argument("--url", action="append", default=[], help="source URL (repeatable)")
    ap.add_argument("--file", action="append", default=[], help="local file or directory (repeatable)")
    ap.add_argument("--lang", default="auto", choices=["auto", "zh", "en", "ja", "ko", "yue"])
    ap.add_argument("--whisper-model", default="large-v3", help="faster-whisper model size")
    ap.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    ap.add_argument("--separate", action="store_true", help="strip music with demucs first")
    ap.add_argument("--no-loudnorm", action="store_true", help="skip EBU R128 loudness normalization")
    ap.add_argument("--min-sec", type=float, default=3.0)
    ap.add_argument("--max-sec", type=float, default=10.0)
    ap.add_argument("--pause-gap", type=float, default=0.35, help="silence (s) treated as a break")
    ap.add_argument("--min-snr", type=float, default=12.0, help="reject clips below this SNR (dB)")
    ap.add_argument("--min-rms-dbfs", type=float, default=-38.0)
    ap.add_argument("--max-silence", type=float, default=0.55, help="max silent-frame fraction")
    ap.add_argument("--min-conf", type=float, default=0.55, help="min mean ASR word confidence")
    ap.add_argument("--target-minutes", type=float, default=0.0,
                    help="stop after this many accepted minutes (0 = use everything)")
    ap.add_argument("--keep-existing", action="store_true",
                    help="append to the existing dataset instead of clearing it")
    args = ap.parse_args()

    if not args.url and not args.file:
        ap.error("give at least one --url or --file")

    voice = ROOT / "kols" / args.kol_id / "voice"
    dirs = {"raw": voice / "raw", "work": voice / "work", "dataset": voice / "dataset"}
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)

    if not args.keep_existing:
        for old in dirs["dataset"].glob("*.wav"):
            old.unlink()

    sources: list[Path] = []
    for url in args.url:
        print(f"[fetch] {url}")
        got = fetch_url(url, dirs["raw"])
        for g in got:
            print(f"  saved {g.name} ({g.stat().st_size/1e6:.1f} MB)")
        sources += got
    sources += collect_local(args.file)
    if not sources:
        print("No source audio resolved.", file=sys.stderr)
        return 1

    model = load_asr(args.whisper_model, args.device)

    all_clips: list[Clip] = []
    counter = [0]
    accepted_sec = 0.0
    for src in sources:
        clips = process_source(src, args.kol_id, dirs, model, args, counter)
        all_clips += clips
        accepted_sec += sum(c.duration for c in clips if c.accepted)
        ok = sum(1 for c in clips if c.accepted)
        print(f"  accepted {ok}/{len(clips)} clips ({accepted_sec/60:.1f} min total)")
        if args.target_minutes and accepted_sec >= args.target_minutes * 60:
            print(f"  reached --target-minutes {args.target_minutes}, stopping")
            break

    accepted = [c for c in all_clips if c.accepted]
    list_path = dirs["dataset"] / f"{args.kol_id}.list"
    rows = [f"{c.path}|{args.kol_id}|{c.lang}|{c.text}" for c in accepted]
    mode = "a" if args.keep_existing and list_path.exists() else "w"
    with open(list_path, mode, encoding="utf-8") as fh:
        fh.write("\n".join(rows) + ("\n" if rows else ""))

    reasons: dict[str, int] = {}
    for c in all_clips:
        for r in c.reasons:
            reasons[r.split("(")[0]] = reasons.get(r.split("(")[0], 0) + 1

    manifest = {
        "kol_id": args.kol_id,
        "sources": [s.name for s in sources],
        "settings": vars(args),
        "totals": {
            "candidates": len(all_clips),
            "accepted": len(accepted),
            "accepted_minutes": round(accepted_sec / 60, 2),
            "rejected_by_reason": dict(sorted(reasons.items(), key=lambda kv: -kv[1])),
        },
        "clips": [asdict(c) for c in all_clips],
    }
    (dirs["dataset"] / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{'='*64}")
    print(f"accepted {len(accepted)}/{len(all_clips)} clips = {accepted_sec/60:.1f} min")
    if reasons:
        print("rejected: " + ", ".join(f"{k}={v}" for k, v in
                                       sorted(reasons.items(), key=lambda kv: -kv[1])))
    print(f"list     -> {list_path}")
    print(f"manifest -> {dirs['dataset'] / 'manifest.json'}")
    if accepted_sec < 5 * 60:
        print("\nNOTE: GPT-SoVITS wants >=5 min (20-30 min is comfortable). Add more sources.")
    print("Next: load the .list in the GPT-SoVITS WebUI -> train SoVITS, then GPT.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
