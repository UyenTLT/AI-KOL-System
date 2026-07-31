#!/usr/bin/env python3
"""Convert a SoVITS training checkpoint into the distributable weight file.

Why this exists: `s2_train.py` finishes all epochs, then calls
`process_ckpt.savee()` to write `SoVITS_weights_<ver>/<exp>_e<N>_s<steps>.pth`.
If that output directory does not exist yet (the WebUI creates it at startup, the
training script does not) the save raises FileNotFoundError *after* training is
complete -- so the run's work is stranded in `logs/<exp>/logs_s2_<ver>/G_*.pth`.

`train_gptsovits.py` now pre-creates the directory, so this is a recovery tool for
runs that already hit the problem. `utils.save_checkpoint` stores the generator
state_dict under the "model" key, which is exactly what `savee()` consumes.

    GPT-SoVITS\\.venv\\Scripts\\python.exe tools\\voice_crawl\\recover_sovits_weight.py lena-chen
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GSV = REPO / "GPT-SoVITS"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kol_id")
    ap.add_argument("--exp-name", default=None)
    ap.add_argument("--version", default="v2Pro")
    ap.add_argument("--epoch", type=int, default=None, help="epoch label for the filename")
    ap.add_argument("--steps", type=int, default=None, help="step label for the filename")
    args = ap.parse_args()

    exp = args.exp_name or args.kol_id
    os.chdir(GSV)
    sys.path.insert(0, str(GSV))
    sys.path.insert(0, str(GSV / "GPT_SoVITS"))

    import torch
    import utils
    from process_ckpt import savee

    ckpt_dir = GSV / "logs" / exp / f"logs_s2_{args.version}"
    cands = sorted(ckpt_dir.glob("G_*.pth"), key=lambda p: p.stat().st_mtime)
    if not cands:
        raise SystemExit(f"no G_*.pth checkpoint in {ckpt_dir}")
    g_path = cands[-1]
    print(f"checkpoint : {g_path}  ({g_path.stat().st_size/1e6:.0f} MB)")

    blob = torch.load(str(g_path), map_location="cpu", weights_only=False)
    if "model" not in blob:
        raise SystemExit(f"unexpected checkpoint layout, keys={list(blob)[:8]}")
    state = blob["model"]
    iteration = int(blob.get("iteration", 0))
    print(f"iteration  : {iteration}   tensors: {len(state)}")

    cfg_path = GSV / "TEMP" / "tmp_s2.json"
    if not cfg_path.is_file():
        raise SystemExit(f"missing {cfg_path} -- re-run train_gptsovits.py to regenerate it")
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    hps = utils.HParams(**cfg)
    hps.model.version = args.version

    out_dir = GSV / hps.save_weight_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    epoch = args.epoch if args.epoch is not None else int(cfg["train"]["epochs"])
    steps = args.steps if args.steps is not None else iteration
    name = f"{exp}_e{epoch}_s{steps}"

    msg = savee(state, name, epoch, steps, hps,
                model_version=None if args.version not in {"v2Pro", "v2ProPlus"} else args.version,
                lora_rank=None)
    out = out_dir / f"{name}.pth"
    print(f"savee()    : {msg}")
    if not out.is_file():
        raise SystemExit(f"savee reported success but {out} is missing")
    print(f"wrote      : {out}  ({out.stat().st_size/1e6:.0f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
