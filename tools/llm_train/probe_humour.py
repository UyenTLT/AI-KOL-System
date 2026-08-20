#!/usr/bin/env python3
"""Did training on hand-written humour move the humour, and does it survive the wrong name?

Two questions, one run, both of which the existing evaluation cannot answer. `evaluate.py`
scores rule violations with an LLM judge; it says nothing about whether she is funny. And the
humour corpus was written under a system prompt that names her Sofia Hsu, while production
still emits Sofia Vargas from profile.json -- so 450 of the training examples are conditioned
on a string no live request contains. Whether the behaviour crosses that gap is measurable
rather than arguable, so it is measured here.

    adapter + "Sofia Hsu"      what the corpus taught, asked for by name
    adapter + "Sofia Vargas"   the same thing under the name production actually sends
    base    + "Sofia Hsu"      the floor: no training, same questions

Questions are the held-out validation split, which the adapter never saw, plus the probe set.
Scored with harvest_talk.is_playful -- the same detector every earlier humour number in this
project was reported against, so the numbers are comparable to the ones in the commit log.

    finetune\.venv\Scripts\python.exe tools\llm_train\probe_humour.py sofia-hsu
"""
from __future__ import annotations

import argparse, json, sys, time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
for sub in ("livetalking", "llm_train"):
    sys.path.insert(0, str(REPO / "tools" / sub))
BASE = REPO / "finetune" / "base" / "Qwen2.5-7B-Instruct"

SYS = ("You are {name}, a virtual influencer talking to your followers. "
       "Reply as yourself, out loud, in one or two short sentences.")


def questions(kol_id: str, limit: int) -> list[str]:
    p = REPO / "datasets" / f"{kol_id}-chat-val.jsonl"
    rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    # Single-turn rows only. A mid-conversation reply is a different act and mixing the two
    # would make the rate depend on the split rather than on the model.
    qs = [r["messages"][-2]["content"] for r in rows if len(r["messages"]) == 3]
    return qs[:limit]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("kol_id")
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--adapter", default="")
    args = ap.parse_args()

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from peft import PeftModel
    from harvest_talk import is_playful, is_story, _OPINION, _QBACK
    from persona_brain import check_reply

    adapter = Path(args.adapter) if args.adapter else \
        REPO / "finetune" / "adapters" / args.kol_id / "final"
    qs = questions(args.kol_id, args.n)
    print(f"  {len(qs)} held-out questions\n")

    tok = AutoTokenizer.from_pretrained(str(BASE))
    quant = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                               bnb_4bit_use_double_quant=True,
                               bnb_4bit_compute_dtype=torch.bfloat16)
    model = AutoModelForCausalLM.from_pretrained(
        str(BASE), quantization_config=quant, dtype=torch.bfloat16, device_map={"": 0})
    model.eval()

    def run(name: str) -> list[str]:
        out = []
        for q in qs:
            msgs = [{"role": "system", "content": SYS.format(name=name)},
                    {"role": "user", "content": q}]
            # return_dict, not return_tensors alone: this transformers returns a BatchEncoding
            # from apply_chat_template, and generate() then reads .shape off a dict and dies.
            enc = tok.apply_chat_template(msgs, add_generation_prompt=True,
                                          return_tensors="pt", return_dict=True)
            enc = {k: v.to(model.device) for k, v in enc.items()}
            n_in = enc["input_ids"].shape[1]
            with torch.no_grad():
                g = model.generate(**enc, max_new_tokens=90, do_sample=True, temperature=0.8,
                                   top_p=0.9, pad_token_id=tok.pad_token_id or tok.eos_token_id)
            out.append(tok.decode(g[0][n_in:], skip_special_tokens=True).strip())
        return out

    def report(label: str, ans: list[str]) -> dict:
        n = len(ans)
        r = {"playful": sum(map(is_playful, ans)), "story": sum(map(is_story, ans)),
             "opinion": sum(1 for a in ans if _OPINION.search(a)),
             "qback": sum(1 for a in ans if _QBACK.search(a)),
             "blocked": sum(1 for q, a in zip(qs, ans) if check_reply(q, a)),
             "words": sorted(len(a.split()) for a in ans)[n // 2]}
        print(f"  {label:<26} playful {100*r['playful']/n:5.1f}%   story {100*r['story']/n:5.1f}%"
              f"   opinion {100*r['opinion']/n:5.1f}%   qback {100*r['qback']/n:5.1f}%"
              f"   blocked {r['blocked']:2d}   median {r['words']:3d}w")
        return r

    results, samples = {}, {}
    t0 = time.perf_counter()
    print("  base, untrained")
    a = run("Sofia Hsu");  results["base+Hsu"] = report("base + 'Sofia Hsu'", a)
    samples["base+Hsu"] = a

    model = PeftModel.from_pretrained(model, str(adapter))
    model.eval()
    print("\n  adapter")
    a = run("Sofia Hsu");     results["tuned+Hsu"] = report("tuned + 'Sofia Hsu'", a)
    samples["tuned+Hsu"] = a
    a = run("Sofia Vargas");  results["tuned+Vargas"] = report("tuned + 'Sofia Vargas'", a)
    samples["tuned+Vargas"] = a

    print(f"\n  {(time.perf_counter()-t0)/60:.1f} min")
    out = REPO / "finetune" / "adapters" / args.kol_id / "humour.json"
    out.write_text(json.dumps({"n": len(qs), "results": results,
                               "samples": {k: v[:8] for k, v in samples.items()}},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
