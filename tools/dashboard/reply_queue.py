#!/usr/bin/env python3
"""Approve-before-send reply queue — the human-in-the-loop the policy requires.

Every KOL profile carries `social.comment_policy_mode: "suggest"`: the AI drafts, a human
approves, only then does anything reach a follower. Nothing enforced that until now — the
chat path spoke the model's output the moment it was generated.

This is the enforcement. A draft is generated, rule-checked, and parked. It can only be
spoken or marked sent after someone approves it, and every decision is recorded.

Storage is one append-only JSONL per KOL (`kols/<id>/replies/queue.jsonl`): trivially
auditable, diffable, needs no database, and survives a crash mid-review.

    python tools/dashboard/reply_queue.py draft lena-chen "這罐多少錢？"
    python tools/dashboard/reply_queue.py list lena-chen
    python tools/dashboard/reply_queue.py approve lena-chen <id> --speak
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools" / "livetalking"))

LIVETALKING = os.getenv("LIVETALKING_URL", "http://127.0.0.1:8010")

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_BLOCKED = "blocked"      # guards refused it; needs an edit, not just a click


def queue_path(kol_id: str) -> Path:
    p = REPO / "kols" / kol_id / "replies"
    p.mkdir(parents=True, exist_ok=True)
    return p / "queue.jsonl"


def _append(kol_id: str, rec: dict) -> None:
    with open(queue_path(kol_id), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def load_all(kol_id: str) -> list[dict]:
    """Replay the log; later records for the same id supersede earlier ones."""
    path = queue_path(kol_id)
    if not path.is_file():
        return []
    items: dict[str, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        rid = rec.get("id")
        if not rid:
            continue
        items[rid] = {**items.get(rid, {}), **rec}
    return sorted(items.values(), key=lambda r: r.get("created", 0), reverse=True)


def policy_mode(kol_id: str) -> str:
    try:
        prof = json.loads((REPO / "kols" / kol_id / "profile.json").read_text(encoding="utf-8"))
    except Exception:
        return "suggest"
    for scope in (prof.get("social") or {}, prof.get("commerce") or {}, prof):
        if isinstance(scope, dict) and scope.get("comment_policy_mode"):
            return scope["comment_policy_mode"]
    return "suggest"


def create_draft(kol_id: str, follower_msg: str, *, model: str | None = None) -> dict:
    """Generate a draft reply and park it. Never sends anything."""
    from persona_brain import chat, check_reply

    rid = uuid.uuid4().hex[:10]
    rec = {"id": rid, "kol_id": kol_id, "created": time.time(),
           "follower": follower_msg, "status": STATUS_PENDING,
           "policy_mode": policy_mode(kol_id)}
    try:
        draft = chat(kol_id, follower_msg, **({"model": model} if model else {}))
    except Exception as exc:
        rec.update(status=STATUS_BLOCKED, draft="", error=f"{type(exc).__name__}: {exc}",
                   violations=["generation_failed"])
        _append(kol_id, rec)
        return rec

    violations = check_reply(follower_msg, draft)
    rec["draft"] = draft
    rec["violations"] = violations
    # chat() already retries and falls back, so a violation here means even the fallback
    # tripped a rule. Park it as blocked: a human must rewrite, not just approve.
    rec["status"] = STATUS_BLOCKED if violations else STATUS_PENDING
    _append(kol_id, rec)
    return rec


def _livetalking_session() -> str | None:
    """Best-effort lookup of a live avatar session.

    LiveTalking needs a WebRTC session before /human works, so speaking an approved reply is
    only possible while a viewer is connected. There is, however, **no endpoint that lists
    sessions**: this polls GET /api/sessions, which no LiveTalking build serves (the string
    appears nowhere in its source), so it returns None in practice. It is kept because it
    costs one request and would start working if upstream ever adds the route.

    Real sources of a sessionid, in the order callers should prefer them:
      1. the dashboard, which captures it from the /offer response passing through its
         signalling proxy (`server.live_session()`);
      2. LIVETALKING_SESSIONID in the environment, for the CLI;
      3. this lookup.
    """
    env = os.getenv("LIVETALKING_SESSIONID")
    if env:
        return env
    try:
        req = urllib.request.Request(f"{LIVETALKING}/api/sessions", method="GET")
        with urllib.request.urlopen(req, timeout=3) as r:
            data = json.loads(r.read())
        for key in ("sessions", "data", "items"):
            if isinstance(data.get(key), list) and data[key]:
                first = data[key][0]
                return first if isinstance(first, str) else first.get("sessionid")
    except Exception:
        pass
    return None


def speak(text: str, sessionid: str) -> tuple[bool, str]:
    body = json.dumps({"sessionid": sessionid, "text": text,
                       "type": "echo", "interrupt": True}).encode()
    req = urllib.request.Request(f"{LIVETALKING}/human", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return True, r.read().decode()
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def decide(kol_id: str, rid: str, action: str, *, final_text: str | None = None,
           reviewer: str = "human", note: str = "",
           sessionid: str | None = None) -> dict:
    """Record an approve/reject/edit decision. Speaking is opt-in and never automatic."""
    items = {r["id"]: r for r in load_all(kol_id)}
    if rid not in items:
        raise KeyError(f"unknown draft {rid}")
    cur = items[rid]

    rec = {"id": rid, "kol_id": kol_id, "decided": time.time(), "reviewer": reviewer,
           "note": note}
    if action == "reject":
        rec["status"] = STATUS_REJECTED
        _append(kol_id, rec)
        return {**cur, **rec}

    if action not in ("approve", "edit"):
        raise ValueError(f"bad action {action}")

    text = (final_text if final_text is not None else cur.get("draft", "")).strip()
    if not text:
        raise ValueError("nothing to approve — provide text")

    # An edited reply is re-checked: a human can paste in a price by accident too.
    from persona_brain import check_reply
    violations = check_reply(cur.get("follower", ""), text)
    if violations:
        rec.update(status=STATUS_BLOCKED, violations=violations, final_text=text)
        _append(kol_id, rec)
        return {**cur, **rec}

    rec.update(status=STATUS_APPROVED, final_text=text, violations=[], edited=action == "edit")
    if sessionid:
        ok, detail = speak(text, sessionid)
        rec["spoken"] = ok
        rec["speak_detail"] = detail
    _append(kol_id, rec)
    return {**cur, **rec}


def stats(kol_id: str) -> dict:
    items = load_all(kol_id)
    out = {"total": len(items), STATUS_PENDING: 0, STATUS_APPROVED: 0,
           STATUS_REJECTED: 0, STATUS_BLOCKED: 0}
    for r in items:
        out[r.get("status", STATUS_PENDING)] = out.get(r.get("status", STATUS_PENDING), 0) + 1
    return out


# ------------------------------------------------------------------------- CLI

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("draft", help="generate and park a draft reply")
    d.add_argument("kol_id"); d.add_argument("message")

    l = sub.add_parser("list", help="show the queue")
    l.add_argument("kol_id")
    l.add_argument("--status", default=None)

    a = sub.add_parser("approve", help="approve a draft (optionally speak it)")
    a.add_argument("kol_id"); a.add_argument("rid")
    a.add_argument("--text", default=None, help="edited text to approve instead of the draft")
    a.add_argument("--speak", action="store_true", help="also speak it via LiveTalking")
    a.add_argument("--sessionid", default=None,
                   help="avatar session to speak into. There is no endpoint that lists "
                        "sessions, so pass it explicitly (the /demo page logs it on Connect) "
                        "or set LIVETALKING_SESSIONID")
    a.add_argument("--reviewer", default=os.getenv("USERNAME", "human"))

    r = sub.add_parser("reject", help="reject a draft")
    r.add_argument("kol_id"); r.add_argument("rid"); r.add_argument("--note", default="")

    args = ap.parse_args()

    if args.cmd == "draft":
        rec = create_draft(args.kol_id, args.message)
        print(f"[{rec['status']}] {rec['id']}")
        print(f"  follower: {rec['follower']}")
        print(f"  draft   : {rec.get('draft','')}")
        if rec.get("violations"):
            print(f"  BLOCKED : {rec['violations']} — needs a human rewrite")
        print(f"  policy  : {rec['policy_mode']} (nothing is sent until approved)")
        return 0

    if args.cmd == "list":
        items = load_all(args.kol_id)
        if args.status:
            items = [i for i in items if i.get("status") == args.status]
        print(f"{stats(args.kol_id)}\n")
        for r in items:
            print(f"[{r.get('status','?'):9s}] {r['id']}  {r.get('follower','')[:40]}")
            print(f"            -> {(r.get('final_text') or r.get('draft') or '')[:78]}")
            if r.get("violations"):
                print(f"            !! {r['violations']}")
        return 0

    if args.cmd == "approve":
        sid = (args.sessionid or _livetalking_session()) if args.speak else None
        if args.speak and not sid:
            print("no avatar session — approving without speaking.\n"
                  "  LiveTalking serves no endpoint that lists sessions, so it cannot be\n"
                  "  discovered: open /demo, press Connect, and pass the id it logs via\n"
                  "  --sessionid (or set LIVETALKING_SESSIONID).")
        rec = decide(args.kol_id, args.rid,
                     "edit" if args.text is not None else "approve",
                     final_text=args.text, reviewer=args.reviewer, sessionid=sid)
        print(f"[{rec['status']}] {rec['id']}: {rec.get('final_text','')}")
        if rec.get("violations"):
            print(f"  BLOCKED: {rec['violations']}")
        if "spoken" in rec:
            print(f"  spoken: {rec['spoken']} ({rec.get('speak_detail','')})")
        return 0 if rec["status"] == STATUS_APPROVED else 1

    if args.cmd == "reject":
        rec = decide(args.kol_id, args.rid, "reject", note=args.note)
        print(f"[{rec['status']}] {rec['id']}")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
