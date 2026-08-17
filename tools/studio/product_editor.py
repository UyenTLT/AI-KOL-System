#!/usr/bin/env python3
"""Turn pasted product information into a catalogue entry a selling script may quote from.

The catalogue is what stops a script inventing a price: `check_reply` allows a number only if
it appears here, so anything absent is silently unsayable. That makes the catalogue worth
filling in properly — and hand-editing JSON is exactly the friction that stops people doing it.

So: paste whatever you have — a product page, an email, a spec sheet, a few lines of notes —
and a local model pulls out the fields. Two rules govern that extraction, and they are the
whole reason this is safe to use:

  * **Anything not stated becomes null**, never a guess. A null price is not a blank waiting to
    be filled; it is an instruction that no price may be spoken.
  * **Nothing is saved until a human has looked at it.** The extracted fields are shown for
    review first, because an extractor that misreads a price produces a script that confidently
    states the wrong one — and the guard cannot catch that, since by then the number is in the
    catalogue it checks against.

Claims of guaranteed profit are dropped at extraction rather than copied into `usp`. Even when
the source material makes them, a scripted endorsement repeating them is a different act.

    from product_editor import extract_product, save_product
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools" / "studio"))

FIELDS = ["name", "category", "what_it_is", "who_it_is_for", "price_TWD", "price_USD",
          "link", "usp", "honest_notes"]

PROMPT = """You extract product facts for a sales-script catalogue. Accuracy matters far more
than completeness: a wrong number here becomes a wrong number spoken aloud to customers.

Return ONLY a JSON object with exactly these keys:
  name, category, what_it_is, who_it_is_for, price_TWD, price_USD, link, usp, honest_notes

Rules:
- Use null for anything the source does not clearly state. Never guess, infer or round.
- Copy prices and URLs verbatim, including currency symbols and separators.
- usp: one short sentence, in the source's own terms, of why someone would buy it.
- honest_notes: any real limitation, caveat or "who it is NOT for" the source mentions.
  Null if the source only praises it — do not invent a downside to seem balanced.
- Do NOT carry over claims of guaranteed profit, returns, earnings or risk-free investment.
  Leave them out entirely, even if the source states them prominently.
- No commentary, no markdown fences. JSON object only."""


def extract_product(raw: str, model: str | None = None) -> dict:
    """Pull structured fields out of pasted text with the local model."""
    from openai import OpenAI
    client = OpenAI(base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1"),
                    api_key="ollama")
    r = client.chat.completions.create(
        model=model or os.getenv("KOL_LLM_MODEL", "qwen2.5:7b"),
        messages=[{"role": "system", "content": PROMPT},
                  {"role": "user", "content": raw[:8000]}],
        temperature=0.1, max_tokens=700)
    text = (r.choices[0].message.content or "").strip()
    # Models wrap JSON in fences often enough that not handling it is a self-inflicted bug.
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError(f"the model did not return JSON: {text[:200]}")
    data = json.loads(m.group(0))
    fields = {k: (data.get(k) if data.get(k) not in ("", "null", "N/A", "unknown") else None)
              for k in FIELDS}
    return verify_against_source(fields, raw)


_URL = re.compile(r"https?://[^\s,;)\"'>]+", re.IGNORECASE)


def verify_against_source(fields: dict, raw: str) -> dict:
    """Drop any price or link that does not actually appear in the source text.

    The prompt tells the model to use null for anything unstated, and for prices it does not
    listen. Measured on a product description containing no price at all — no currency symbol,
    no digits, not even the word "price" — it returned `$29.99` on three runs out of three.

    That is the worst possible failure for this pipeline rather than merely an annoying one.
    An invented price does not stay in the extractor: it lands in the catalogue, and the guard
    checks scripts *against* the catalogue, so from then on the fabricated number is the
    approved answer and every check passes.

    Prompting was already established as insufficient elsewhere in this project. This is the
    same conclusion applied here: verify in code. A price survives only if its digits appear in
    the source; a link only if the URL does.
    """
    digits = re.sub(r"\D", "", raw)
    urls = {u.lower().rstrip("/.,") for u in _URL.findall(raw)}
    checked = {k: fields.get(k) for k in FIELDS}      # only real fields; see DROPPED below
    dropped: list[str] = []

    for key in ("price_TWD", "price_USD"):
        val = checked.get(key)
        if not val:
            continue
        d = re.sub(r"\D", "", str(val))
        if not d or d not in digits:
            checked[key] = None
            dropped.append(f"{key}={val!r} (not in the source)")

    link = checked.get("link")
    if link:
        low = str(link).lower().rstrip("/.,")
        if not any(low.startswith(u) or u.startswith(low) for u in urls):
            checked["link"] = None
            dropped.append(f"link={link!r} (not in the source)")

    # Kept out of the returned dict. Stashing it in there was convenient and wrong: callers
    # iterate the fields to report "facts it could use", so the bookkeeping key showed up in
    # that list as though `_dropped` were a product attribute the script could quote.
    checked["__dropped__"] = dropped        # explicit, and filtered by dropped_from()
    return checked


def dropped_from(fields: dict) -> list[str]:
    """What verification threw away, without it polluting the field list."""
    return list(fields.get("__dropped__") or [])


def real_fields(fields: dict) -> dict:
    """The product attributes only — no bookkeeping keys."""
    return {k: v for k, v in fields.items() if k in FIELDS}


def to_entry(fields: dict, product_id: str, source_url: str | None = None) -> dict:
    """Shape extracted fields into the catalogue's schema. Bookkeeping keys never reach it."""
    fields = real_fields(fields)
    return {
        "id": product_id,
        "name": fields.get("name") or product_id,
        "source_url": source_url,
        "category": fields.get("category"),
        "what_it_is": fields.get("what_it_is"),
        "who_it_is_for": fields.get("who_it_is_for"),
        "price": {"TWD": fields.get("price_TWD"), "USD": fields.get("price_USD")},
        "buy_links": {"site": fields.get("link"), "affiliate": None},
        "usp": fields.get("usp"),
        "honest_notes": fields.get("honest_notes"),
        "self_bought_or_sponsored": None,
        "in_stock": None,
        "added": "extracted from pasted text and reviewed by a human before saving",
    }


def save_product(kol_id: str, entry: dict) -> Path:
    """Add or replace an entry, keeping the rest of the catalogue untouched."""
    p = REPO / "kols" / kol_id / "products.json"
    if p.is_file():
        data = json.loads(p.read_text(encoding="utf-8"))
    else:
        data = {"kol_id": kol_id,
                "description": ("Product knowledge base. A selling script may state ONLY what "
                                "is written here; anything null is treated as unknown and the "
                                "guard blocks a script that states it anyway."),
                "products": []}
    products = data.setdefault("products", [])
    for i, item in enumerate(products):
        if item.get("id") == entry["id"]:
            products[i] = entry
            break
    else:
        products.append(entry)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def slugify(name: str) -> str:
    s = re.sub(r"[^\w\s-]", "", (name or "product").lower()).strip()
    return re.sub(r"[\s_]+", "-", s)[:40] or "product"


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("kol_id")
    ap.add_argument("--file", help="read the raw product info from this file")
    ap.add_argument("--id", default=None)
    ap.add_argument("--url", default=None)
    ap.add_argument("--save", action="store_true")
    args = ap.parse_args()

    raw = Path(args.file).read_text(encoding="utf-8") if args.file else sys.stdin.read()
    fields = extract_product(raw)
    print(json.dumps(fields, ensure_ascii=False, indent=2))
    missing = [k for k, v in real_fields(fields).items() if v is None]
    for d in dropped_from(fields):
        print(f"  dropped by verification: {d}")
    if missing:
        print(f"\nnot stated in the source (will be unsayable): {', '.join(missing)}")
    if args.save:
        entry = to_entry(fields, args.id or slugify(fields.get("name")), args.url)
        print(f"\nsaved -> {save_product(args.kol_id, entry)}")
