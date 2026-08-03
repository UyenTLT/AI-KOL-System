# Decision memo — lip-sync & portrait-animation licensing

**Question:** the lip-sync stack carries licence constraints. Which option do we take?

> **Update (2026-08-03) — this is a pattern, not a series of one-offs.** Every component
> examined in this layer so far carries a research or non-commercial restriction, each with a
> different documented remedy. That reframes the decision: it is not "fix this one tool", it is
> "budget for one licence swap per component in the avatar layer, and check before adopting the
> next one". See §*Systemic risk* below.

**Recommendation: accept the watermark for now, and treat the *model* licence as the real
commercial blocker — solved by switching model, not by paying for the wrapper.**

Not legal advice. The point of this memo is to make the trade-offs and the cheap next actions
explicit so legal is asked a narrow question instead of an open one.

---

## The two constraints are separate

They are easy to conflate, and conflating them leads to buying the wrong thing.

| | What it is | Where it comes from |
|---|---|---|
| **A · Watermark** | "LiveTalking" is drawn into avatar frames at build time and onto **every rendered output frame** | LiveTalking's `README-EN.md` §7 *Statement*: videos published to platforms "such as Bilibili, WeChat Channels, and Douyin" must include the LiveTalking watermark and logo |
| **B · Model licence** | **wav2lip's published weights are research-licensed** | the wav2lip project, not LiveTalking |

**This is the crux: paying LiveTalking for a commercial licence would remove A and leave B
untouched.** B is the constraint that actually blocks commercial publishing. Any option that
only addresses the watermark is poor value.

Worth noting on A: LiveTalking's actual `LICENSE` file is plain Apache-2.0, which does not
require a watermark on output. The requirement appears only in the README "Statement". Whether
a README statement forms part of the licence grant is exactly the narrow question for legal —
but we should behave as if it binds until told otherwise.

## Options

| | Option | Cost | Fixes A | Fixes B | Verdict |
|---|---|---|---|---|---|
| **A** | Keep the watermark, keep wav2lip | NT$0 | n/a — accepted | ✗ | **Chosen for now.** Correct for internal/demo use. |
| **B** | Buy LiveTalking's commercial edition | unknown | ✓ | ✗ | Poor value alone — leaves the harder constraint in place. |
| **C** | Switch the lip-sync model to MuseTalk | ~NT$0 | ✗ | likely ✓ | **The cheap lever.** LiveTalking already supports it, so it is a flag change. |
| **D** | Replace LiveTalking entirely | weeks | ✓ | ✓ | Only if A and C both fail. Loses the realtime/WebRTC layer we already have working. |

**Chosen: A now → C before any commercial publishing → B only if C proves impossible.**

## Why this is the best option

1. **It is the reversible one.** Accepting the watermark today forecloses nothing; stripping it
   or committing spend does. Under unresolved legal ambiguity, take the reversible path.
2. **The cost of A is genuinely near zero.** Measured: the watermark is 110×32 px on a 576×768
   frame — **0.80% of the frame**, drawn in low-contrast grey (128,128,128) at 0.3 font scale.
   At 1× it is easy to miss. Trading a breach of a stated condition for 0.8% of frame area is a
   bad risk/reward trade.
3. **C is a config change, not a project.** LiveTalking already registers `musetalk` and
   `ultralight` alongside `wav2lip`; our launcher already exposes `-Model`. Upstream benchmarks
   list MuseTalk at 42–45 fps on a 3080Ti/3090, so our RTX 5070 should sustain realtime.
   MuseTalk is also the higher-quality model, so this is an upgrade, not a compromise.
4. **It keeps the demo working today.** The pipeline is verified end-to-end right now; none of
   this needs to change for the current review.

## What we should NOT do

- **Do not patch the watermark out.** There is no official switch (checked: nothing in
  `config.py`, `config.yaml`, `app.py`, or `server/`), so removing it means editing against the
  author's stated request. It has deliberately been left in place.
- **Do not buy B expecting it to unblock launch.** It does not address wav2lip.

## Next actions (cheap, and they replace speculation with facts)

| # | Action | Owner | Why |
|---|---|---|---|
| 1 | Email `lipku@foxmail.com` (listed in their README) asking commercial terms | manager | Gives a real number instead of an assumption, and asks the author directly whether the Statement is intended to bind non-Chinese platforms |
| 2 | Have legal read MuseTalk's licence text | legal | If permissive, B is solved for ~NT$0 |
| 3 | If (2) is clear: validate `-Model musetalk` on this GPU — quality, fps, VRAM | me | ~half a day; proves the migration before it is needed |
| 4 | Keep the watermark on every output until (1) and (2) are answered | me | Already the case |
| 5 | Treat "check the licence" as a gate on adopting any new model in this layer | me | Three for three so far; cheaper as a habit than as a retrofit |
| 6 | If we adopt LivePortrait for facial motion: use the MediaPipe variant, not the stock InsightFace one | me | Keeps that component MIT/Apache instead of non-commercial |

## Systemic risk — three for three

| Component | What it does | Constraint | Documented remedy |
|---|---|---|---|
| **LiveTalking** | realtime serving + rendering | Apache-2.0, but README §7 requires its watermark on published video | accept it / commercial edition / change engine |
| **wav2lip** | lip-sync model (in use now) | published weights are **research-licensed** | switch to MuseTalk — LiveTalking already supports it, so a flag change |
| **LivePortrait** | facial motion (blink, head turn) — *evaluated, not yet adopted* | MIT code, but bundled **InsightFace detection models are non-commercial research only** | its LICENSE states the fix: replace InsightFace's detector. The community fork **ComfyUI-LivePortraitKJ** already substitutes **MediaPipe**, "ensuring the license remains under MIT and Apache 2.0" |

Three components examined, three restrictions. The important read is not that any one of them is
a problem — each has a known, cheap-ish fix — but that **this is normal for this class of model**,
so it should be treated as a standing checklist item rather than a surprise:

- **Check the licence before adopting a component**, not after building on it. That is why
  LivePortrait was licence-checked before its ~2 GB of weights were downloaded, and why the
  MuseTalk performance test is sequenced after legal, not before.
- **Research/internal use is a different question from publishing.** Everything here is fine for
  R&D and internal demos, which is what the current build is. The constraints bite at launch.
- **Budget one swap per component.** MuseTalk for wav2lip; MediaPipe for InsightFace; a decision
  for the watermark. None is large individually; together they are a work item worth naming.

## Scope note

Our KOLs target Taiwan, the Americas and Europe (Instagram, TikTok, YouTube). The platforms
named in LiveTalking's Statement are all Chinese (Bilibili, WeChat Channels, Douyin), and the
wording is "such as" — non-exhaustive. That ambiguity is precisely why action 1 exists: one
email to the author is far cheaper than a legal opinion on the phrase "such as".
