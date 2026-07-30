# AI-KOL System — Detailed Project Report

*Consolidated from a full read of `kols/`, `tools/`, `research/local-ai-companion/`, `docs/`, and
`.claude/`. Status as of 2026-07-15.*

---

## 1. Executive Summary

**Buildup_KOL / AI-KOL-System** is a system for designing and operating **virtual influencers
(AI KOLs)** — fictional characters that look like real people, post content, read comments, and
(eventually) sell products and go live. Today the project is three things at once:

1. **A persona database** (`kols/`) — 10 fully-designed characters, the core asset.
2. **A working local content toolkit** (`tools/`) — turns a persona + photos into vertical vlogs
   and a "type → the KOL speaks" web app, 100% local and free on a Mac.
3. **A research + runbook layer** (`research/`, `CUDA_SETUP.md`) — a fully-planned upgrade path from
   static personas to realistic images, natural per-character voice, a real-time talking digital
   human, and an LLM "brain" for conversation and comment handling.

**Where it stands:** the *design and planning* are mature and thorough; the *content tooling* works
locally; but everything that makes a KOL feel truly real — locked face identity, natural voice,
lip-synced/real-time video — is **CUDA-only and not yet executed**. The single biggest blocker is
**access to an NVIDIA GPU machine**. The second is **completing the assets** for the flagship
characters (images, voice, product catalogue) so one KOL can be proven end-to-end.

---

## 2. What the Project Is (Overview & Architecture)

### 2.1 The hub-and-spoke model

Everything revolves around `kols/<id>/profile.json` as the **single source of truth**:

```
                         kols/<id>/profile.json  (schema-validated)
                          + character.md, content_style.md
                                     │
        ┌───────────────┬────────────┼───────────────┬───────────────────┐
   kol-builder      tools/        research/        .claude/            future
   skill (authors)  (reads it)    (defines "why")  agents+skill        companion/
   Higgsfield MCP   vlog/talk/tts                                      (Phase 1 chat)
```

- The **kol-builder skill** (+ Higgsfield MCP) authors personas and seed images into `kols/`.
- The **tools** read the same profile (`identity.languages` → voice, `persona` → script,
  `images/` → frames).
- The **research docs** define the interactive-companion architecture the tools will grow into.

### 2.2 Repository layout

```
Buildup_KOL/
├── kols/                 # CORE persona DB: index.json, schema.json, 10 KOL dirs
├── tools/
│   ├── vlog_app.py       # local photo → 9:16 vlog (Ollama + say + ffmpeg)     ✅ works
│   ├── talking_web/      # "type → KOL speaks" web app (echo mode)             ✅ works
│   └── tts_train/        # GPT-SoVITS per-KOL voice fine-tune (client+prep)    ⚠️ CUDA, untested
├── research/local-ai-companion/   # 12 decision docs (01–12) + references
├── docs/                 # KOL standards (video ref, photo standard, male Real-IP, style system)
├── reports/              # PDF reports (gitignored)
├── CUDA_SETUP.md         # one-file full-system GPU runbook (untested)
└── .claude/              # kol-builder skill, 3 subagents, settings (Higgsfield MCP + hook)
```

### 2.3 The three-layer product vision

| Layer | What it does | State |
|---|---|---|
| **Content** | Photoreal images + short videos of each KOL | Images: partial; video: 1 KOL only |
| **Voice** | A natural, consistent voice per KOL (ZH/EN) | Designed; needs CUDA fine-tune |
| **Interaction** | LLM persona brain, comment read-and-act, live digital human | Designed; not built |

---

## 3. Current State — What Is Built

### 3.1 KOL roster (10 characters)

| id | Flavor | Commerce role | Markets | Status | Images | Video |
|---|---|---|---|---|---|---|
| sofia-vargas | Latina lifestyle | R0/R1 | LatAm+US | **active** | ✅ Soul v1–v3 | ✅ **14-shot self-intro** |
| xie-yizhen | Film-candid new-mom (F6-adj.) | — | Taiwan | **active** | ✅ extensive | — |
| xiang-xiang | Wine-PR insider (real-person) | F&B soft | Taiwan | photos_collected | ⚠️ mixed, Soul pending | — |
| brooke-sinclair | Confident it-girl | — | US | draft | ✅ Soul v3 ready | — |
| chloe-lin | **F1** 純欲 | R1 (proposed) | TW+US | draft | ✗ | — |
| sienna-lai | **F2** Cute×Elegant | R1 (proposed) | TW+N.America | draft | ✗ | — |
| mika-tran | **F3** Real-IP Sexy | R2 (proposed) | US | draft | ✗ | — |
| jax-calloway | **F4** Male Real-IP | — | US | draft | ✗ | — |
| **lena-chen** | **F5×F1** 甜妹 | **R2 seller (flagship)** | TW+US+EU | draft | 1 seed | — |
| **lin-wanqing** | **F6** 溫柔知性 | **R1 soft-seller** | TW+JP | draft | 5 seed | — |

Only **sofia-vargas** has a finished video (made with Seedance + ElevenLabs). `xie-yizhen` and
`brooke-sinclair` have rich image sets. The rest are persona-complete but asset-thin.

### 3.2 The persona schema

`schema.json` (draft-07) requires 6 blocks — `id, meta, identity, persona, content, social` — plus
optional `commerce` and `ai_assets`, and free-form `ai_prompts`. Highlights:
- **`commerce`** encodes the seller role (`R0–R3`), product-KB path, and comment-automation mode.
- **`ai_assets`** anchors face + voice identity (Soul/LoRA/Element IDs; nested `voice{}` with
  GPT-SoVITS weights + reference). `additionalProperties:true`, so KOLs freely version sub-objects.

### 3.3 The Style System (docs/04) — two orthogonal axes

- **Axis 1 — Flavor (look/feel):** F1 純欲 · F2 Cute×Elegant · F3 Real-IP Sexy · F4 Male Real-IP ·
  F5 甜妹 Pure-Cute · F6 溫柔知性 Feminine-Elegant. Invariant: adult, mainstream, never NSFW.
- **Axis 2 — Commerce Role (how hard she sells):** R0 Influencer → R1 Soft → R2 Active/KOC → R3 Live-closer.
- **Any Flavor × any Role** is a valid blend; the comment-reading loop is the selling engine.
  `lena-chen` is the designated **reference build** to clone for other markets.

### 3.4 Working local tools

- **`vlog_app.py`** — topic → LLM script (Ollama qwen2.5:7b, Traditional Chinese) → macOS `say`
  voiceover → Ken-Burns + burned captions (Pillow/ffmpeg) → concatenated 9:16 MP4. Verified working.
- **`talking_web/`** — a local browser app (`http://localhost:7860`): pick a KOL, type text, it
  returns a clip of the character "speaking" it (echo mode). Verified working; `generate()` is a
  swap-in point for real lip-sync later.

### 3.5 Research & decision layer (mature)

Twelve numbered docs settle the architecture and every stack choice:
- **Phase model:** Phase 1 text chat → Phase 2 voice → Phase 3 realtime avatar + livestream, built
  so 2/3 are *added modules*, not rewrites.
- **Local LLM:** Ollama, OpenAI-compatible streaming, default **Qwen2.5-14B-Instruct Q4_K_M**.
- **Voice:** CosyVoice2 (realtime) / GPT-SoVITS (fine-tune) + IndexTTS-2 / F5-TTS; RVC polish.
- **Avatar/lip-sync:** **LiveTalking** (Wav2Lip POC, MuseTalk for quality), ~91% feasibility, echo-mode POC in doc 05.
- **Images:** Flux.1-dev + character LoRA / PuLID / InstantID + ReActor; 4-layer "de-AI" recipe.
- **Comment loop (doc 11):** ingest (IG/YouTube first-party) → rule prefilter → Qwen2.5-3B JSON
  classifier → priority score → decision table → act, human-in-the-loop for money/DM/block.
- **Growth funnel (doc 12):** Reach → Engage → Read/Filter comments → Convert → Close (DM) → Retain.
- **Standards:** docs/02 "Film Candid" photo standard (Higgsfield Soul), docs/03 male Real-IP
  (Seedream + Reference Element), docs/01 a (now-stale) video pipeline reference.

---

## 4. The Plan — Execution Roadmap

### 4.1 Chosen bring-up order on the CUDA machine (from `CUDA_SETUP.md`)

1. Base + `nvidia-smi` + clone repo.
2. **LLM brain** (Ollama, fast GPU sanity check) → **Voice** (GPT-SoVITS fine-tune) → **Images**
   (Flux + character LoRA to lock faces).
3. **LiveTalking echo mode** → connect the fine-tuned voice → OBS/RTMP.
4. Wire tools to the real voice (`TTS_API`), then optional real-motion video (Wan/LTX).

### 4.2 Proposed milestones

| Horizon | Goal |
|---|---|
| **Now (unblock)** | Secure NVIDIA GPU (buy ≥24 GB, or rent cloud). Fix repo hygiene (below). |
| **Milestone 1** | Prove **lena-chen** end-to-end: character LoRA (locked face) → 15–25 images → GPT-SoVITS voice → vlog + talking-head with the real voice. |
| **Milestone 2** | Load a **real product catalogue** into `products.json`; run the comment read-and-act loop in `suggest` mode on one channel (IG or YouTube). |
| **Milestone 3** | Build **KOL #2 for Europe** (the biggest gap) + finish the 4 asset-less drafts. |
| **Milestone 4** | LiveTalking realtime digital human (Phase 3), livestream selling, AI-disclosure compliant. |

### 4.3 The commercial thesis (why this can attract customers)

Trust is the fuel: a KOL that will say "this one is not worth it" makes her recommendations
believable; the open-question CTA turns viewers into commenters; the comment loop filters buy-intent
and funnels it into DM soft-close; happy customers become UGC that feeds the top of the funnel and
lowers CAC. Selling lives in the comment/DM layer, not the post.

---

## 5. Outstanding Difficulties (Open Issues)

### 5.1 Hardware — the primary blocker
- Apple Silicon **cannot run CUDA**. Voice fine-tuning, character-LoRA training, lip-sync, real-motion
  video, and the real-time avatar are all **CUDA-only** → need an NVIDIA box (≥24 GB VRAM ideal).
- **VRAM contention:** LLM (14B) + lip-sync + TTS on one card competes; must stage or use 2 GPUs.

### 5.2 Asset completeness
- **4 KOLs have no images at all** (chloe, sienna, mika, jax).
- **Flagship lena-chen is thin:** 1 seed image; `soul_id`, `voice_id`, `element_id` all null; and its
  `products.json` is a **template with null prices/links** — so the seller loop has nothing to sell yet.
- Only 1 KOL (sofia) has finished video.

### 5.3 Identity consistency (quality ceiling)
- SDXL/zero-shot gives a slightly different face each render → needs **character LoRA / IP-Adapter**
  to lock identity (CUDA). Tension: lock too hard → "AI look"; loosen → inconsistent.
- Voice similarity has a zero-shot ceiling → **fine-tuning** (GPT-SoVITS) is required for a locked voice.

### 5.4 Platform, legal & compliance
- **TikTok has no official comment/live-chat API** → automation there risks ToS bans (disabled by default). Only IG Graph + YouTube Live are first-party-safe.
- **AI-disclosure law:** China (from 2026/06) mandates on-screen "AI digital-human host" labels;
  four verticals (medical-aesthetics, education, finance, healthcare) are **banned** from AI livestream
  (from 2026/05). EU AI Act requires transparency. Must be handled before Phase 3 live.
- **Human-in-the-loop** required for money/links/blocks until metrics justify `auto`.

### 5.5 Unresolved product/architecture decisions (carried in docs 02/03/11)
- Single shared LLM for all personas vs one deployment per KOL.
- The **content-boundary** policy (how much "flirtatious/sexy" latitude) — deliberately left blank.
- Product-KB source/format for price/link replies.
- Pace of opening comment automation from `suggest` → `auto`.

### 5.6 Data-integrity issues found (should be cleaned up)
- **`xiang-xiang`** violates the schema (`identity` has **no `handle`, no `origin`**) and adds
  non-schema blocks (`meta.type`, `career{}`, `birth_year`). Its `ai_assets` says Soul "pending" but
  generated images already exist on disk — the record is out of sync.
- **`jax-calloway` (male)** has no `meta.gender` in his profile (only in `index.json`); the schema
  **defaults gender to female**, so the profile alone is wrong.
- **Flavor encoding is inconsistent:** mika/jax use a non-schema `meta.flavor`; chloe/sienna/lena/lin
  correctly use `meta.tags: flavor:Fx`.
- **`index.json` drifts from profiles:** xiang-xiang handle (`null` vs `@daphne428`), differing
  ethnicity strings, and `role`/`markets` present only for lena & lin.
- **`docs/01` is stale:** it mandates a `generation{}` block and a LoRA/CosyVoice pipeline **no
  profile uses**; sofia's real video used Seedance + ElevenLabs. It also misspells Xie's name.
- **Voice-engine drift:** schema comment names GPT-SoVITS as production, but lena/lin specify
  IndexTTS-2 + CosyVoice2.

### 5.7 Repo hygiene / new-developer traps
- **No dependency manifest** (`requirements.txt` / `pyproject.toml`); Python 3.10, Pillow,
  faster-whisper, ffmpeg only mentioned in prose.
- **`sd-venv` landmine:** `talking_web/server.py` docstring says run with `./sd-venv/bin/python`, but
  **no `sd-venv` exists in the repo** (it was a local prototype venv) — a cloner following it fails.
- **Hardcoded macOS path** `/System/Library/Fonts/PingFang.ttc` (no fallback) breaks off-Mac.
- **`.claude/settings.json` hook** hardcodes a Linux path `cd /home/user/Buildup_KOL` and its matcher
  uses `mcp__higgsfield__*` while the allowlist uses `mcp__higgs__*` — inconsistent, and it auto-commits/pushes.
- **Repo-name mismatch:** `CUDA_SETUP.md` clones `AI-KOL-System` while the folder/README is `Buildup_KOL`.
- **Untested-by-authors:** all `tts_train/` code and `CUDA_SETUP.md` are self-declared unverified;
  LiveTalking integration is documentation only (no code yet).

### 5.8 Market coverage
- **Europe is the biggest hole.** docs/04 proposed a dedicated Euro-Asian F6 KOL for Europe, but the
  F6 slot went to `lin-wanqing` (Taiwan/Japan). `lena-chen` is tagged `market:europe` but only touches
  it via "buying trips" with basic French — no native European-language KOL exists.

---

## 6. Development Proposals

### 6.1 Immediate (unblock + hygiene) — low cost, high leverage
1. **Get the GPU** (buy ≥24 GB NVIDIA for long-term, or rent cloud for the POC) — unblocks 5 of the 6 hardest items.
2. **Add `requirements.txt`** and a documented venv; remove the `sd-venv` reference; make the font
   path configurable with a fallback; fix/neutralize the `.claude` hook path + MCP-prefix mismatch;
   reconcile the repo name.
3. **Run a data-integrity pass**: fix xiang-xiang's schema violations, add `meta.gender` to jax,
   standardize flavor encoding to `meta.tags`, sync `index.json` to profiles, and either update or
   retire the stale `docs/01`. Consider adding `additionalProperties:false` + a CI JSON-validation step.

### 6.2 Prove the flagship end-to-end (Milestone 1)
4. On the GPU: train a **character LoRA** for `lena-chen` (lock the face) → generate the full seed set →
   fine-tune her **GPT-SoVITS voice** → regenerate vlog + talking-head using the real voice
   (`TTS_API`). This validates the whole content+voice pipeline on one character.
5. **Fill `lena-chen/products.json`** with a real catalogue so the R2 comment loop and DM soft-close work.

### 6.3 Build the interactive layer (Phase 1 → comment loop)
6. Implement the `companion/` Phase-1 chat exactly as specified in doc 03 (persona→prompt,
   session/context, Orchestrator API) — it's implementation-ready.
7. Stand up the **comment read-and-act loop** (doc 11) in `suggest` mode on IG or YouTube (first-party
   only), with human review for money/DM/block. Measure classifier accuracy before opening `auto`.

### 6.4 Close the gaps
8. **Build the Europe KOL** (Euro-Asian F6, EN + one European language, R1/R2 skincare) and finish the
   four asset-less drafts (chloe, sienna, mika, jax) once the image pipeline is on GPU.
9. **Bump statuses** to match reality (e.g. brooke has a ready Soul but is still `draft`).

### 6.5 Longer-term (Phase 3)
10. Stand up **LiveTalking** echo-mode POC (doc 05), then real-time selling livestreams; add the
    **Action-Routing** layer (intent → avatar behavior) that the current architecture lacks.
11. **Codify a compliance policy** (AI-disclosure labels, banned verticals, platform strategy) before
    any public live operation.

### 6.6 Recommended priority order

```
GPU access  →  repo hygiene + data-integrity  →  lena-chen end-to-end (face LoRA + voice)
→  real product catalogue  →  comment loop (suggest mode)  →  Europe KOL + finish drafts
→  LiveTalking realtime + compliance  →  scale roster
```

---

## 7. Risk & Compliance Summary

| Risk | Mitigation |
|---|---|
| No CUDA → core features blocked | Buy/rent NVIDIA GPU (the gating decision) |
| AI-disclosure law (CN 2026/06, EU AI Act) | Label AI hosts; avoid banned verticals; policy before live |
| Platform ToS (esp. TikTok) | First-party APIs only (IG/YouTube); TikTok automation off |
| Likeness/voice rights | Original identities only; never clone real people without consent |
| Auto-reply errors | Default `suggest` (human review); open `auto` only on proven metrics |
| Model/tooling churn (Flux→FLUX.2, etc.) | Pin versions; verify `CUDA_SETUP.md` against upstream on setup |

---

## 8. Bottom Line

The **hard thinking is done** — the persona system, style framework, tech-stack choices, and the
end-to-end runbook are all in place and coherent. The project is blocked less by unknowns than by two
concrete needs: **an NVIDIA GPU** to execute the CUDA-only pipeline, and **finishing the assets** for
one flagship character to prove the whole chain. Clear those two, run a data-integrity + repo-hygiene
pass, and the path from "static persona files" to "a real-looking, real-sounding KOL that reads
comments and sells" is well-defined and largely pre-designed.
