#!/usr/bin/env python3
"""Paste anything about a product, get a spoken sales script. One step.

The catalogue route asks you to extract facts, save them, then write — sensible when a product
will be sold repeatedly, and too much ceremony when you just want to hear a pitch. This does
the whole thing in one call: read the raw material, work out what is actually claimed, write
the script in the KOL's own voice, and rule-check the result before handing it back.

The extraction is not decoration. Feeding raw marketing copy straight to a script writer
produces a script that repeats the marketing, including whatever it asserts — and product pages
assert a great deal. Pulling the facts out first creates a place to draw the line: what the
source actually states becomes available, and everything else is explicitly unknown.

Four angles, because one script rarely fits:

    honest      what she liked, what she did not, who it is not for
    hook        a few seconds designed to stop a scroll
    problem     name the problem first, then the product as the answer
    demo        walk through using it, as if on camera

    python tools/studio/sell.py sofia-hsu --file product.txt
    python tools/studio/sell.py sofia-hsu --file product.txt --angle hook --seconds 10
    python tools/studio/sell.py sofia-hsu --file product.txt --all --say
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools" / "studio"))
sys.path.insert(0, str(REPO / "tools" / "livetalking"))

ANGLES = {
    "honest": ("an honest review to her followers — what she liked, what she did not, and who "
               "it is not for. She has actually used it."),
    "hook":   ("a short scroll-stopping opener. One surprising or specific thing, said fast. "
               "No preamble, no greeting, straight in."),
    "problem": ("name the problem her followers have first, in their words, then introduce the "
                "product as what she uses for it."),
    "demo":   ("talking through actually using it, as if filming. Concrete steps and what she "
               "notices, not a feature list."),
}


def write_sales_script(kol_id: str, product_info: str, *, angle: str = "honest",
                       seconds: int = 20, model: str | None = None) -> dict:
    """Raw product text in, checked script out.

    Returns the script alongside the facts it was allowed to use and anything the source did
    not state, because "what it could not say" is usually the more useful half — a script that
    avoids the price because no price was given looks evasive until you can see that no price
    was ever supplied.
    """
    from product_editor import extract_product, to_entry, slugify, real_fields, dropped_from
    from voice_studio import write_script

    if angle not in ANGLES:
        raise ValueError(f"unknown angle {angle!r}; have {', '.join(ANGLES)}")

    fields = extract_product(product_info, model=model)
    entry = to_entry(fields, slugify(fields.get("name") or "product"))
    # real_fields, not fields: the verification bookkeeping key rides along in the dict, and
    # counting it as a product attribute makes callers report "__dropped__" to the user as
    # though it were something the script could quote.
    missing = [k for k, v in real_fields(fields).items() if v in (None, "")]

    # write_script rule-checks its own output and retries once with the broken rule named, so a
    # script that reaches here has already survived the guard.
    script = write_script(kol_id, ANGLES[angle], seconds=seconds, model=model, product=entry)
    return {"script": script, "angle": angle, "facts": fields, "unstated": missing,
            "dropped": dropped_from(fields), "product": entry}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("kol_id")
    ap.add_argument("--file", help="file holding the product information")
    ap.add_argument("--text", help="the product information inline")
    ap.add_argument("--angle", default="honest", choices=list(ANGLES))
    ap.add_argument("--all", action="store_true", help="write one script per angle")
    ap.add_argument("--seconds", type=int, default=20)
    ap.add_argument("--say", action="store_true", help="speak the result")
    ap.add_argument("--save-product", action="store_true",
                    help="also add the extracted facts to the KOL's catalogue")
    ap.add_argument("-o", "--out", default=None)
    args = ap.parse_args()

    if args.file:
        raw = Path(args.file).read_text(encoding="utf-8")
    elif args.text:
        raw = args.text
    else:
        raw = sys.stdin.read()
    if not raw.strip():
        raise SystemExit("no product information given")

    angles = list(ANGLES) if args.all else [args.angle]
    results = []
    for i, angle in enumerate(angles):
        r = write_sales_script(args.kol_id, raw, angle=angle, seconds=args.seconds)
        results.append(r)
        print(f"\n=== {angle} " + "=" * (60 - len(angle)))
        print(r["script"])
        if i == 0:
            from product_editor import real_fields
            known = [k for k, v in real_fields(r["facts"]).items() if v]
            print(f"\n  facts it could use : {', '.join(known) or 'none'}")
            print(f"  not stated in source: {', '.join(r['unstated']) or 'none'}")
            for d in r.get("dropped") or []:
                print(f"  invented, discarded : {d}")

    if args.save_product and results:
        from product_editor import save_product
        print(f"\n  catalogue -> {save_product(args.kol_id, results[0]['product'])}")

    if args.say:
        from stream_speak import speak_streaming
        out_dir = Path(args.out).parent if args.out else (REPO / "renders" / "sell")
        out_dir.mkdir(parents=True, exist_ok=True)
        for r in results:
            dst = (Path(args.out) if args.out and len(results) == 1
                   else out_dir / f"{r['angle']}.wav")
            speak_streaming(args.kol_id, r["script"], dst,
                            on_chunk=lambda i, n, w, a=r["angle"]:
                                print(f"  {a}: chunk {i}/{n}, first sound {w:.1f}s")
                                if i == 1 else None)
            print(f"  {r['angle']} -> {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
