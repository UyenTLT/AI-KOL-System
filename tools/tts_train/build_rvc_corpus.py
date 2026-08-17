#!/usr/bin/env python3
"""Build an RVC training corpus in a character's *current* voice.

## Why this exists rather than reusing the dataset on disk

`kols/sofia-vargas/voice/dataset/sofia-vargas.list` still lists 320 clips and the profile still
says 30.2 minutes, but the audio is gone and it would be the wrong audio anyway: every entry is
named `sofia-vargas_bs_*` — `bs` for bootstrap — and that corpus was spoken by
`edge:es-MX-DaliaNeural` to bootstrap GPT-SoVITS before she had a voice of her own. Training RVC
on it would produce a model of the bootstrap timbre, not of Sofia.

What remains of the real source is 50.33 seconds: one recording of the project owner's own
voice, of which 6.5 s is the reference clip CosyVoice clones from. RVC's own guidance is around
ten minutes. Fifty seconds is not a corpus.

So the corpus is generated from the voice she actually has now. CosyVoice renders her identity
from that 6.5 s reference; this walks the same text corpus through it and keeps the audio. The
result is a copy of a copy, and its ceiling is CosyVoice's rendition of her — worth stating
plainly. The alternative is asking the owner to record ten more minutes, which is strictly
better and needs a person; this needs nobody.

## Pitch spread is deliberate

A model trained only on level conversational speech has never seen the range singing asks for.
The delivery instruction is a measured control on this voice — same sentence, 17.50 semitones of
range on the conversational wording against 8.17 on a whispered one — so the corpus cycles
through registers instead of rendering 320 lines in one. It widens the pitch distribution the
model is fitted to, which is the distribution a sung line will land outside of otherwise.

    python tools/tts_train/build_rvc_corpus.py sofia-vargas
    python tools/tts_train/build_rvc_corpus.py sofia-vargas --limit 40      # a quick sample
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools" / "studio"))

# Cycled across the corpus. Ordinary speech dominates on purpose — the wider registers are there
# to stretch the distribution, not to become it.
REGISTERS = [
    "Speak warmly and conversationally, like talking to a close friend, with natural pauses.",
    "Speak warmly and conversationally, like talking to a close friend, with natural pauses.",
    "Speak brightly and with excitement, energetic and quick, pitching your voice up.",
    "Speak softly and tenderly, almost whispering, unhurried.",
    "Speak with emphasis and feeling, drawing out the important words.",
]


def lines_from(path: Path, limit: int | None = None) -> list[str]:
    """Text lines only — comments and blanks are corpus bookkeeping, not utterances."""
    out = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        out.append(s)
        if limit and len(out) >= limit:
            break
    return out


def build(kol_id: str, *, limit: int | None = None, out_dir: Path | None = None) -> dict:
    from voice_studio import synthesize

    corpus = REPO / "kols" / kol_id / "voice" / "corpus.txt"
    if not corpus.is_file():
        raise FileNotFoundError(f"no corpus text for {kol_id}: {corpus}")
    dst = out_dir or (REPO / "kols" / kol_id / "voice" / "rvc_corpus")
    dst.mkdir(parents=True, exist_ok=True)

    texts = lines_from(corpus, limit)
    made = skipped = failed = 0
    started = time.perf_counter()

    for i, text in enumerate(texts):
        f = dst / f"{kol_id}_rvc_{i:04d}.wav"
        # Resumable on purpose: this is a twenty-minute job against a network service, and
        # losing all of it to one timeout near the end would be its own reason not to run it.
        if f.is_file() and f.stat().st_size > 2000:
            skipped += 1
            continue
        try:
            synthesize(kol_id, text, out=f, instruct=REGISTERS[i % len(REGISTERS)])
            made += 1
        except Exception as exc:
            failed += 1
            print(f"  [{i:04d}] failed: {str(exc)[:110]}", flush=True)
            continue
        if made % 20 == 0:
            done = made + skipped
            rate = (time.perf_counter() - started) / max(made, 1)
            left = (len(texts) - done) * rate
            print(f"  {done}/{len(texts)}  ~{left/60:.1f} min left", flush=True)

    secs = _corpus_seconds(dst)
    return {"made": made, "skipped": skipped, "failed": failed,
            "clips": len(list(dst.glob("*.wav"))), "minutes": secs / 60, "dir": dst}


def _corpus_seconds(d: Path) -> float:
    import wave
    total = 0.0
    for f in d.glob("*.wav"):
        try:
            with wave.open(str(f), "rb") as w:
                total += w.getnframes() / float(w.getframerate())
        except Exception:
            pass
    return total


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("kol_id")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    t = time.perf_counter()
    r = build(args.kol_id, limit=args.limit,
              out_dir=Path(args.out) if args.out else None)
    print(f"\n  made {r['made']}, skipped {r['skipped']}, failed {r['failed']}")
    print(f"  {r['clips']} clips, {r['minutes']:.1f} minutes -> {r['dir']}")
    print(f"  took {(time.perf_counter() - t)/60:.1f} min")
    return 0 if r["clips"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
