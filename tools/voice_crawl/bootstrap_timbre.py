#!/usr/bin/env python3
"""Generate a synthetic bootstrap voice corpus, then lock it with GPT-SoVITS.

This is the no-real-person path from CUDA_SETUP.md section I ("Original identities
only -- never clone a real person's face or voice without permission"): synthesize
20-30 min of speech in one consistent synthetic timbre, fine-tune GPT-SoVITS on it,
and the KOL then owns a voice that never belonged to anybody.

Because the text is known up front there is no ASR step -- the transcript is exact,
which makes this corpus strictly cleaner than anything crawled. Clips still run
through the same QC gate as `crawl.py` so the dataset format is identical.

Backends
--------
  edge   (default) Microsoft Edge neural voices. No GPU, fast, very natural, wide
         ZH + EN selection. Review Microsoft's terms for your use case.
  piper  Fully local, MIT-licensed, permissive for any downstream use. Flatter
         prosody -- acceptable here since GPT-SoVITS re-learns the timbre anyway.

Usage
-----
    python tools/voice_crawl/bootstrap_timbre.py <kol_id> --list-voices
    python tools/voice_crawl/bootstrap_timbre.py <kol_id> --voice en-US-AvaNeural --minutes 30
    python tools/voice_crawl/bootstrap_timbre.py <kol_id> --voice zh-CN-XiaoxiaoNeural \
        --lang zh --text-file my_corpus.txt
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ffmpeg_util  # noqa: E402
from crawl import Clip, measure, judge, SAMPLE_RATE, LANG_TOKENS  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]

# Phonetically varied seed lines. Enough to prove the pipeline and to cover the
# main phoneme inventory; supply --text-file for the full 20-30 min corpus.
SEED_EN = [
    "The quick brown fox jumps over the lazy dog while the sun sets behind the hills.",
    "I honestly did not expect the package to arrive this early in the morning.",
    "She whispered something about the meeting, but nobody really caught the details.",
    "Could you please explain why the third option costs almost twice as much?",
    "There were seventeen thousand people waiting outside the stadium last night.",
    "Roughly ninety percent of the feedback we received was genuinely positive.",
    "Honestly, this is my favourite thing I have tried all month, no exaggeration.",
    "Wait, hold on, are you telling me it actually shipped without the charger?",
    "The texture feels light, almost weightless, and it absorbs in a few seconds.",
    "Before we start, let me quickly show you what is inside the box.",
    "It rained heavily throughout August, which ruined most of our travel plans.",
    "Thank you so much for watching, and I will see you in the next video.",
    "My brother thinks judges should never question a witness that aggressively.",
    "Six zebras vaguely wandered past the quiet farmhouse just after dawn.",
    "Please measure the width carefully, otherwise the whole shelf will be crooked.",
    "I bought this in three different shades because I could not decide.",
    "The price dropped from forty nine dollars to just twenty two this week.",
    "Everything about the finish is smooth, matte, and surprisingly durable.",
    "Do you think we should reschedule, or is Thursday still working for everyone?",
    "That was genuinely one of the strangest films I have ever sat through.",
]

SEED_ZH = [
    "今天天氣真的很好，我決定出門走走，順便買一杯咖啡。",
    "這款產品的質地非常輕盈，擦上去幾秒鐘就完全吸收了。",
    "老實說，這是我這個月用過最喜歡的一樣東西，沒有誇張。",
    "等一下，你的意思是它出貨的時候沒有附充電器嗎？",
    "大概有百分之九十的回饋都是相當正面的，我覺得很意外。",
    "開始之前，我先快速帶大家看看盒子裡面有什麼。",
    "價格從四十九塊降到二十二塊，這個折扣真的很有誠意。",
    "整體的質感很細緻，霧面的，而且意外地耐用。",
    "謝謝大家收看，我們下一支影片再見囉。",
    "你覺得要改期嗎，還是星期四大家都還可以？",
    "昨天晚上體育場外面大概聚集了一萬七千個人。",
    "請仔細量一下寬度，不然整個層架會歪掉。",
    "我一次買了三個不同的色號，因為實在選不出來。",
    "那部電影是我看過最奇怪的作品之一，真的很難形容。",
    "八月一直下大雨，把我們大部分的旅遊計畫都打亂了。",
    "她小聲說了一些關於會議的事，可是沒有人聽清楚細節。",
    "可以請你解釋一下，為什麼第三個方案貴了將近一倍嗎？",
    "我哥哥認為法官不應該那樣尖銳地質問證人。",
    "清晨剛過，六隻斑馬慢慢走過安靜的農舍。",
    "說真的，我沒想到包裹這麼早就送到了。",
]


def load_texts(args) -> list[tuple[str, str]]:
    """Return [(text, lang)] for synthesis."""
    if args.text_file:
        raw = Path(args.text_file).read_text(encoding="utf-8").splitlines()
        lines = [ln.strip() for ln in raw if ln.strip() and not ln.startswith("#")]
        # Heuristic per-line language tag so mixed corpora work.
        return [(ln, "zh" if any("一" <= c <= "鿿" for c in ln) else "en")
                for ln in lines]
    bank: list[tuple[str, str]] = []
    for lang in args.lang.split(","):
        lang = lang.strip()
        if lang == "zh":
            bank += [(t, "zh") for t in SEED_ZH]
        elif lang == "en":
            bank += [(t, "en") for t in SEED_EN]
    if not bank:
        raise SystemExit(f"no seed text for --lang {args.lang!r} (use zh, en, or zh,en)")
    return bank


# ------------------------------------------------------------------- backends

async def _edge_list_voices():
    import edge_tts
    return await edge_tts.list_voices()


async def _edge_say(text: str, voice: str, rate: str, pitch: str, out: Path):
    import edge_tts
    comm = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    await comm.save(str(out))


async def _edge_batch(items, args, tmp_dir: Path, concurrency: int) -> list[Path]:
    """Synthesize all utterances concurrently.

    Each line is an independent network round-trip, so running them one at a time
    makes a 300-line corpus take ~an hour. A bounded semaphore keeps the service
    happy while cutting that to minutes. Results stay index-aligned with `items`.
    """
    import edge_tts

    sem = asyncio.Semaphore(concurrency)
    out: list[Path | None] = [None] * len(items)
    done = 0
    total = len(items)

    async def one(i: int, text: str):
        nonlocal done
        mp3 = tmp_dir / f"seg_{i+1:05d}.mp3"
        async with sem:
            for attempt in range(3):
                try:
                    comm = edge_tts.Communicate(text, args.voice,
                                                rate=args.rate, pitch=args.pitch)
                    await comm.save(str(mp3))
                    if mp3.exists() and mp3.stat().st_size > 500:
                        out[i] = mp3
                        break
                except Exception as exc:  # noqa: BLE001 - retry, then give up on this line
                    if attempt == 2:
                        print(f"  ! line {i+1} failed ({type(exc).__name__}: {exc})")
                    else:
                        await asyncio.sleep(1.5 * (attempt + 1))
        done += 1
        if done % 25 == 0 or done == total:
            print(f"  synthesized {done}/{total}", flush=True)

    await asyncio.gather(*(one(i, t) for i, (t, _l) in enumerate(items)))
    return out


def synth_edge(items, args, tmp_dir: Path) -> list[Path]:
    try:
        import edge_tts  # noqa: F401
    except ImportError as exc:
        raise SystemExit("edge backend needs `pip install edge-tts`") from exc
    return asyncio.run(_edge_batch(items, args, tmp_dir, args.concurrency))


def synth_piper(items, args, tmp_dir: Path) -> list[Path]:
    import subprocess
    model = args.piper_model
    if not model:
        raise SystemExit("--backend piper needs --piper-model <path to .onnx>")
    out: list[Path] = []
    for i, (text, _lang) in enumerate(items, 1):
        wav = tmp_dir / f"seg_{i:05d}.wav"
        proc = subprocess.run(
            [sys.executable, "-m", "piper", "-m", model, "-f", str(wav)],
            input=text, capture_output=True, text=True, encoding="utf-8",
        )
        if proc.returncode != 0 or not wav.exists():
            print(f"  ! line {i} failed: {(proc.stderr or '').strip()[:120]}")
            out.append(None)
            continue
        out.append(wav)
        if i % 10 == 0 or i == len(items):
            print(f"  synthesized {i}/{len(items)}")
    return out


# --------------------------------------------------------------------- driver

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Synthesize a bootstrap voice corpus for GPT-SoVITS fine-tuning.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("kol_id")
    ap.add_argument("--backend", default="edge", choices=["edge", "piper"])
    ap.add_argument("--voice", default="en-US-AvaNeural", help="backend voice id")
    ap.add_argument("--piper-model", help="path to a piper .onnx voice model")
    ap.add_argument("--lang", default="en", help="seed-bank languages, e.g. 'zh,en'")
    ap.add_argument("--text-file", help="own corpus, one utterance per line")
    ap.add_argument("--minutes", type=float, default=0.0,
                    help="stop once this many accepted minutes exist (0 = use all text)")
    ap.add_argument("--repeat", type=int, default=1,
                    help="cycle the seed bank N times (use --text-file for real volume)")
    ap.add_argument("--concurrency", type=int, default=8,
                    help="parallel edge-tts requests (lower it if the service throttles)")
    ap.add_argument("--rate", default="+0%", help="edge speaking rate, e.g. '-5%%'")
    ap.add_argument("--pitch", default="+0Hz", help="edge pitch, e.g. '+10Hz'")
    ap.add_argument("--list-voices", action="store_true", help="print available voices and exit")
    # QC thresholds (same gate as crawl.py)
    ap.add_argument("--min-sec", type=float, default=1.5)
    ap.add_argument("--max-sec", type=float, default=14.0)
    ap.add_argument("--min-snr", type=float, default=12.0)
    ap.add_argument("--min-rms-dbfs", type=float, default=-38.0)
    ap.add_argument("--max-silence", type=float, default=0.55)
    ap.add_argument("--min-conf", type=float, default=0.0)  # text is exact, no ASR
    args = ap.parse_args()

    if args.list_voices:
        if args.backend != "edge":
            raise SystemExit("--list-voices is only supported for the edge backend")
        voices = asyncio.run(_edge_list_voices())
        for v in voices:
            if v["Locale"].startswith(("en-", "zh-")):
                print(f'{v["ShortName"]:32s} {v["Gender"]:7s} {v["Locale"]}')
        return 0

    voice_dir = ROOT / "kols" / args.kol_id / "voice"
    dataset = voice_dir / "dataset"
    tmp_dir = voice_dir / "work" / "bootstrap"
    dataset.mkdir(parents=True, exist_ok=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    items = load_texts(args) * max(args.repeat, 1)
    print(f"[bootstrap] {len(items)} utterances via {args.backend} voice {args.voice!r}")

    synth = {"edge": synth_edge, "piper": synth_piper}[args.backend]
    produced = synth(items, args, tmp_dir)

    print("[qc] measuring + writing dataset")
    clips: list[Clip] = []
    accepted_sec = 0.0
    for i, (src, (text, lang)) in enumerate(zip(produced, items), 1):
        if src is None:
            continue
        wav32 = tmp_dir / f"seg_{i:05d}_32k.wav"
        try:
            ffmpeg_util.to_mono_wav(src, wav32, SAMPLE_RATE, loudnorm=True)
        except RuntimeError as exc:
            print(f"  ! decode failed for line {i}: {exc}")
            continue
        audio, sr = sf.read(str(wav32), dtype="float32", always_2d=False)
        if audio.ndim > 1:
            audio = audio.mean(axis=1)

        clip = Clip(index=i, source=f"{args.backend}:{args.voice}", start=0.0,
                    end=audio.size / sr, text=text, lang=LANG_TOKENS.get(lang, "EN"),
                    asr_conf=1.0, duration=audio.size / sr)
        clip.__dict__.update(measure(audio, sr))
        clip.reasons = judge(clip, args)
        clip.accepted = not clip.reasons
        if clip.accepted:
            out = dataset / f"{args.kol_id}_bs_{i:05d}.wav"
            sf.write(str(out), audio, sr, subtype="PCM_16")
            clip.path = str(out)
            accepted_sec += clip.duration
        clips.append(clip)
        if args.minutes and accepted_sec >= args.minutes * 60:
            print(f"  reached --minutes {args.minutes}, stopping")
            break

    accepted = [c for c in clips if c.accepted]
    list_path = dataset / f"{args.kol_id}.list"
    rows = [f"{c.path}|{args.kol_id}|{c.lang}|{c.text}" for c in accepted]
    with open(list_path, "a" if list_path.exists() else "w", encoding="utf-8") as fh:
        fh.write("\n".join(rows) + ("\n" if rows else ""))

    # A reference clip is required at inference: pick the longest accepted clip
    # inside GPT-SoVITS' comfortable 3-10 s prompt window.
    ref_pool = [c for c in accepted if 3.0 <= c.duration <= 10.0] or accepted
    if ref_pool:
        best = max(ref_pool, key=lambda c: c.asr_conf * min(c.duration, 10.0))
        ref_wav = voice_dir / "ref.wav"
        audio, sr = sf.read(best.path, dtype="float32")
        sf.write(str(ref_wav), audio, sr, subtype="PCM_16")
        (voice_dir / "ref.txt").write_text(best.text, encoding="utf-8")
        print(f"\nreference -> {ref_wav} ({best.duration:.1f}s)")
        print(f"ref text  -> {best.text}")

    (dataset / "bootstrap_manifest.json").write_text(
        json.dumps({"voice": args.voice, "backend": args.backend,
                    "accepted": len(accepted), "candidates": len(clips),
                    "accepted_minutes": round(accepted_sec / 60, 2)},
                   ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{'='*64}")
    print(f"accepted {len(accepted)}/{len(clips)} clips = {accepted_sec/60:.1f} min")
    print(f"list -> {list_path}")
    if accepted_sec < 5 * 60:
        print("\nNOTE: only a seed corpus. For a real fine-tune supply --text-file with "
              "enough lines to reach 20-30 min (roughly 300-400 utterances).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
