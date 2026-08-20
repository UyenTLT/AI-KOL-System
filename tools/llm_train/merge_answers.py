#!/usr/bin/env python3
"""Collect what several writers sent back, check it, and report what the set actually looks like.

Handing packs out is the easy half. The half that decides whether the work was worth doing is
what happens when the files come back, and it is not "concatenate them":

* **An answer that breaks a rule cannot be trained on.** The writing tool warns while somebody
  types, but a warning is advice and this is the gate. The same `check_reply` the live system
  runs decides, so nothing reaches training that would have been refused in production.
* **Writers drift from the brief in different directions**, and the drift is invisible in one
  file and obvious across several. One person ends every answer with a question, another writes
  paragraphs where the rest write two lines. Both are fixable by asking — but only if somebody
  looks, so this measures each writer against the same rubric the model is steered by.
* **The shared prompts are the calibration.** Every pack contains the same handful, so the same
  question comes back in several voices. Reading those side by side is the fastest way to see
  whether the brief was understood, and they are printed together for exactly that.

    python tools/llm_train/merge_answers.py returned/
    python tools/llm_train/merge_answers.py returned/ --out datasets/sofia-hsu-gold.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
for sub in ("livetalking", "livestream", "llm_train"):
    sys.path.insert(0, str(REPO / "tools" / sub))


def load(folder: Path) -> list[dict]:
    """Every answer from every file in the folder, tagged with the file it came from."""
    rows = []
    for f in sorted(folder.glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                print(f"  {f.name}: a line is not valid JSON, skipped", file=sys.stderr)
                continue
            r.setdefault("writer", f.stem.replace("answers-", ""))
            r["_file"] = f.name
            rows.append(r)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", help="directory holding the answers-*.jsonl files sent back")
    ap.add_argument("--kol", default="sofia-hsu")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass

    from harvest_talk import _FILLER, _OPINION, _QBACK, is_story
    from persona_brain import check_reply, speaks_cjk

    folder = Path(args.folder)
    rows = load(folder)
    if not rows:
        print(f"nothing to merge in {folder}", file=sys.stderr)
        return 1
    no_cjk = not speaks_cjk(args.kol)

    kept, refused = [], []
    for r in rows:
        answer = (r.get("answer") or "").strip()
        if not answer:
            continue
        bad = check_reply(r.get("prompt", ""), answer, no_cjk=no_cjk)
        (refused if bad else kept).append({**r, "violations": bad})

    print(f"{len(rows)} answers from {len({r['writer'] for r in rows})} writers "
          f"across {len({r['_file'] for r in rows})} files")
    print(f"{len(kept)} pass the production rules, {len(refused)} refused")
    if refused:
        why: dict[str, int] = defaultdict(int)
        for r in refused:
            for v in r["violations"]:
                why[v] += 1
        for k, v in sorted(why.items(), key=lambda x: -x[1]):
            print(f"    {k:<22} {v}")
        print("    (these go back to the writer rather than into training)")

    # Per writer, against the same rubric the model is steered by. A writer whose numbers sit
    # far from the others has read the brief differently, and that is worth one conversation
    # rather than a silent correction later.
    print()
    by = defaultdict(list)
    for r in kept:
        by[r["writer"]].append(r["answer"])
    head = ("writer", "kept", "words", "story", "opinion", "spoken", "ends on ?")
    widths = [max(len(str(h)), 9) for h in head]
    print("  ".join(str(h).ljust(w) for h, w in zip(head, widths)))
    print("  ".join("-" * w for w in widths))
    for w, ans in sorted(by.items(), key=lambda x: -len(x[1])):
        n = len(ans)
        lens = sorted(len(a.split()) for a in ans)
        row = (w[:9], n, lens[n // 2],
               f"{100 * sum(1 for a in ans if is_story(a)) / n:.0f}%",
               f"{100 * sum(1 for a in ans if _OPINION.search(a)) / n:.0f}%",
               f"{100 * sum(1 for a in ans if _FILLER.search(a)) / n:.0f}%",
               f"{100 * sum(1 for a in ans if _QBACK.search(a)) / n:.0f}%")
        print("  ".join(str(c).ljust(wd) for c, wd in zip(row, widths)))
    print("  measured on real answers to real questions: story 4%, opinion 19%, "
          "spoken 50%, ends on a question 5%")

    # The same prompt in several voices. This is what the shared set was for.
    shared = defaultdict(list)
    for r in kept:
        if r.get("shared"):
            shared[r["prompt"]].append((r["writer"], r["answer"]))
    both = {p: v for p, v in shared.items() if len(v) > 1}
    if both:
        print(f"\n{len(both)} shared prompts came back from more than one writer:")
        for prompt, answers in list(both.items())[:3]:
            print(f"\n  {prompt}")
            for w, a in answers:
                print(f"    [{w}] {a[:150]}")

    out = Path(args.out) if args.out else REPO / "datasets" / f"{args.kol}-gold.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        for r in kept:
            fh.write(json.dumps({"kol": args.kol, "writer": r["writer"], "kind": r.get("kind"),
                                 "prompt": r["prompt"], "answer": r["answer"]},
                                ensure_ascii=False) + "\n")
    print(f"\n{len(kept)} gold answers -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
