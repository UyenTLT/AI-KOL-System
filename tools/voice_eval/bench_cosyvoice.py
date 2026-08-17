#!/usr/bin/env python3
"""Benchmark CosyVoice 2 against the current GPT-SoVITS voice, on the measurements that
actually motivated the evaluation.

The complaint was "it still sounds like a robot". Measured against 48 s of real human
speech, the two biggest gaps in the current voice were not timbre — median pitch already
matches within 0.4 Hz — but **phrasing** (2.09 vs 6.79 pauses per 10 s) and **delivery
variety** (0.47 vs 1.71 semitones of clip-to-clip variation). This script tests whether
CosyVoice 2 closes them.

Three conditions, so the comparison separates the engine from the reference clip:

    zs-synth    zero-shot from Sofia's existing synthetic reference
    zs-human    zero-shot from the real human clip
    instruct    same human reference, plus a natural-language delivery instruction

The equivalent GPT-SoVITS A/B failed: swapping in the human reference dropped the register
51 Hz and made the output drag, because weights fine-tuned on one speaker fight a reference
from another. CosyVoice 2 is zero-shot, so it has no fine-tuned weights to fight — which is
exactly the hypothesis being tested here.

Pitch is measured octave-safe (80 Hz high-pass, pyin floor at 110 Hz). An earlier pass
used a 70 Hz floor, the tracker locked an octave low on creaky frames, and every derived
statistic was wrong — including a "12.6x" figure that survived to a written conclusion
before it was caught.

    CosyVoice/.venv/Scripts/python.exe tools/voice_eval/bench_cosyvoice.py --out <dir>
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
COSY = REPO / "CosyVoice"
sys.path.insert(0, str(COSY))
sys.path.insert(0, str(COSY / "third_party" / "Matcha-TTS"))

# The same line for every condition, and the same one used for the GPT-SoVITS A/B, so the
# numbers are comparable across engines. Deliberately conversational: an even, declarative
# sentence hides exactly the flatness being measured.
LINE = "Okay so, I honestly did not expect this to work. But look at my skin right now. I mean, come on!"

INSTRUCT = "Speak warmly and conversationally, like talking to a close friend, with natural pauses."

HUMAN_REF_SPAN = (7.7, 14.2)   # a clean, expressive stretch of the raw clip
HUMAN_REF_TEXT = ("and paper. I want you to write down in one section all the good things "
                  "that he's done for you.")


def cut_human_ref(dst: Path) -> Path:
    raw = REPO / "kols/sofia-vargas/voice/raw/kols_sofia-vargas_raw voice.m4a"
    if not raw.is_file():
        raise SystemExit(f"missing raw human clip: {raw}")
    start, end = HUMAN_REF_SPAN
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(raw),
                    "-ss", str(start), "-to", str(end),
                    "-ar", "16000", "-ac", "1", str(dst)], check=True)
    return dst


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True, help="directory for the generated wavs")
    ap.add_argument("--model", default=str(COSY / "pretrained_models" / "CosyVoice2-0.5B"))
    ap.add_argument("--fp16", action="store_true")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    import torch
    import torchaudio
    from cosyvoice.cli.cosyvoice import CosyVoice2
    from cosyvoice.utils.file_utils import load_wav

    model_dir = Path(args.model)
    if not model_dir.is_dir():
        raise SystemExit(f"weights not found: {model_dir}\nDownload CosyVoice2-0.5B first.")

    t0 = time.perf_counter()
    cosy = CosyVoice2(str(model_dir), load_jit=False, load_trt=False, fp16=args.fp16)
    print(f"[load] model ready in {time.perf_counter()-t0:.1f} s  ·  sr={cosy.sample_rate}")

    synth_ref = REPO / "kols/sofia-vargas/voice/ref.wav"
    synth_text = ("Let me be blunt about the moisturiser: I am still undecided about it, "
                  "mainly because results took much too long.")
    human_ref = cut_human_ref(out / "ref_human_16k.wav")

    conditions = [
        ("zs-synth", "inference_zero_shot", (LINE, synth_text, load_wav(str(synth_ref), 16000))),
        ("zs-human", "inference_zero_shot", (LINE, HUMAN_REF_TEXT, load_wav(str(human_ref), 16000))),
        ("instruct", "inference_instruct2", (LINE, INSTRUCT, load_wav(str(human_ref), 16000))),
    ]

    results = []
    for name, fn_name, fn_args in conditions:
        fn = getattr(cosy, fn_name)
        started = time.perf_counter()
        chunks = [o["tts_speech"] for o in fn(*fn_args, stream=False)]
        elapsed = time.perf_counter() - started
        if not chunks:
            print(f"[{name}] produced no audio")
            continue
        wav = torch.cat(chunks, dim=1)
        path = out / f"cosy_{name}.wav"
        torchaudio.save(str(path), wav, cosy.sample_rate)
        dur = wav.shape[1] / cosy.sample_rate
        rtf = elapsed / dur if dur else float("nan")
        peak = torch.cuda.max_memory_allocated() / 1e6 if torch.cuda.is_available() else 0
        print(f"[{name}] {dur:5.2f} s audio in {elapsed:5.2f} s  ·  RTF {rtf:.2f}  ·  {path.name}")
        results.append({"name": name, "path": str(path), "dur": dur,
                        "gen_s": elapsed, "rtf": rtf, "peak_vram_mb": peak})

    print("\nGenerated:")
    for r in results:
        print(f"  {r['name']:9} {r['dur']:5.2f} s   RTF {r['rtf']:.2f}   {r['path']}")
    if torch.cuda.is_available():
        print(f"\npeak VRAM allocated: {torch.cuda.max_memory_allocated()/1e6:.0f} MB")
    print("\nNow measure prosody + intelligibility with the repo .venv "
          "(faster-whisper and the octave-safe pitch code live there).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
