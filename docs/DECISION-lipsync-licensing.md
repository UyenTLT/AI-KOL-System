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

## Systemic risk — four for four, and no longer only the avatar layer

| Component | What it does | Constraint | Documented remedy |
|---|---|---|---|
| **LiveTalking** | realtime serving + rendering | Apache-2.0, but README §7 requires its watermark on published video | accept it / commercial edition / change engine |
| **wav2lip** | lip-sync model (in use now) | published weights are **research-licensed** | switch to MuseTalk — LiveTalking already supports it, so a flag change |
| **LivePortrait** | facial motion (blink, head turn) — *evaluated, not yet adopted* | MIT code, but bundled **InsightFace detection models are non-commercial research only** | its LICENSE states the fix: replace InsightFace's detector. The community fork **ComfyUI-LivePortraitKJ** already substitutes **MediaPipe**, "ensuring the license remains under MIT and Apache 2.0" |
| **IndexTTS-2** | emotion-controllable TTS — *evaluated 2026-08-04, rejected on licence* | not Apache-2.0 as its repo first suggests: the **bilibili Model Use License Agreement** requires prior **written authorisation for commercial use**, and forbids using it to improve any other commercial AI model | either negotiate terms (`indexspeech@bilibili.com`) or use **CosyVoice 2**, which is Apache-2.0 for both code and weights and also offers instruction-based emotion control |

**Update (2026-08-04):** the pattern is not confined to the avatar layer. Looking for a fix to
a *voice* problem — the cloned voice sounding robotic — turned up the same thing on the first
serious candidate. IndexTTS-2 is the strongest emotion-control engine in this repo's own
survey, and it is the one that cannot be used commercially without a signed agreement.

Four components examined, four restrictions — and then a fifth, MuseTalk, that came back clean
on 2026-08-05 (see below). So the rule is not "everything in this space is restricted"; it is
that restriction is common enough to be worth checking every time, and that the check
occasionally pays out with a component that has no strings at all.

The important read is not that any one of them is a problem — each has a known, cheap-ish fix —
but that **this is normal for this class of model**, so it should be treated as a standing
checklist item rather than a surprise:

- **Check the licence before adopting a component**, not after building on it. That is why
  LivePortrait was licence-checked before its ~2 GB of weights were downloaded, why the
  MuseTalk performance test is sequenced after legal, not before, and why IndexTTS-2 was
  screened out before anything of its was installed.
- **A repo carrying an Apache-2.0 LICENSE file is not the answer on its own.** IndexTTS-2 ships
  one and still restricts commercial use through a separate model agreement; LiveTalking ships
  one and still asks for a watermark in its README. Both times the binding term lived outside
  the file named LICENSE. Read the model card and the README, not just the licence file.
- **Research/internal use is a different question from publishing.** Everything here is fine for
  R&D and internal demos, which is what the current build is. The constraints bite at launch.
- **Budget one swap per component.** MuseTalk for wav2lip; MediaPipe for InsightFace; CosyVoice 2
  for IndexTTS-2; a decision for the watermark. None is large individually; together they are a
  work item worth naming.

## MuseTalk, verified 2026-08-05 — the pattern breaks

The memo above recommended MuseTalk as the cheap lever for wav2lip's research-licensed
weights, but had never checked it. It has now been checked the same way as everything else:
clone the code, read the actual files, follow the weight downloads, and check each dependency
in turn. **It is clean the whole way down** — the first component in this project of which
that is true.

| | Licence | Source |
|---|---|---|
| MuseTalk code | **MIT** — "no limitation for both academic and commercial usage" | its `LICENSE` and README §Disclaimer/License |
| MuseTalk weights | **"available for any purpose, even commercially"** | README §Disclaimer/License, item 2 |
| `sd-vae-ft-mse` (Stability) | MIT | its model card |
| `whisper-tiny` (OpenAI) | MIT | its model card |
| `DWPose` (IDEA-Research) | Apache-2.0 | its repo |
| `resnet18` (torchvision) | BSD | pytorch.org |

The dependency list is the part that mattered. LivePortrait looked MIT until its bundled
InsightFace detector turned out to be non-commercial, and MuseTalk's README carries the same
warning in the abstract — "other open-source models used must comply with their license". Here
each one actually resolves permissive.

One genuine exclusion, and it is narrow: **their test data** is "collected from internet,
available for non-commercial research purposes only". That is the sample videos, not the model.

**It is also trainable.** `train.py`, `train.sh`, and a four-file config set for preprocessing,
syncnet, stage 1 and stage 2. That matters beyond convenience: weights trained on footage we
own are unambiguously ours, which removes the licence question rather than answering it.

### What this changes

- **wav2lip's research licence stops being a launch blocker.** LiveTalking already registers
  `musetalk` alongside `wav2lip`, and the launcher already exposes `-Model`, so the swap is a
  flag rather than a project. Action 3 in the table above ("validate `-Model musetalk` on this
  GPU") is now unblocked — it was sequenced after legal, and legal's answer is in the files.
- **It runs on this hardware.** Upstream tested inference on a 4 GB RTX 3050 Ti laptop; this
  box has 12 GB.
- **Training on this box is a separate question.** MuseTalk's stage-2 config uses
  `gradient_accumulation_steps: 8` at fp32, which is written for multi-GPU
  (`num_processes: 2`). Fine-tuning would need its own VRAM measurement before being promised.

### LatentSync, checked at the same time

Apache-2.0 code with `train_syncnet.py` and `train_unet.py`, from ByteDance. Better lip-sync
quality in published comparisons, and a legitimate second candidate.

**Ruled out on hardware, not licence.** Its own README states stage-1 training needs 23 GB and
stage-2 needs 30 GB, with an "efficient" stage-2 at 20 GB aimed at a 3090. This machine has
12 GB, so training it here is not possible; inference at 8 GB (v1.5) would fit, but a model we
cannot retrain leaves us depending on someone else's weights, which is the position we are
trying to leave.

## Singing — RVC checked 2026-08-07, and it is clean

Song requests on the live stream need a singing voice, which no TTS engine here can produce
(measured: asking CosyVoice 2 to sing *narrows* its pitch range from 17.50 semitones to 10.06).
The chosen design is Suno for the music and RVC to convert the vocal to Sofia's timbre, so RVC
was licence-checked the same way as everything else — code, then every component under it.

| | Licence |
|---|---|
| RVC (`RVC-Project/Retrieval-based-Voice-Conversion-WebUI`) | **MIT** |
| ContentVec (content feature extractor) | **MIT** |
| RMVPE (pitch extraction) | **Apache-2.0** |
| Base model training data | VCTK, ~50 h, stated by the project as free of copyright concerns |

Second component in this project to come back clean the whole way down, after MuseTalk. The
profile already asserted "RVC is MIT-style — clean"; that was an unverified note in a JSON file,
and this is the check behind it.

## Suno — the constraint moved from licence to access

Suno's terms *do* permit commercial use, but not in the shape the earlier assumption had:

- **Paid plan required.** Pro or Premier grants commercial exploitation; the free tier does not.
- **Ownership was removed from the terms in 2026.** Following major-label litigation and a
  subsequent licensing partnership with Warner Music Group, the rewritten terms no longer give
  the user ownership: Suno remains the author, and the subscriber holds a perpetual licence to
  exploit the output commercially. Usable, but it is a licence, not a title — worth legal
  reading it before it sits under a commercial KOL.
- **No copyright vests in the output.** Neither Suno nor the US Copyright Office treats
  AI-generated audio as copyrightable in its raw form, so the track cannot be defended as ours.

**The blocker is access, not terms.** As of July 2026 Suno has no self-serve public API. It has
announced a curated partner programme with an application form. The third-party "Suno API"
wrappers drive the consumer web app with a session cookie, which is fragile and sits against
Suno's own terms — not a foundation for a commercial pipeline.

**Consequence for the design:** song requests cannot be generated on demand mid-stream anyway.
Generation takes tens of seconds to minutes against a 6–9 s conversational turn, so the pipeline
wants a **pre-built library** regardless: songs made ahead of time, converted to Sofia's voice
once, and chosen at stream time. That design needs no API at all, which turns the access
blocker from a stop into a scheduling question.

## Scope note

Our KOLs target Taiwan, the Americas and Europe (Instagram, TikTok, YouTube). The platforms
named in LiveTalking's Statement are all Chinese (Bilibili, WeChat Channels, Douyin), and the
wording is "such as" — non-exhaustive. That ambiguity is precisely why action 1 exists: one
email to the author is far cheaper than a legal opinion on the phrase "such as".
