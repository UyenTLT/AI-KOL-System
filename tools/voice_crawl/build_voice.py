#!/usr/bin/env python3
"""One command to build a complete voice: corpus -> bootstrap -> fine-tune.

Chains the three steps that were previously run by hand, and invokes each with the right
interpreter — the corpus/bootstrap stages need the repo venv (edge-tts, soundfile) while
training needs the GPT-SoVITS venv (numpy<2, its own torch). Getting that wrong is the
easiest way to waste half an hour.

Creates a minimal profile.json if the id does not exist yet, so a plain voice preset can be
built without inventing a whole KOL persona. Presets are deliberately NOT added to
kols/index.json, so they stay out of the KOL roster while still working with every tool.

    python tools/voice_crawl/build_voice.py preset-en-warm \
        --edge-voice en-US-EmmaMultilingualNeural --lang en
    python tools/voice_crawl/build_voice.py preset-zhtw \
        --edge-voice zh-TW-HsiaoYuNeural --lang zh --minutes 30
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
REPO_PY = REPO / ".venv" / "Scripts" / "python.exe"
GSV_PY = REPO / "GPT-SoVITS" / ".venv" / "Scripts" / "python.exe"

LANG_META = {
    "en": {"languages": ["English (native)"], "ratio_zh": 0.0},
    "zh": {"languages": ["Mandarin / Traditional Chinese (native)", "English (fluent)"],
           "ratio_zh": 1.0},
}


def run(py: Path, args: list[str], label: str) -> None:
    print(f"\n{'='*70}\n{label}\n{'='*70}", flush=True)
    if not py.is_file():
        raise SystemExit(f"interpreter missing: {py}")
    proc = subprocess.run([str(py), *args], cwd=str(REPO))
    if proc.returncode != 0:
        raise SystemExit(f"{label} failed (exit {proc.returncode})")


def ensure_profile(vid: str, lang: str, edge_voice: str, name: str | None) -> Path:
    """Create a minimal profile if absent; never overwrite an existing persona."""
    d = REPO / "kols" / vid
    p = d / "profile.json"
    if p.is_file():
        print(f"  profile exists, leaving it alone: {p.relative_to(REPO)}")
        return p
    d.mkdir(parents=True, exist_ok=True)
    (d / "voice").mkdir(exist_ok=True)
    prof = {
        "id": vid,
        "meta": {"created_at": time.strftime("%Y-%m-%d"), "status": "voice_preset",
                 "kind": "voice_preset",
                 "design_note": ("A Voice Studio preset, not a KOL persona. Deliberately not "
                                 "listed in kols/index.json so it stays out of the roster.")},
        "identity": {"name": name or vid, "languages": LANG_META[lang]["languages"]},
        "ai_assets": {"voice": {
            "engine": "gpt-sovits", "voice_id": f"{vid}-v1",
            "source": "synthetic_bootstrap", "bootstrap_timbre": f"edge:{edge_voice}",
            "reference_lang": lang, "status": "not_started",
            "api": "http://127.0.0.1:9880", "fallback_voice": edge_voice}},
    }
    p.write_text(json.dumps(prof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"  created {p.relative_to(REPO)}")
    return p


def wire_profile(vid: str, lang: str, minutes: float) -> None:
    """Point the profile at the reference clip the bootstrap just produced."""
    d = REPO / "kols" / vid
    p = d / "profile.json"
    prof = json.loads(p.read_text(encoding="utf-8"))
    v = prof.setdefault("ai_assets", {}).setdefault("voice", {})
    ref_txt = d / "voice" / "ref.txt"
    rows = [r for r in (d / "voice" / "dataset" / f"{vid}.list")
            .read_text(encoding="utf-8").splitlines() if r.strip()]
    v.update({
        "dataset_list": f"kols/{vid}/voice/dataset/{vid}.list",
        "reference_audio": f"kols/{vid}/voice/ref.wav",
        "reference_text": ref_txt.read_text(encoding="utf-8").strip() if ref_txt.is_file() else "",
        "reference_lang": lang,
        "dataset_clips": len(rows), "dataset_minutes": round(minutes, 1),
        "status": "dataset_ready_pending_finetune",
    })
    p.write_text(json.dumps(prof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"  wired reference + {len(rows)} clips into the profile")


def clear_dataset(vid: str) -> None:
    """Bootstrap appends to the .list, so a rebuild must start clean or voices blend."""
    d = REPO / "kols" / vid / "voice" / "dataset"
    if not d.is_dir():
        return
    n = 0
    for f in list(d.glob("*.wav")) + list(d.glob("*.list")) + list(d.glob("*.json")):
        f.unlink(); n += 1
    if n:
        print(f"  cleared {n} file(s) from a previous build")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("voice_id")
    ap.add_argument("--edge-voice", required=True, help="edge-tts short name for the timbre")
    ap.add_argument("--lang", required=True, choices=["en", "zh"])
    ap.add_argument("--name", default=None)
    ap.add_argument("--minutes", type=float, default=30.0)
    ap.add_argument("--sovits-epochs", type=int, default=8)
    ap.add_argument("--gpt-epochs", type=int, default=16)
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--skip-train", action="store_true")
    args = ap.parse_args()

    vid = args.voice_id
    t0 = time.time()
    print(f"building voice '{vid}'  lang={args.lang}  timbre={args.edge_voice}")

    ensure_profile(vid, args.lang, args.edge_voice, args.name)
    clear_dataset(vid)

    corpus = REPO / "kols" / vid / "voice" / "corpus.txt"
    run(REPO_PY, ["tools/voice_crawl/corpus_builder.py",
                  "--minutes", str(args.minutes),
                  "--ratio-zh", str(LANG_META[args.lang]["ratio_zh"]),
                  "-o", str(corpus)], "1/3  corpus")

    run(REPO_PY, ["tools/voice_crawl/bootstrap_timbre.py", vid,
                  "--voice", args.edge_voice, "--text-file", str(corpus),
                  "--concurrency", str(args.concurrency)], "2/3  bootstrap synthesis + QC")

    man = REPO / "kols" / vid / "voice" / "dataset" / "bootstrap_manifest.json"
    minutes = json.loads(man.read_text(encoding="utf-8")).get("accepted_minutes", 0.0) \
        if man.is_file() else 0.0
    wire_profile(vid, args.lang, minutes)

    if args.skip_train:
        print(f"\nstopped before training (--skip-train). {minutes:.1f} min of audio ready.")
        return 0

    run(GSV_PY, ["tools/voice_crawl/train_gptsovits.py", vid,
                 "--sovits-epochs", str(args.sovits_epochs),
                 "--gpt-epochs", str(args.gpt_epochs)], "3/3  fine-tune")

    v = json.loads((REPO / "kols" / vid / "profile.json").read_text(encoding="utf-8"))
    v = v["ai_assets"]["voice"]
    print(f"\n{'='*70}")
    print(f"voice '{vid}' built in {(time.time()-t0)/60:.1f} min")
    print(f"  corpus  : {v.get('dataset_clips')} clips / {v.get('dataset_minutes')} min")
    print(f"  sovits  : {v.get('sovits_weights')}")
    print(f"  gpt     : {v.get('gpt_weights')}")
    print(f"  status  : {v.get('status')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
