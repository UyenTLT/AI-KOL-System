#!/usr/bin/env python3
"""Did the fine-tune actually work? Three arms, held-out messages, the same judge.

The claim being tested is specific: that the persona moved from the prompt into the weights. So
the comparison is not "tuned vs untuned" but three separate things:

    base  + short prompt   what you get with no training and no persona — the floor
    base  + full persona   what production does today, and what training has to beat
    tuned + short prompt   the goal: the same behaviour without the character sheet in context

If the third column does not beat the second, the training bought nothing and should be said so.

Messages come from the validation split, which the adapter never saw. The judge is the same
`build_dataset.judge` used to filter the training data — the guards that run in production plus
the assistant habits being trained out. Reusing it is deliberate: the training set was selected
by this function, so scoring with anything else would be measuring a different thing than the
one optimised for.

    finetune\\.venv\\Scripts\\python.exe tools\\llm_train\\evaluate.py sofia-vargas
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
for sub in ("livetalking", "livestream", "llm_train"):
    sys.path.insert(0, str(REPO / "tools" / sub))

BASE = REPO / "finetune" / "base" / "Qwen2.5-7B-Instruct"
ADAPTERS = REPO / "finetune" / "adapters"
DATA = REPO / "datasets"


def held_out(kol_id: str, limit: int | None = None) -> list[dict]:
    """Validation rows as {short_system, thread, user, mid}.

    `thread` is what came before, and `mid` says whether this reply lands inside a running
    conversation. Testing every reply as if it were a first message is what made the previous
    evaluation miss the point: the habit being trained out only appears on the third turn.
    """
    p = DATA / f"{kol_id}-chat-val.jsonl"
    rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    out = []
    for r in rows:
        m = r["messages"]
        out.append({"system": m[0]["content"], "thread": m[1:-2],
                    "user": m[-2]["content"], "mid": len(m) > 3})
    return out[:limit] if limit else out


def score(replies: list[tuple[dict, str]]) -> dict:
    """Violation counts over (case, reply) pairs."""
    from build_dataset import judge
    n = len(replies)
    fails, tally, lens = 0, {}, []
    mid_n = mid_fail = 0
    for case, rep in replies:
        ok, why = judge(rep, case["user"], mid=case["mid"])
        lens.append(len(rep))
        if case["mid"]:
            mid_n += 1
        if not ok:
            fails += 1
            if case["mid"]:
                mid_fail += 1
            for w in why:
                tally[w] = tally.get(w, 0) + 1
    return {"n": n, "clean": n - fails, "rate": (n - fails) / n if n else 0.0,
            "mid_n": mid_n, "mid_clean": mid_n - mid_fail,
            "mid_rate": (mid_n - mid_fail) / mid_n if mid_n else 0.0,
            "avg_len": sum(lens) / n if n else 0, "why": tally}


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
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--max-new", type=int, default=110)
    args = ap.parse_args()

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from peft import PeftModel
    from persona_brain import build_system_prompt, sanitize_for_speech
    from stage import MODES

    pairs = held_out(args.kol_id, args.limit)
    print(f"  {len(pairs)} held-out messages\n")

    tok = AutoTokenizer.from_pretrained(str(BASE))
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    quant = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                               bnb_4bit_use_double_quant=True,
                               bnb_4bit_compute_dtype=torch.bfloat16)
    model = AutoModelForCausalLM.from_pretrained(
        str(BASE), quantization_config=quant, dtype=torch.bfloat16, device_map={"": 0})
    adapter = Path(args.adapter) if args.adapter else (ADAPTERS / args.kol_id / "final")
    model = PeftModel.from_pretrained(model, str(adapter))
    model.eval()

    full_sys = (build_system_prompt(args.kol_id) + "\n\n" + MODES["comment"]["system"])

    def generate(system: str, case: dict) -> str:
        msgs = ([{"role": "system", "content": system}] + list(case["thread"])
                + [{"role": "user", "content": case["user"]}])
        # return_dict=True: in transformers 5 the template returns a BatchEncoding rather than a
        # bare tensor, so indexing `.shape` on the result raises a bare AttributeError from deep
        # inside generate() with nothing pointing at the cause.
        enc = tok.apply_chat_template(msgs, add_generation_prompt=True,
                                      return_tensors="pt", return_dict=True)
        enc = {k: v.to(model.device) for k, v in enc.items()}
        n_in = enc["input_ids"].shape[-1]
        with torch.no_grad():
            out = model.generate(**enc, max_new_tokens=args.max_new, do_sample=True,
                                 temperature=0.7, top_p=0.9, pad_token_id=tok.pad_token_id)
        txt = tok.decode(out[0][n_in:], skip_special_tokens=True)
        return sanitize_for_speech(txt, False).strip()

    arms = {}
    # disable_adapter gives the untouched base from the same load — no second 15 GB of weights,
    # and no chance of the two arms differing by anything other than the adapter.
    for name, use_adapter, use_full in (
            ("base  + short prompt", False, False),
            ("base  + full persona", False, True),
            ("tuned + short prompt", True, False)):
        reps = []
        t = time.perf_counter()
        for case in pairs:
            sysmsg = full_sys if use_full else case["system"]
            if use_adapter:
                reps.append((case, generate(sysmsg, case)))
            else:
                with model.disable_adapter():
                    reps.append((case, generate(sysmsg, case)))
        arms[name] = {**score(reps), "secs": time.perf_counter() - t,
                      "samples": [(c["user"], r) for c, r in reps if c["mid"]][:3]}

    mid = sum(1 for c in pairs if c["mid"])
    print(f"  {mid} of {len(pairs)} are mid-conversation\n")
    print(f"{'arm':<24}{'all':>10}{'mid-conv':>12}{'len':>7}{'s':>7}")
    for name, r in arms.items():
        print(f"{name:<24}{100*r['rate']:9.0f}%{100*r['mid_rate']:11.0f}%"
              f"{r['avg_len']:7.0f}{r['secs']:7.0f}")
    print("\n  why they failed:")
    for name, r in arms.items():
        w = ", ".join(f"{k}×{v}" for k, v in sorted(r["why"].items(), key=lambda x: -x[1]))
        print(f"    {name:<24} {w or 'nothing'}")
    print("\n  samples from the tuned model:")
    for msg, rep in arms["tuned + short prompt"]["samples"]:
        print(f"    FAN  : {msg}")
        print(f"    SOFIA: {rep}\n")

    out = ADAPTERS / args.kol_id / "eval.json"
    out.write_text(json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "samples"}
                               for k, v in arms.items()}, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(f"  -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
