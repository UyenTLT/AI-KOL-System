# selftest — verification console

The dashboard answers *what state is the project in*. This answers a different question:
**does it actually still work, right now, on this machine.**

```bash
python tools/selftest/server.py            # http://127.0.0.1:8772
python tools/selftest/server.py --port 9100
python tools/selftest/server.py --cli      # headless; exits non-zero if any check fails
```

Stdlib only. Runs with the repo `.venv` (or any interpreter that can import the tools it
checks). The `--cli` mode is the CI-shaped one: one line per check, non-zero exit on failure.

## What it checks

Checks are split by what they cost. **Auto** ones are read-only and fast, so they run the
moment the page opens; **on demand** ones load a model or use the GPU, so they wait for a
button.

| Group | Check | When | Why it exists |
|---|---|---|---|
| Machine | GPU present, VRAM headroom | auto | The pipeline is GPU-bound; VRAM exhaustion is the usual first failure |
| Machine | GPT-SoVITS venv reaches CUDA | demand | A 50-series card is `sm_120`; the upstream `cu121` pin cannot run on it |
| Machine | LiveTalking venv reaches CUDA | demand | Same pin problem, second environment |
| Services | api_v2 · LiveTalking · Ollama | auto | Which of the four layers can run at all |
| Assets | Every profile parses | auto | `profile.json` drives voice, avatar and prompt — one break costs all three |
| Assets | Fine-tuned voices complete | auto | A voice needs **both** halves; one alone silently falls back to the base checkpoint |
| Assets | Avatar frame counts agree | auto | `full_imgs` / `face_imgs` / `coords.pkl` must match or the avatar renders garbage |
| Safety | Reply guard battery | auto | 13 cases: 9 that must block, 4 that must **not** |
| Safety | An edited reply is re-checked | auto | A human can paste in a price as easily as a model can invent one |
| Safety | Approve & speak reaches the avatar | auto | Approving is useless if the approved text never gets spoken |
| Voice | Speak a line in a cloned voice | demand | End of the voice pipeline: text in, her voice out — with a player to hear it |
| Voice | Speak it, then transcribe it back | demand | Catches audio that sounds fine but says the wrong words |
| Brain | Answer a follower in persona | demand | Layer four, on a local model |
| Brain | Resist a jailbreak | demand | The rule that matters most: she must never deny being AI |

Voice and brain checks take a character and a line of text, so you can probe a specific
voice or a specific awkward question rather than only the built-in default.

## It does not write to any audit log

The reply-queue check drives the real `reply_queue.decide()` enforcement path, but against a
temporary `REPO` — so the write path is genuinely exercised and no synthetic decision lands
in a character's append-only history. The check fails if anything leaks into the real
`kols/` tree.

## Reading a result

`ok` green, `warn` amber, `fail` red, `skip` grey. **Skip is not a pass** — it means a
prerequisite was missing (a service down, a venv absent), so the check could not form an
opinion. A run that is all-green because half of it skipped has proved very little; the
tally line separates them for exactly that reason.

The first run found two real bugs. Both are now fixed, and both fixes are asserted here so
they cannot regress silently:

- **`GET /api/sessions` does not exist.** `reply_queue._livetalking_session()` polled it to
  find a live avatar session, but no LiveTalking route serves it — the string appears nowhere
  in that codebase. So "Approve & speak" always degraded to approve-only, even with a viewer
  connected. It failed safe, which is why nobody noticed.
  **Fixed** by not discovering what was already known: every `/demo` connection negotiates its
  session through the dashboard's own signalling proxy, so `server._remember_session()` now
  captures the `sessionid` from the `/offer` response on its way past. The CLI gained
  `--sessionid` / `LIVETALKING_SESSIONID` for the same reason.
- **The deal-negotiation guard was Chinese-only.** Every other rule in `check_reply()` carried
  both an English and a Chinese pattern; `_NEGOTIATE_RE` carried only Chinese, so "DM me and we
  can negotiate a discount" passed unblocked. The gap sat exactly where it was least likely to
  be noticed — `sofia-vargas` is an English-only persona, so the rule meant to stop her
  negotiating privately never fired in her language.
  **Fixed** with English patterns anchored on the *offer to transact*, not on the words
  "discount" or "DM" alone. The battery now asserts both directions: "There was a discount last
  month" and "DM me if you have any questions" must still pass, or the fix has over-corrected
  into censoring ordinary community management.

## Adding a check

One entry in `CHECKS` and one function returning `ok()` / `warn()` / `bad()` / `skip()`.
Attach evidence with `rows=[[label, value], …]` (plus `head=[…]` for a real table) and
`audio="<file in the temp dir>"` for anything playable. The page renders both without
needing to know what the check was.
