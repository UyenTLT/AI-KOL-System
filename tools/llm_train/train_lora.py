#!/usr/bin/env python3
"""QLoRA fine-tune of the persona model, on this machine.

This is the one training job the RTX 5070 can actually do. Lip-sync needs 24 GB and has to be
rented; a 7B language model in 4-bit with LoRA adapters fits in 12 GB with room to spare.

What it is for, precisely: moving the persona out of the prompt and into the weights. Measured
with the full persona and style instructions in context, the base model still greeted a fan
again mid-conversation on 2 turns of 4 and signed off with an offer of help on 1 of 4 — both
explicitly forbidden by the text it had just been given. The training data is that same model's
answers, filtered to the ones that obeyed. Training on its own good half is what turns a habit
it has into a habit it keeps.

Only the base weights are quantised. The LoRA adapters train in bfloat16, which is what makes
4-bit training stable rather than a slow way to get a broken model.

    finetune\\.venv\\Scripts\\python.exe tools\\llm_train\\train_lora.py sofia-hsu
    ... --epochs 3 --rank 16
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BASE = REPO / "finetune" / "base" / "Qwen2.5-7B-Instruct"
DATA = REPO / "datasets"
OUT = REPO / "finetune" / "adapters"


def load_jsonl(p: Path) -> list[dict]:
    if not p.is_file():
        raise FileNotFoundError(f"no dataset at {p} — run build_dataset.py first")
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("kol_id")
    ap.add_argument("--epochs", type=float, default=3.0)
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--batch", type=int, default=1)
    ap.add_argument("--accum", type=int, default=8)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--maxlen", type=int, default=512)
    ap.add_argument("--base", default=str(BASE))
    args = ap.parse_args()

    import torch
    from datasets import Dataset
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from trl import SFTConfig, SFTTrainer

    train = load_jsonl(DATA / f"{args.kol_id}-chat-train.jsonl")
    val = load_jsonl(DATA / f"{args.kol_id}-chat-val.jsonl")
    print(f"  {len(train)} train / {len(val)} val examples")

    tok = AutoTokenizer.from_pretrained(args.base)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token

    # nf4 with double quantisation is the configuration QLoRA was measured on; bfloat16 compute
    # keeps the matmuls in a range this GPU handles natively.
    quant = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                               bnb_4bit_use_double_quant=True,
                               bnb_4bit_compute_dtype=torch.bfloat16)
    model = AutoModelForCausalLM.from_pretrained(
        args.base, quantization_config=quant, dtype=torch.bfloat16, device_map={"": 0})
    model.config.use_cache = False
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)

    # Attention and MLP projections both. Attention-only adapters move who the model attends to;
    # the MLP is where the phrasing lives, and phrasing is the whole complaint being fixed.
    lora = LoraConfig(
        r=args.rank, lora_alpha=args.rank * 2, lora_dropout=0.05, bias="none",
        task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"])
    model = get_peft_model(model, lora)
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    print(f"  trainable {trainable/1e6:.1f}M of {total/1e9:.2f}B ({100*trainable/total:.3f}%)")

    out = OUT / args.kol_id
    out.mkdir(parents=True, exist_ok=True)
    cfg = SFTConfig(
        output_dir=str(out), num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch, gradient_accumulation_steps=args.accum,
        # warmup_steps, not warmup_ratio: trl 1.9 dropped the ratio form from SFTConfig and
        # raises TypeError on it. Five steps is about 5% of the ~87 this run does.
        learning_rate=args.lr, lr_scheduler_type="cosine", warmup_steps=5,
        logging_steps=5, save_strategy="epoch", eval_strategy="epoch",
        bf16=True, optim="paged_adamw_8bit", max_length=args.maxlen,
        gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        report_to=[], seed=0,
        # Train on the reply only. Including the prompt in the loss teaches the model to produce
        # fan comments as well, which is not the job and dilutes the signal that is.
        completion_only_loss=True)

    trainer = SFTTrainer(model=model, args=cfg, processing_class=tok,
                         train_dataset=Dataset.from_list(train),
                         eval_dataset=Dataset.from_list(val))
    t = time.perf_counter()
    trainer.train()
    mins = (time.perf_counter() - t) / 60

    final = out / "final"
    trainer.model.save_pretrained(str(final))
    tok.save_pretrained(str(final))
    peak = torch.cuda.max_memory_allocated() / 1e9
    print(f"\n  trained in {mins:.1f} min, peak VRAM {peak:.1f} GB")
    print(f"  adapter -> {final}")
    (out / "run.json").write_text(json.dumps({
        "kol_id": args.kol_id, "base": args.base, "epochs": args.epochs, "rank": args.rank,
        "lr": args.lr, "train": len(train), "val": len(val),
        "minutes": round(mins, 1), "peak_vram_gb": round(peak, 1)},
        ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
