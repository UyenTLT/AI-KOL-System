#!/usr/bin/env python3
"""Train an RVC voice-conversion model for a KOL, from the command line.

RVC ships its training as a Gradio app: the four stages exist as scripts, but the filelist and
config that stand between extraction and training are built inside a button handler, so there is
no CLI path from a folder of audio to a trained model. This is that path.

Three things had to be worked out by running them, and each is a trap worth naming:

* **The stage scripts must be run as modules.** `python train/preprocess.py` puts `train/` first
  on `sys.path`, so `import train.dataset...` resolves the name `train` to `train/train.py`
  rather than to the package, and dies on a circular import that has nothing to do with the
  actual problem. `python -m train.preprocess` resolves it correctly.
* **The experiment directory must exist first.** Every stage opens its log for append without
  creating the parent, so the first stage fails on a missing directory rather than on anything
  meaningful. The webui makes the directory before calling out.
* **v2 at 40k uses the v1 config.** `configs/v2/40k.json` is not what the webui loads for that
  combination — it takes `configs/v1/40k.json`, and only v2 at 32k/48k reads from `v2/`.

Stages, all of which can be re-run independently:

    slice      cut the corpus into training clips at both 40k and 16k
    f0         pitch contours with RMVPE on the GPU
    feature    HuBERT/ContentVec features
    train      fine-tune from the pretrained f0G40k / f0D40k pair
    index      the retrieval index that gives RVC its name

    python tools/tts_train/train_rvc.py sofia-hsu --epochs 150
    python tools/tts_train/train_rvc.py sofia-hsu --stage train --epochs 20 --batch 4
"""
from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RVC = REPO / "RVC"
PY = RVC / ".venv" / "Scripts" / "python.exe"

STAGES = ["slice", "f0", "feature", "train", "index"]


def run(args: list[str], *, quiet_tail: int = 6) -> None:
    """Run one RVC stage as a module, from the RVC root, and fail loudly."""
    cmd = [str(PY), "-m"] + args
    print(f"  $ python -m {' '.join(args)}", flush=True)
    p = subprocess.run(cmd, cwd=str(RVC), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    out = ((p.stdout or "") + (p.stderr or "")).strip().splitlines()
    for line in out[-quiet_tail:]:
        print(f"    {line}", flush=True)
    if p.returncode != 0:
        raise RuntimeError(f"{args[0]} failed with exit code {p.returncode}")


def exp_dir(kol_id: str) -> Path:
    return RVC / "logs" / kol_id


def build_filelist(kol_id: str, sr: str = "40k", version: str = "v2",
                   spk_id: int = 0) -> int:
    """Pair up every slice with its features, and write what training reads.

    A name only qualifies when all four artefacts exist. Extraction failures are per-clip and
    silent in the aggregate, so intersecting the four directories is what stops a half-extracted
    clip from taking the run down several minutes into training.
    """
    d = exp_dir(kol_id)
    gt, feat = d / "0_gt_wavs", d / f"3_feature{768 if version == 'v2' else 256}"
    f0, f0nsf = d / "2a_f0", d / "2b-f0nsf"
    for p in (gt, feat, f0, f0nsf):
        if not p.is_dir():
            raise FileNotFoundError(f"missing {p} — run the earlier stages first")

    stems = (set(x.stem for x in gt.glob("*.wav"))
             & set(x.stem for x in feat.glob("*.npy"))
             & set(x.name.split(".")[0] for x in f0.glob("*.npy"))
             & set(x.name.split(".")[0] for x in f0nsf.glob("*.npy")))
    if not stems:
        raise RuntimeError("nothing usable to train on — slicing or extraction produced nothing")

    now = RVC.as_posix()
    lines = [f"{gt.as_posix()}/{s}.wav|{feat.as_posix()}/{s}.npy|"
             f"{f0.as_posix()}/{s}.wav.npy|{f0nsf.as_posix()}/{s}.wav.npy|{spk_id}"
             for s in sorted(stems)]
    # Two silent examples, exactly as the webui adds them: they teach the model what to do with
    # silence, which is most of the gap between words.
    fea_dim = 768 if version == "v2" else 256
    mute = (f"{now}/logs/mute/0_gt_wavs/mute{sr}.wav|{now}/logs/mute/3_feature{fea_dim}/mute.npy|"
            f"{now}/logs/mute/2a_f0/mute.wav.npy|{now}/logs/mute/2b-f0nsf/mute.wav.npy|{spk_id}")
    lines += [mute, mute]
    random.shuffle(lines)
    (d / "filelist.txt").write_text("\n".join(lines), encoding="utf-8")

    # v2 at 40k reads the v1 config — this is the webui's own branch, not a simplification.
    src = RVC / "configs" / ("v1" if (version == "v1" or sr == "40k") else "v2") / f"{sr}.json"
    cfg = json.loads(src.read_text(encoding="utf-8"))
    cfg.pop("speaker_info", None)
    (d / "config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=4, sort_keys=True),
                                   encoding="utf-8")
    return len(stems)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("kol_id")
    ap.add_argument("--corpus", default=None, help="folder of wavs (default: the KOL's rvc_corpus)")
    ap.add_argument("--sr", default="40k", choices=["32k", "40k", "48k"])
    ap.add_argument("--version", default="v2", choices=["v1", "v2"])
    ap.add_argument("--epochs", type=int, default=150)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--save-every", type=int, default=25)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--stage", choices=STAGES, default=None,
                    help="run one stage only; default runs all of them in order")
    args = ap.parse_args()

    corpus = Path(args.corpus) if args.corpus else (
        REPO / "kols" / args.kol_id / "voice" / "rvc_corpus")
    if not corpus.is_dir():
        raise SystemExit(f"no corpus at {corpus} — build one with build_rvc_corpus.py")

    d = exp_dir(args.kol_id)
    d.mkdir(parents=True, exist_ok=True)
    todo = [args.stage] if args.stage else STAGES
    sr_hz = {"32k": 32000, "40k": 40000, "48k": 48000}[args.sr]
    started = time.perf_counter()

    if "slice" in todo:
        print(f"\n[slice] {len(list(corpus.glob('*.wav')))} clips from {corpus}")
        run(["train.preprocess", corpus.as_posix(), str(sr_hz), str(args.workers),
             d.as_posix(), "False", "3.0"])

    if "f0" in todo:
        print("\n[f0] RMVPE on the GPU")
        run(["train.dataset.extract_f0", "cuda", "1", "0", "0", d.as_posix(), "False"])

    if "feature" in todo:
        print("\n[feature] HuBERT/ContentVec")
        run(["train.dataset.extract_hubert_feature", "cuda:0", "1", "0", "0",
             d.as_posix(), args.version, "False"])

    if "train" in todo:
        n = build_filelist(args.kol_id, args.sr, args.version)
        # RVC saves the finished model to a relative "assets/weights/..." and does not create
        # the directory. Worse, it catches the resulting error and logs it, so training runs to
        # completion, exits 0, and leaves no model behind — a failure that looks like success
        # right up until you go looking for the file.
        (RVC / "assets" / "weights").mkdir(parents=True, exist_ok=True)
        print(f"\n[train] {n} slices, {args.epochs} epochs, batch {args.batch}")
        pg = (RVC / "assets" / "pretrained_v2" / f"f0G{args.sr}.pth").as_posix()
        pd = (RVC / "assets" / "pretrained_v2" / f"f0D{args.sr}.pth").as_posix()
        run(["train.train", "-e", args.kol_id, "-sr", args.sr, "-f0", "1",
             "-bs", str(args.batch), "-g", "0", "-te", str(args.epochs),
             "-se", str(args.save_every), "-pg", pg, "-pd", pd,
             "-l", "1", "-c", "0", "-sw", "1", "-v", args.version], quiet_tail=12)

    if "index" in todo:
        print("\n[index] retrieval index")
        (RVC / "assets" / "indices").mkdir(parents=True, exist_ok=True)
        run(["train.train_index", args.kol_id, args.version,
             (RVC / "assets" / "indices").as_posix(), str(args.workers), "auto"])

    print(f"\n  finished in {(time.perf_counter() - started)/60:.1f} min")
    models = sorted((RVC / "assets" / "weights").glob(f"{args.kol_id}*.pth"))
    for p in models:
        print(f"  model -> {p}  ({p.stat().st_size/1e6:.1f} MB)")
    for p in sorted(d.glob("*.index")):
        print(f"  index -> {p}  ({p.stat().st_size/1e6:.1f} MB)")
    if "train" in todo and not models:
        # Training logs its save failures and exits 0 regardless, so the exit code cannot be
        # trusted to mean a model exists. Checking for the file is the only honest test.
        raise SystemExit("training reported success but wrote no model — check the log above")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
