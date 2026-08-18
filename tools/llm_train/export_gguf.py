#!/usr/bin/env python3
"""Merge the adapter into the base and hand the result to Ollama, which runs it far faster.

Serving the adapter through transformers works and was the right first step — it needed no
conversion and no extra tooling. It is also slow: measured on this GPU, the same model generates
at 12.1 tokens per second under bitsandbytes 4-bit and 34 through Ollama's GGUF runtime. Same
weights, same card, 2.5x. At 27 tokens a reply that is the difference between 2.2 seconds of
waiting and under a second.

Three stages, each skippable if its output already exists:

    merge      LoRA folded into the base weights, saved as fp16 safetensors
    convert    safetensors to GGUF, quantised
    import     registered with Ollama under a name the rest of the system can point at

The conversion needs llama.cpp's `convert_hf_to_gguf.py`. It is a pure-Python script — no build
step, no compiler — so this clones the repository and uses it directly rather than asking anyone
to install a toolchain.

    finetune\\.venv\\Scripts\\python.exe tools\\llm_train\\export_gguf.py sofia-vargas
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BASE = REPO / "finetune" / "base" / "Qwen2.5-7B-Instruct"
ADAPTERS = REPO / "finetune" / "adapters"
WORK = REPO / "finetune" / "export"
LLAMA_CPP = REPO / "finetune" / "llama.cpp"


def run(cmd: list[str], **kw) -> None:
    print(f"  $ {' '.join(str(c) for c in cmd[:6])}{' ...' if len(cmd) > 6 else ''}", flush=True)
    p = subprocess.run([str(c) for c in cmd], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", **kw)
    if p.returncode != 0:
        tail = ((p.stdout or "") + (p.stderr or "")).strip()[-700:]
        raise RuntimeError(f"failed (exit {p.returncode}):\n{tail}")


def _stale(out: Path, src: Path) -> bool:
    """Does `out` need rebuilding because `src` is newer?

    Existence alone is the wrong test, and it silently shipped the wrong model once. After a
    retrain the merge re-ran and the conversion skipped, because a GGUF from six days earlier
    was sitting where the new one belonged — so `ollama create` registered the previous tune
    under the current name, and every service pointed at it would have served the old weights
    while every log said the new ones had been deployed.

    Comparing modification times costs nothing and makes the skip mean "already up to date"
    rather than "a file with this name exists".
    """
    if not out.exists():
        return True
    newest = max((f.stat().st_mtime for f in ([src] if src.is_file() else src.rglob("*"))
                  if f.is_file()), default=0)
    return newest > out.stat().st_mtime


def merge(kol_id: str, base: Path, adapter: Path, out: Path) -> Path:
    """Fold the LoRA into the weights so nothing downstream needs to know about adapters."""
    if ((out / "model.safetensors.index.json").is_file() or (out / "model.safetensors").is_file())             and not _stale(out / "config.json", adapter):
        print(f"  merged is up to date -> {out}")
        return out
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import PeftModel

    print("  loading base in fp16 (this is the memory-hungry step, on CPU)", flush=True)
    # CPU and fp16 on purpose: merging needs the full unquantised weights, which do not fit on a
    # 12 GB card, and merging into 4-bit weights would bake the quantisation error in.
    model = AutoModelForCausalLM.from_pretrained(str(base), dtype=torch.float16,
                                                device_map="cpu", low_cpu_mem_usage=True)
    model = PeftModel.from_pretrained(model, str(adapter), device_map="cpu")
    model = model.merge_and_unload()
    out.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(out), safe_serialization=True)
    AutoTokenizer.from_pretrained(str(base)).save_pretrained(str(out))
    return out


def ensure_llama_cpp() -> Path:
    script = LLAMA_CPP / "convert_hf_to_gguf.py"
    if script.is_file():
        return script
    LLAMA_CPP.parent.mkdir(parents=True, exist_ok=True)
    run(["git", "clone", "--depth", "1", "https://github.com/ggml-org/llama.cpp",
         str(LLAMA_CPP)])
    if not script.is_file():
        raise FileNotFoundError(f"clone succeeded but {script} is missing")
    return script


def convert(merged: Path, gguf: Path, outtype: str = "f16") -> Path:
    """safetensors to GGUF, unquantised — Ollama does the quantising.

    q8_0 was the first choice, on the reasoning that the Python converter cannot go lower
    without llama-quantize and that the difference would be size rather than speed. Measured,
    that was wrong on both counts: the q8_0 build served at 14.8 tokens per second against 34
    for the q4 base, because every token reads twice the weights and 8.1 GB leaves no room
    beside CosyVoice on a 12 GB card. Size IS speed here.

    `ollama create --quantize` does q4_K_M with no extra binaries, but only from an unquantised
    source, so this stage now emits f16 and hands the quantising over.
    """
    if not _stale(gguf, merged):
        print(f"  gguf is up to date -> {gguf}")
        return gguf
    if gguf.is_file():
        print(f"  gguf is older than the merged weights, rebuilding it")
        gguf.unlink()
    script = ensure_llama_cpp()
    gguf.parent.mkdir(parents=True, exist_ok=True)
    run([sys.executable, str(script), str(merged), "--outfile", str(gguf),
         "--outtype", outtype])
    return gguf


def to_ollama(gguf: Path, name: str, quantize: str = "q4_K_M") -> str:
    mf = gguf.parent / f"Modelfile-{name}"
    # The template has to match what the model was trained on. Qwen2.5's chat format is what
    # both the base and the fine-tune saw; a mismatched template produces fluent nonsense, which
    # is harder to spot than an outright failure.
    mf.write_text(
        f'FROM {gguf.as_posix()}\n'
        'TEMPLATE """{{ if .System }}<|im_start|>system\n{{ .System }}<|im_end|>\n{{ end }}'
        '{{ if .Prompt }}<|im_start|>user\n{{ .Prompt }}<|im_end|>\n{{ end }}'
        '<|im_start|>assistant\n{{ .Response }}<|im_end|>\n"""\n'
        'PARAMETER stop "<|im_start|>"\n'
        'PARAMETER stop "<|im_end|>"\n',
        encoding="utf-8")
    cmd = ["ollama", "create", name, "-f", str(mf)]
    if quantize:
        cmd += ["--quantize", quantize]
    run(cmd)
    return name


def main() -> int:
    # Model output carries emoji and this console is cp950. Printing a sample must not be able
    # to destroy a run whose numbers are already computed — it happened here, and in
    # harvest_talk before it.
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("kol_id")
    ap.add_argument("--adapter", default=None)
    ap.add_argument("--name", default=None, help="the name Ollama will serve it under")
    ap.add_argument("--outtype", default="f16")
    ap.add_argument("--quantize", default="q4_K_M",
                    help="what Ollama quantises to; empty string to keep f16")
    ap.add_argument("--keep-merged", action="store_true",
                    help="keep the 15 GB fp16 merge after the GGUF is built")
    args = ap.parse_args()

    adapter = Path(args.adapter) if args.adapter else (ADAPTERS / args.kol_id / "final")
    if not (adapter / "adapter_config.json").is_file():
        raise SystemExit(f"no adapter at {adapter} — train one first")
    name = args.name or f"{args.kol_id}-tuned"
    merged = WORK / f"{args.kol_id}-merged"
    gguf = WORK / f"{args.kol_id}-{args.outtype}.gguf"

    t = time.perf_counter()
    print("\n[1/3] merge")
    merge(args.kol_id, BASE, adapter, merged)
    print("\n[2/3] convert to gguf")
    convert(merged, gguf, args.outtype)
    print("\n[3/3] register with ollama")
    to_ollama(gguf, name, args.quantize)

    if not args.keep_merged and merged.is_dir():
        shutil.rmtree(merged, ignore_errors=True)
        print(f"  removed the intermediate merge ({merged.name})")

    print(f"\n  done in {(time.perf_counter()-t)/60:.1f} min")
    print(f"  gguf  -> {gguf}  ({gguf.stat().st_size/1e9:.1f} GB)")
    print(f"  serve -> set KOL_LLM_MODEL={name} and point OLLAMA_BASE_URL at Ollama's own port")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
