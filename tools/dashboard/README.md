# dashboard — live pipeline tracker, data browser, and avatar demo

One local page showing where every KOL actually is, letting you inspect the real assets,
and driving the live avatar. Stdlib only, no new dependencies.

```bash
python tools/dashboard/server.py            # http://127.0.0.1:8770
python tools/dashboard/server.py --port 9000 --host 0.0.0.0   # expose on the LAN
```

Any interpreter works (repo `.venv`, either engine venv, or system python).

| Route | What it is |
|---|---|
| `/` | Dashboard — pipeline stages, overview counts, service + GPU health, KOL roster |
| `/kol/<id>` | **Data browser** — reference clip, training clips with playable audio + transcripts, images, videos |
| `/demo` | **Live avatar demo** — connect, type text, watch it speak in the cloned voice |
| `/replies` | **Approve-before-send queue** — the AI drafts, a human approves, edits or rejects |
| `/api/state` | Whole state as JSON |
| `/api/kol/<id>` | One KOL's detail as JSON |
| `/api/reply/queue?kol=<id>` | Queue state as JSON |
| `/media?path=…` | Read-only media, restricted to the repo (see security note) |

## Reply queue (`/replies`)

Every profile carries `comment_policy_mode: "suggest"` — the AI drafts, a human approves,
only then does anything reach a follower. Nothing enforced that until now: the chat path
spoke the model's output the instant it was generated. This is the enforcement.

Paste what a follower said → **Draft reply** → review → *Approve*, *Approve & speak*, or
*Reject*. Approved text can be edited first.

Why it matters, measured rather than assumed: `qwen2.5:7b`, given the rules explicitly in its
prompt, still denied being AI, invented a price of 「二百九十九美元」, offered to negotiate a
deal privately, and fell for an "ignore all previous instructions" jailbreak. Intent
directives plus code-level guards took that to zero violations — but "zero on eight tests" is
not a licence to auto-post.

**An edited reply is re-checked.** A human can paste in a price just as easily as a model can
invent one; verified that an edit containing 「只要 $299，link in bio!」 is blocked, not sent.
The link guard distinguishes *claiming* a link exists from promising to look one up
(「我會去查一下價格和連結」 passes — it is the honest answer).

Storage is one append-only JSONL per KOL (`kols/<id>/replies/queue.jsonl`): auditable,
diffable, no database, survives a crash mid-review. It is gitignored — the decision trail
belongs on the machine that made the decisions, not in the repo.

CLI equivalent, for scripting or a cron-driven inbox:

```bash
python tools/dashboard/reply_queue.py draft   lena-chen "這罐多少錢？"
python tools/dashboard/reply_queue.py list    lena-chen
python tools/dashboard/reply_queue.py approve lena-chen <id> --speak
```

"Approve & speak" needs a live avatar session — open `/demo` and press Connect first,
otherwise it approves without speaking and tells you so.

## Live demo (`/demo`)

Press **Connect**, then type and press **Speak**. LiveTalking's `/human` endpoint needs a
`sessionid` that only exists after a WebRTC handshake, so the page performs that handshake in
the browser — the same flow `tools/livetalking/verify_lipsync.py` automates headlessly.

Signalling is proxied through this server (`/lt/offer`, `/lt/human`, `/lt/interrupt_talk`) so
the page only ever talks to one origin; the audio/video itself still flows peer-to-peer from
LiveTalking. Verified working through the proxy: 283 video + 562 audio frames in 10 s.

Both services must be running — the page shows the exact commands if either is down. Remember
**GPT-SoVITS api_v2 is the cloned voice**; without it the avatar speaks in a generic timbre.

The preset lines deliberately mix ZH and EN in one sentence, which exercises the
per-segment language detection patched into `tts/sovits.py`.

## Data browser (`/kol/<id>`)

Click any KOL name in the roster. Shows the reference clip (the prompt GPT-SoVITS speaks
from) plus **24 training clips sampled evenly across the whole corpus** — not the first 24 —
so the preview reflects both languages and the full range of utterances. Each clip is
playable with its exact transcript, which is the fastest way to spot a bad dataset.

## Security note

`/media` only serves files that are **inside the repo** and have an image/audio/video
extension. Path traversal (`../../…`) and source files are refused with 404 — verified.
It is still a local-only tool: think before binding it to `0.0.0.0` on an untrusted network.

## What it shows

| Section | Source of truth |
|---|---|
| **Pipeline** — 4 stages (persona → images → voice → lip-sync) | derived from the data below |
| **Overview** — persona / image / dataset / fine-tuned counts | `kols/index.json` + each `profile.json` |
| **Services** — GPT-SoVITS :9880, LiveTalking :8010, Ollama :11434 | live HTTP probe each request |
| **GPU** — VRAM used/free, util, temp | `nvidia-smi` |
| **KOL roster** — images, videos, voice status, clips, minutes, ZH/EN split, weight file | `voice/dataset/<id>.list`, `manifest.json`, `GPT-SoVITS/{SoVITS,GPT}_weights_*` |
| **Dataset QC** — rejected clips by reason | `voice/dataset/manifest.json → totals.rejected_by_reason` |

Everything is re-read **on every request** — nothing is cached or hardcoded, so the page
cannot drift from reality. The page self-refreshes every 15 s.

`GET /api/state` returns the identical data as JSON, so scripts and CI can consume it:

```bash
curl -s http://127.0.0.1:8770/api/state | python -c "import json,sys; d=json.load(sys.stdin); print(d['summary'])"
```

## Reading the voice column

| Badge | Meaning |
|---|---|
| `fine-tuned` | both a SoVITS `.pth` and a GPT `.ckpt` exist for that KOL — a usable cloned voice |
| `dataset ready` | clips + `.list` exist but no trained weights yet → run `train_gptsovits.py` |
| `planned` | `ai_assets.voice` is configured but there is no dataset yet |
| `—` | nothing set up |

Weight discovery matches on the file naming both trainers use (`<exp>_e8_s496.pth`,
`<exp>-e12.ckpt`) and picks the newest per KOL, so it keeps working after a retrain.

## Notes

- Ollama shows `not running` until you start it; the LLM-brain stage isn't wired up yet.
- Minutes come from a manifest. A dataset built outside `crawl.py`/`bootstrap_timbre.py`
  will show clips with `?` minutes rather than a wrong number.
- Read-only: the dashboard never writes to `kols/` or touches the engines.
