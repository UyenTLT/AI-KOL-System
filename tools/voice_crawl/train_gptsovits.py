#!/usr/bin/env python3
"""Headless GPT-SoVITS fine-tune for one KOL -- no WebUI, reproducible from a .list.

The GPT-SoVITS WebUI is interactive and hides the real pipeline behind Gradio
callbacks. This drives the exact same six steps directly, so a voice can be rebuilt
from `kols/<id>/voice/dataset/<id>.list` with one command:

    1. 1-get-text.py          text -> phonemes + BERT features
    2. 2-get-hubert-wav32k.py audio -> HuBERT SSL features
    2b. 2-get-sv.py           speaker-verification embeddings   (v2Pro/v2ProPlus only)
    3. 3-get-semantic.py      -> semantic tokens
    4. s2_train.py            fine-tune SoVITS  -> SoVITS_weights_<ver>/<exp>.pth
    5. s1_train.py            fine-tune GPT     -> GPT_weights_<ver>/<exp>.ckpt

Each prepare step is a separate process reading its arguments from the environment
(that is how upstream wrote them), so this sets those env vars rather than importing.

MUST run with the GPT-SoVITS venv, whose deps conflict with the repo venv:
    GPT-SoVITS\\.venv\\Scripts\\python.exe tools\\voice_crawl\\train_gptsovits.py lena-chen

Useful flags:
    --version v2Pro       v1 | v2 | v2Pro | v2ProPlus   (v3/v4 use a different trainer)
    --sovits-epochs 8     --gpt-epochs 15
    --batch-size 0        0 = auto from free VRAM
    --steps prepare       run only data prep, skip training
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GSV = REPO / "GPT-SoVITS"

# s2_train.py handles these; v3/v4 need s2_train_v3_lora.py and a vocoder.
S2_TRAIN_VERSIONS = {"v1", "v2", "v2Pro", "v2ProPlus"}

PRETRAINED_S2G = {
    "v1": "GPT_SoVITS/pretrained_models/s2G488k.pth",
    "v2": "GPT_SoVITS/pretrained_models/gsv-v2final-pretrained/s2G2333k.pth",
    "v2Pro": "GPT_SoVITS/pretrained_models/v2Pro/s2Gv2Pro.pth",
    "v2ProPlus": "GPT_SoVITS/pretrained_models/v2Pro/s2Gv2ProPlus.pth",
}
PRETRAINED_S1 = {
    "v1": "GPT_SoVITS/pretrained_models/s1bert25hz-2kh-longer-epoch=68e-step=50232.ckpt",
    "v2": "GPT_SoVITS/pretrained_models/gsv-v2final-pretrained/s1bert25hz-5kh-longer-epoch=12-step=369668.ckpt",
    "v2Pro": "GPT_SoVITS/pretrained_models/s1v3.ckpt",
    "v2ProPlus": "GPT_SoVITS/pretrained_models/s1v3.ckpt",
}
SOVITS_WEIGHT_ROOT = {
    "v1": "SoVITS_weights", "v2": "SoVITS_weights_v2",
    "v2Pro": "SoVITS_weights_v2Pro", "v2ProPlus": "SoVITS_weights_v2ProPlus",
}
GPT_WEIGHT_ROOT = {
    "v1": "GPT_weights", "v2": "GPT_weights_v2",
    "v2Pro": "GPT_weights_v2Pro", "v2ProPlus": "GPT_weights_v2ProPlus",
}
BERT_DIR = "GPT_SoVITS/pretrained_models/chinese-roberta-wwm-ext-large"
HUBERT_DIR = "GPT_SoVITS/pretrained_models/chinese-hubert-base"
SV_PATH = "GPT_SoVITS/pretrained_models/sv/pretrained_eres2netv2w24s4ep4.ckpt"


def log(msg: str) -> None:
    print(f"\n{'='*70}\n{msg}\n{'='*70}", flush=True)


def auto_batch_size(version: str) -> int:
    """Mirror the WebUI heuristic: ~half the GPU's GB, min 1."""
    try:
        import torch
        if not torch.cuda.is_available():
            return 2
        gb = torch.cuda.get_device_properties(0).total_memory / 1024**3
        return max(1, int(gb // 2))
    except Exception:
        return 2


def ffmpeg_shared_bin() -> str | None:
    """Locate an FFmpeg *shared* build's bin dir (the one that ships DLLs).

    `2-get-sv.py` calls `torchaudio.load`, which in torchaudio 2.11 goes through
    torchcodec; torchcodec dlopens `libtorchcodec_core<N>.dll`, whose dependencies
    are the FFmpeg **shared** libraries. A static ffmpeg.exe (Gyan `full_build`)
    satisfies the CLI-based loaders but not this one, so the shared build
    (`Gyan.FFmpeg.Shared`) must be on PATH as well.
    """
    env_dir = os.environ.get("FFMPEG_SHARED_BIN")
    if env_dir and Path(env_dir).is_dir():
        return env_dir
    roots = [
        Path(os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages")),
        Path(r"C:\ffmpeg"),
    ]
    for root in roots:
        if not root.is_dir():
            continue
        for dll in root.glob("**/bin/avcodec*.dll"):
            return str(dll.parent)
    return None


def base_env() -> dict:
    """Environment for every GPT-SoVITS subprocess.

    The prepare/train scripts do bare `from text.cleaner import ...` and
    `from tools.my_utils import ...`, which need BOTH the repo root (for `tools`)
    and `GPT_SoVITS/` (for `text`) importable. Upstream gets this free from its
    portable `runtime\\python.exe` `._pth`; running under a venv we must set
    PYTHONPATH ourselves. (`-s` only disables user site-packages, so PYTHONPATH
    is still honoured — unlike `-I`, which would ignore it.)
    """
    env = os.environ.copy()
    paths = [str(GSV), str(GSV / "GPT_SoVITS")]
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join(paths + ([existing] if existing else []))
    env["_CUDA_VISIBLE_DEVICES"] = "0"
    shared = ffmpeg_shared_bin()
    if shared:
        env["PATH"] = shared + os.pathsep + env.get("PATH", "")
    # s2_train spawns DDP, which then spawns DataLoader workers; on Windows each
    # worker re-initialises CUDA inside the spawned process and the first
    # iteration segfaults (0xC0000005). Load in-process instead. Read by the
    # local patch in GPT_SoVITS/s2_train.py; s1 takes it from its YAML config.
    if os.name == "nt":
        env.setdefault("GSV_NUM_WORKERS", "0")
    return env


def run_step(name: str, script: str, env_extra: dict, py: str) -> None:
    log(f"STEP: {name}")
    env = base_env()
    env.update({k: str(v) for k, v in env_extra.items()})
    proc = subprocess.run([py, "-s", script], cwd=str(GSV), env=env)
    if proc.returncode != 0:
        raise SystemExit(f"step failed: {name} (exit {proc.returncode})")


def expect_outputs(label: str, path: Path, min_count: int, pattern: str = "*") -> None:
    """Fail loudly when a step produced nothing despite exiting 0.

    Every prepare script wraps its per-clip work in a bare `except:` that only
    prints the traceback, so a systemic problem (a blocked native DLL, a missing
    model) yields exit code 0 and an empty output directory. Trusting the exit
    code alone means the failure surfaces much later as a confusing training
    error, so assert the artifacts actually exist.
    """
    got = len(list(path.glob(pattern))) if path.is_dir() else 0
    if got < min_count:
        raise SystemExit(
            f"\n{label} produced {got} file(s) in {path} but expected >= {min_count}.\n"
            f"The step exited 0 because it swallows per-clip exceptions -- re-run it "
            f"directly and read the full traceback:\n"
            f"  cd GPT-SoVITS && .venv\\Scripts\\python.exe -s <script>  (capture ALL output)"
        )
    print(f"  ok: {got} file(s) in {path.name}/")


def merge_parts(opt_dir: Path) -> None:
    """Concatenate the per-part prepare outputs, as the WebUI does.

    Steps 1 and 3 write `2-name2text-<i>.txt` / `6-name2semantic-<i>.tsv` per
    shard; s1_train.py reads the merged `2-name2text.txt` / `6-name2semantic.tsv`.
    Upstream merges in the Gradio callback, so a headless run must do it too.
    """
    for pattern, merged, header in (
        ("2-name2text-*.txt", "2-name2text.txt", None),
        ("6-name2semantic-*.tsv", "6-name2semantic.tsv", "item_name\tsemantic_audio"),
    ):
        parts = sorted(opt_dir.glob(pattern))
        if not parts:
            continue
        lines: list[str] = []
        for p in parts:
            lines += [ln for ln in p.read_text(encoding="utf-8").split("\n") if ln.strip()]
        if header:
            lines = [ln for ln in lines if ln != header]
            lines.insert(0, header)
        (opt_dir / merged).write_text("\n".join(lines) + "\n", encoding="utf-8")
        for p in parts:
            p.unlink()
        print(f"  merged {len(parts)} part(s) -> {merged} ({len(lines)} lines)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kol_id")
    ap.add_argument("--version", default="v2Pro", choices=sorted(S2_TRAIN_VERSIONS))
    ap.add_argument("--exp-name", default=None, help="defaults to the KOL id")
    ap.add_argument("--sovits-epochs", type=int, default=8)
    ap.add_argument("--gpt-epochs", type=int, default=15)
    ap.add_argument("--batch-size", type=int, default=0, help="0 = auto from VRAM")
    ap.add_argument("--save-every", type=int, default=4)
    ap.add_argument("--steps", default="all",
                    choices=["all", "prepare", "train", "sovits", "gpt"],
                    help="'sovits'/'gpt' run a single training stage (useful to resume "
                         "after one stage already succeeded)")
    ap.add_argument("--fp32", action="store_true", help="disable half precision")
    args = ap.parse_args()

    exp = args.exp_name or args.kol_id
    version = args.version
    py = sys.executable

    # --- validate inputs before spending GPU time -----------------------------
    dataset = REPO / "kols" / args.kol_id / "voice" / "dataset"
    list_file = dataset / f"{args.kol_id}.list"
    if not list_file.is_file():
        raise SystemExit(f"no training list: {list_file}\n"
                         f"Run bootstrap_timbre.py or crawl.py first.")
    rows = [r for r in list_file.read_text(encoding="utf-8").splitlines() if r.strip()]
    missing = [r.split("|")[0] for r in rows if not Path(r.split("|")[0]).is_file()]
    if missing:
        raise SystemExit(f"{len(missing)} wav(s) in the .list are missing, e.g. {missing[0]}")

    import soundfile as sf
    total_sec = sum(sf.info(r.split("|")[0]).duration for r in rows)
    print(f"dataset : {len(rows)} clips, {total_sec/60:.1f} min")
    print(f"exp     : {exp}   version: {version}")
    if total_sec < 5 * 60:
        print(f"\nWARNING: only {total_sec/60:.1f} min. GPT-SoVITS wants >=5 min "
              f"(20-30 min comfortable). Quality will suffer.")

    for rel in (PRETRAINED_S2G[version], PRETRAINED_S1[version], BERT_DIR, HUBERT_DIR):
        if not (GSV / rel).exists():
            raise SystemExit(f"missing pretrained asset: {rel}\n"
                             f"Run tools/voice_crawl/fetch_gptsovits_models.ps1")
    if version in {"v2Pro", "v2ProPlus"} and not (GSV / SV_PATH).exists():
        raise SystemExit(f"{version} needs the SV model: {SV_PATH}")

    batch = args.batch_size or auto_batch_size(version)
    is_half = not args.fp32

    # Weights are only written on multiples of save_every, so any trailing epochs
    # past the last multiple are computed and then thrown away. Warn instead of
    # silently wasting GPU time (e.g. 15 epochs @ save_every 4 -> keeps e12).
    for label, total in (("--sovits-epochs", args.sovits_epochs),
                         ("--gpt-epochs", args.gpt_epochs)):
        if total % args.save_every:
            kept = total - (total % args.save_every)
            print(f"WARNING: {label}={total} is not a multiple of --save-every="
                  f"{args.save_every}; the newest saved weight will be epoch {kept}, "
                  f"so {total - kept} epoch(s) of training would be discarded.")
    opt_dir = f"logs/{exp}"
    (GSV / opt_dir).mkdir(parents=True, exist_ok=True)
    (GSV / "TEMP").mkdir(exist_ok=True)
    # The weight output dirs are created by the WebUI at startup, not by the
    # training scripts. Without them process_ckpt.savee() raises FileNotFoundError
    # *after* training completes -- losing the whole run.
    (GSV / SOVITS_WEIGHT_ROOT[version]).mkdir(parents=True, exist_ok=True)
    (GSV / GPT_WEIGHT_ROOT[version]).mkdir(parents=True, exist_ok=True)

    common = {
        "inp_text": str(list_file),
        "inp_wav_dir": "",           # .list already holds absolute wav paths
        "exp_name": exp,
        "i_part": "0", "all_parts": "1",
        "_CUDA_VISIBLE_DEVICES": "0",
        "opt_dir": opt_dir,
        "is_half": str(is_half),
        "version": version,
    }

    # --- data preparation -----------------------------------------------------
    out = GSV / opt_dir
    n = len(rows)
    do_sovits = args.steps in ("all", "train", "sovits")
    do_gpt = args.steps in ("all", "train", "gpt")
    if args.steps in ("all", "prepare"):
        run_step("1/6 text -> phonemes + BERT",
                 "GPT_SoVITS/prepare_datasets/1-get-text.py",
                 {**common, "bert_pretrained_dir": BERT_DIR}, py)
        # BERT features exist only for ZH rows (EN uses ARPAbet, word2ph=None),
        # so require at least one rather than one per clip.
        expect_outputs("step 1 (BERT)", out / "3-bert", 1, "*.pt")
        expect_outputs("step 1 (phonemes)", out, 1, "2-name2text-*.txt")

        run_step("2/6 audio -> HuBERT features",
                 "GPT_SoVITS/prepare_datasets/2-get-hubert-wav32k.py",
                 {**common, "cnhubert_base_dir": HUBERT_DIR}, py)
        expect_outputs("step 2 (HuBERT)", out / "4-cnhubert", n, "*.pt")
        expect_outputs("step 2 (wav32k)", out / "5-wav32k", n, "*.wav")

        if version in {"v2Pro", "v2ProPlus"}:
            run_step("2b/6 speaker-verification embeddings",
                     "GPT_SoVITS/prepare_datasets/2-get-sv.py",
                     {**common, "sv_path": SV_PATH}, py)
            expect_outputs("step 2b (SV)", out / "7-sv_cn", n, "*.pt")

        s2cfg = ("GPT_SoVITS/configs/s2.json" if version not in {"v2Pro", "v2ProPlus"}
                 else f"GPT_SoVITS/configs/s2{version}.json")
        run_step("3/6 -> semantic tokens",
                 "GPT_SoVITS/prepare_datasets/3-get-semantic.py",
                 {**common, "pretrained_s2G": PRETRAINED_S2G[version],
                  "s2config_path": s2cfg}, py)
        expect_outputs("step 3 (semantic)", out, 1, "6-name2semantic-*.tsv")

        log("merging per-part prepare outputs")
        merge_parts(out)
        for f, minimum in (("2-name2text.txt", 2), ("6-name2semantic.tsv", 2)):
            p = out / f
            got = len([ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]) if p.is_file() else 0
            if got < minimum:
                raise SystemExit(f"{f} has {got} line(s) -- prepare did not produce usable data")
            print(f"  {f}: {got} lines")

    if args.steps == "prepare":
        print("\nprepare-only run complete.")
        return 0

    # --- SoVITS (s2) ----------------------------------------------------------
    s2cfg_path = (GSV / ("GPT_SoVITS/configs/s2.json"
                         if version not in {"v2Pro", "v2ProPlus"}
                         else f"GPT_SoVITS/configs/s2{version}.json"))
    data = json.loads(s2cfg_path.read_text(encoding="utf-8"))
    s2_batch = batch if is_half else max(1, batch // 2)
    data["train"].update({
        "fp16_run": is_half,
        "batch_size": s2_batch,
        "epochs": args.sovits_epochs,
        "text_low_lr_rate": 0.4,
        "pretrained_s2G": PRETRAINED_S2G[version],
        "pretrained_s2D": PRETRAINED_S2G[version].replace("s2G", "s2D"),
        "if_save_latest": True,
        "if_save_every_weights": True,
        "save_every_epoch": args.save_every,
        "gpu_numbers": "0",
        "grad_ckpt": False,
        "lora_rank": 32,
    })
    data["model"]["version"] = version
    data["data"]["exp_dir"] = data["s2_ckpt_dir"] = opt_dir
    data["save_weight_dir"] = SOVITS_WEIGHT_ROOT[version]
    data["name"] = exp
    data["version"] = version
    (GSV / opt_dir / f"logs_s2_{version}").mkdir(parents=True, exist_ok=True)
    tmp_s2 = GSV / "TEMP" / "tmp_s2.json"
    tmp_s2.write_text(json.dumps(data), encoding="utf-8")

    env = base_env()
    if do_sovits:
        log(f"STEP 4/6: fine-tune SoVITS ({args.sovits_epochs} epochs, batch {s2_batch})")
        if subprocess.run([py, "-s", "GPT_SoVITS/s2_train.py", "--config", str(tmp_s2)],
                          cwd=str(GSV), env=env).returncode != 0:
            raise SystemExit("SoVITS training failed")
    else:
        log("STEP 4/6: skipped (--steps gpt); tmp_s2.json refreshed for reference")

    # --- GPT (s1) -------------------------------------------------------------
    import yaml
    s1cfg_path = GSV / ("GPT_SoVITS/configs/s1longer.yaml" if version == "v1"
                        else "GPT_SoVITS/configs/s1longer-v2.yaml")
    s1 = yaml.safe_load(s1cfg_path.read_text(encoding="utf-8"))
    s1_batch = batch if is_half else max(1, batch // 2)
    if not is_half:
        s1["train"]["precision"] = "32"
    s1["train"].update({
        "batch_size": s1_batch,
        "epochs": args.gpt_epochs,
        "save_every_n_epoch": args.save_every,
        "if_save_every_weights": True,
        "if_save_latest": True,
        "if_dpo": False,
        "half_weights_save_dir": GPT_WEIGHT_ROOT[version],
        "exp_name": exp,
    })
    # Same Windows DataLoader-worker crash as s2; s1 reads this from the config
    # (AR/data/data_module.py) rather than an env var, so set it here.
    if os.name == "nt":
        s1.setdefault("data", {})["num_workers"] = 0
    s1["pretrained_s1"] = PRETRAINED_S1[version]
    s1["train_semantic_path"] = f"{opt_dir}/6-name2semantic.tsv"
    s1["train_phoneme_path"] = f"{opt_dir}/2-name2text.txt"
    s1["output_dir"] = f"{opt_dir}/logs_s1_{version}"
    (GSV / opt_dir / "logs_s1").mkdir(parents=True, exist_ok=True)
    tmp_s1 = GSV / "TEMP" / "tmp_s1.yaml"
    tmp_s1.write_text(yaml.dump(s1, default_flow_style=False), encoding="utf-8")

    if do_gpt:
        log(f"STEP 5/6: fine-tune GPT ({args.gpt_epochs} epochs, batch {s1_batch})")
        env["hz"] = "25hz"
        if subprocess.run([py, "-s", "GPT_SoVITS/s1_train.py", "--config_file", str(tmp_s1)],
                          cwd=str(GSV), env=env).returncode != 0:
            raise SystemExit("GPT training failed")
    else:
        log("STEP 5/6: skipped (--steps sovits)")

    # --- report + wire into the profile --------------------------------------
    log("STEP 6/6: results")
    sov = sorted((GSV / SOVITS_WEIGHT_ROOT[version]).glob(f"{exp}*.pth"),
                 key=lambda p: p.stat().st_mtime)
    gpt = sorted((GSV / GPT_WEIGHT_ROOT[version]).glob(f"{exp}*.ckpt"),
                 key=lambda p: p.stat().st_mtime)
    if not sov or not gpt:
        print("WARNING: expected weights not found; check the training logs above.")
        print(f"  looked in {SOVITS_WEIGHT_ROOT[version]}/ and {GPT_WEIGHT_ROOT[version]}/")
        return 1
    sovits_w, gpt_w = sov[-1], gpt[-1]
    print(f"SoVITS -> {sovits_w}")
    print(f"GPT    -> {gpt_w}")

    prof_path = REPO / "kols" / args.kol_id / "profile.json"
    prof = json.loads(prof_path.read_text(encoding="utf-8"))
    voice = prof.setdefault("ai_assets", {}).setdefault("voice", {})
    voice["engine"] = "gpt-sovits"
    voice["gsv_version"] = version
    voice["sovits_weights"] = str(sovits_w.relative_to(REPO)).replace("\\", "/")
    voice["gpt_weights"] = str(gpt_w.relative_to(REPO)).replace("\\", "/")
    voice["status"] = "finetuned"
    prof_path.write_text(json.dumps(prof, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    print(f"\nwrote weights into {prof_path} -> ai_assets.voice")
    print("\nNext:")
    print(f"  1) serve : GPT-SoVITS\\.venv\\Scripts\\python.exe api_v2.py -a 127.0.0.1 -p 9880 "
          f"-c GPT_SoVITS/configs/tts_infer.yaml")
    print(f"  2) verify: python tools/tts_train/tts_client.py {args.kol_id} "
          f"\"大家好 Hi everyone\" zh out.wav")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
