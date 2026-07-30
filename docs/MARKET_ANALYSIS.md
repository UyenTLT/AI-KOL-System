# AI-KOL — Market Analysis & LLM Implementation Plan

*Market intelligence (China · Taiwan · Americas · Europe) with per-market strengths, weaknesses, and
mitigations, plus the concrete LLM models to implement. Compiled from web research on 2026-07-15.*

> **Reliability note.** Market-size and engagement figures are third-party estimates that vary widely
> by source and definition; each is flagged. Case GMV/earnings are mostly self-reported by
> creators/vendors or Chinese business media, not audited. Treat all numbers as **directional**.

---

## 1. Executive Summary

- **The category is real and growing fast.** Global virtual-influencer market ≈ **$8.3B (2025) → ~$11.7B
  (2026)**, with multi-firm 2032–34 forecasts of **$150–185B at ~40–45% CAGR** (wide spread — directional).
  North America (~43%) + Europe (~27%) are >70% of the 2024 base; China's *marketing* slice is smaller
  (~$0.7B in 2024) but the fastest-growing (~43% CAGR).
- **The strongest proof points are Chinese live-commerce:** Luo Yonghao's AI avatar sold **~¥55M
  (~$7.66M) in 6.5h** to 13M+ viewers (Baidu, Jun 2025); JD's digital humans drove **~¥14B GMV at 618
  2025, beating ~80% of human hosts at ~1/10 the cost**. In the West, **Neuro-sama** (AI VTuber) is
  Twitch's most-subscribed channel (~162K subs, est. ≥$400K/mo).
- **The universal constraint is disclosure.** Every target market is converging on **mandatory AI
  labeling** (China Sept 2025 + Feb/Jul 2026; EU AI Act Aug 2026; platform toggles everywhere). The
  winning posture is **openly-AI, compliance-first** — turn the label into part of the brand.
- **Positioning that survives all four markets:** a **brand-owned, transparent AI character** doing
  **beauty/lifestyle/fashion/FMCG** short-video + comment interaction, monetized at **KOC economics**,
  with a **human-in-the-loop** layer for live selling (legally required in China, trust-required in Taiwan).
- **LLM decision: switch from Qwen2.5 to Qwen3 (non-thinking "2507" variants).** See §7.

---

## 2. Global Context & Proof Points

| Signal | Figure (flagged) | Source |
|---|---|---|
| Virtual-influencer market | $8.3B (2025) → $11.7B (2026); $154–184B by 2032–34 @ 39–45% CAGR | Business Research Co., Mordor, Precedence |
| Regional share (2024) | N. America ~42.8%, Europe ~27.4% | Grand View Research |
| Engagement vs humans | ~3× (5.7–7.2% vs 1.9–2.3%) — **contradicted** by Lil Miquela's BMW campaign (0.6%) | marketing blogs (weak) |
| Cost vs human creators | ~50–76% cheaper per post | single-source (weak) |
| China live-commerce case | Luo Yonghao×Baidu: ~¥55M / 6.5h / 13M viewers | CNBC, TechNode, 36Kr |
| China platform case | JD 618: ~¥14B GMV, beat ~80% human hosts, ~1/10 cost, +~30% conversion | 腾讯新闻, 新浪财经 |
| West live case | Neuro-sama: ~162K Twitch subs (Jan 2026), est. ≥$400K/mo | Wikipedia, Tubefilter |
| AI-creator monetization | Fanvue: >$100M ARR, 17M MAU, 325K creators (Jan 2026) | Sacra |

**Cross-cutting lesson:** platform-average engagement stats look great, but *brand-campaign conversion*
is inconsistent (Miquela BMW 0.6%). **Measure real conversion, not engagement %.**

---

## 3. Market-by-Market Analysis

### 3.1 🇨🇳 China — the proven, most-regulated market

**Scale/platforms.** Douyin e-commerce GMV **~¥4.3T (2025)**; Taobao/Tmall #1; JD 言犀 (Yanxi) and Taobao
run in-house digital-human tooling; Xiaohongshu (RED) ~300M MAU with note→purchase 4–6%; Bilibili 109M
DAU with **native VTuber culture**. Digital-human *core* market ~¥40–49.5B (2025, ~18–20% CAGR).

| | |
|---|---|
| **Strengths** | Only market with mature digital-human commerce + proven GMV multipliers (国台酒 1.93× conversion, 7.5× daily GMV); Bilibili audience *natively accepts* virtual personas; 24/7 AI streaming at ~1/10 human cost; deep vendor ecosystem incl. **open-source self-hostable HeyGem (硅基)**. |
| **Weaknesses / risks** | Heaviest regulation (see §5): Douyin **bans fully-autonomous AI streaming**, requires **real-person real-time control** + on-screen "AI" label >1/10 screen; Xiaohongshu is **hostile to AI personas** (removed 600K AI notes H1 2025; Feb 2026 mandatory labeling + suppression of unlabeled AI); Bilibili commerce still small; portrait-rights risk if cloning real faces. |
| **How to overcome** | **Fully-synthetic (non-cloned) face** sidesteps portrait rights and fits our "fictional but real-looking" model; build fame on Bilibili/XHS/Douyin short-video → convert on Douyin Live + Taobao/JD digital-human stores; budget a **human-supervision layer** per stream (still ~1/10 human cost); bake the AI label into the persona brand; avoid banned verticals. |

**Vendors:** Tencent 智影 (~¥99–399/mo, content/editing), Baidu 曦灵/慧播星 (~¥199–699/mo, best live-commerce
results), 硅基/HeyGem (**open-source**, self-host), Alibaba 通义万相 (generative video+avatar), SenseTime 如影.

### 3.2 🇹🇼 Taiwan — #1 target; mature, trust-sensitive, NOT China

**Scale/platforms (DataReportal 2025):** pop 23.2M; YouTube ad-reach 79%, Facebook 73.8%, Instagram 48.8%,
**TikTok 41.9% (+47.7% YoY — fastest)**; LINE near-universal for closing sales/group-buy. Live-commerce runs
on **Facebook > Momo > YouTube > LINE > Shopee** and is **personality/relationship-trust led** — a fraction
of China's scale (Taiwan e-commerce ~$50B, online <12% of retail, +2.65% in 2024).

| | |
|---|---|
| **Strengths** | Short-video (IG/TikTok/Shorts) is a perfect fit for a high-frequency photoreal persona; TikTok's rapid growth = cheap discovery + younger, novelty-tolerant audience; **market is actively shifting to nano/KOC ("去中心化帶貨")** where AI can flood authentic-feeling micro-content cheaply; local precedent (**農純鄉** virtual spokesperson) shows positive reception when framed as a transparent brand character. |
| **Weaknesses / risks** | High authenticity bar; Facebook (top selling surface) skews older/skeptical; sensory categories (food/beauty efficacy) need real testimony an AI can't honestly give; **FTC Taiwan** requires sponsorship disclosure with penalties up to **NT$25M**; Xiaohongshu access restricted (Dec 2025); live selling exposes AI latency/uncanny failures. |
| **How to overcome** | Position as a **brand-owned character (curation/entertainment)**, never a fake "real user testimony"; lead on IG + TikTok + Shorts, use Facebook for retarget/community and **LINE OA** for CRM/group-buy conversion (human-in-the-loop 1:1); pair efficacy claims with real UGC/expert validation; **always disclose sponsorship + AI status** (regulatory tailwind favors early transparency); enter live selling last, via **Shopee Live**, after recorded-content trust is proven. |

### 3.3 🇺🇸 Americas — biggest market, best Western commerce funnel

**Scale/platforms.** **TikTok Shop US GMV $15.1B (2025, +68%), ~18% of US social commerce**, live ~14% and
growing ~84% YoY for live sellers; Instagram is the home of photoreal virtual influencers (+ Meta AI Studio);
YouTube Shorts huge for virtual creators (~50B VTuber views/3yr); **Twitch proves a fully-AI entity can top a
Western platform** (Neuro-sama). Fanvue (~$100M ARR) is the AI-native monetization hub.

| | |
|---|---|
| **Strengths** | Largest brand-deal ecosystem + the West's most mature shopping funnel (TikTok Shop); Gen-Z is the most AI-tolerant audience; multiple stacked revenue lines (brand deals + affiliate/TikTok Shop + subscription/Fanvue + live subs); Western **live shopping is still early → first-mover room** for a 24/7 AI streamer. |
| **Weaknesses / risks** | **Polarized consumer trust** (Sprout Q3 2025: 46% uncomfortable, only 23% comfortable — vs other data claiming 76% trust); brand-campaign ROI inconsistent (Miquela BMW 0.6%); TikTok requires an **AI toggle** for synthetic humans; TikTok-US ownership overhang; Fanvue's adult-adjacent brand-safety baggage. |
| **How to overcome** | Lead with **TikTok Shop + live shopping** to ride the fastest-growing curve; enable AI labels everywhere (no monetization penalty when compliant, and it differentiates to Gen-Z); anchor in **visual verticals** (fashion/beauty/fitness/tech/gaming), avoid trust-heavy categories; pair AI reach with human/UGC proof at the conversion step; keep a brand-safe public persona separate from any paywalled content. |

### 3.4 🇪🇺 Europe — large, high-value, strictest regulation

**Scale/platforms.** ~27% of the global market; same platforms (IG/TikTok/YouTube), lower live-commerce
maturity than Asia. The defining factor is the **EU AI Act (Article 50)**: binding AI-disclosure from
**2 Aug 2026** — the first such regime in a G7 jurisdiction.

| | |
|---|---|
| **Strengths** | High purchasing power; strong fashion/beauty brand base; early live-commerce = first-mover room; clear (if strict) rules reduce ambiguity once you comply. |
| **Weaknesses / risks** | **EU AI Act penalties up to €15M or 3% of global turnover** for non-disclosure; machine-readable provenance/watermark required; European consumers more privacy/authenticity-sensitive; no native European KOL in our roster yet (the **biggest coverage gap**). |
| **How to overcome** | **Build labeling in by design** (persistent AI disclosure in bio + per-post + embedded machine-readable provenance now); align with the EU **Code of Practice** before Aug 2026 for legal safe harbor; **build a dedicated Euro-Asian F6 KOL** (EN + one European language) as proposed in docs/04; treat FTC-style material-connection disclosure as standard on every brand deal. |

---

## 4. Cross-Market Strategy

- **Positioning (all markets):** a **transparent, brand-owned AI character**, not a fake human. Disclosure
  is the #1 consumer complaint *and* the regulatory direction — make it an asset.
- **Funnel:** short-video + persona building at the top (Bilibili/XHS/Douyin in CN; IG/TikTok/Shorts in
  TW/US/EU) → comment read-and-act loop filters buy-intent → convert in DM / TikTok Shop / Taobao-JD stores
  → live selling last, with human-in-the-loop.
- **Verticals:** apparel, beauty (non-medical claims), FMCG, lifestyle, tech/gaming. **Avoid** medical/health,
  finance, and China's 13 banned food categories.
- **Ops:** live streaming needs a lightweight human-supervision layer (legally required in China, trust-required
  in Taiwan) — still ~1/10 the cost of a full human host team.
- **Sequencing:** recorded short-video (prove trust + product-fit) → comment/DM automation in suggest mode →
  live digital-human selling.

---

## 5. Regulation & Compliance Matrix

| Market | Key rule | Effective | Requirement | Penalty |
|---|---|---|---|---|
| China | AI-labeling 《标识办法》 + GB 45438-2025 | **Sep 1 2025** | Explicit + implicit (metadata) AI labels | platform enforcement |
| China | 《直播电商监督管理办法》 | **Feb 1 2026** | Digital-human hosts supervised; continuous on-screen AI label; 13 banned food categories; no health/medical claims | admin penalties |
| China | 《AI 拟人化互动服务办法》 | **Jul 15 2026** | Algorithm filing + security assessment at >100K MAU; no minors for companion services | registration regime |
| China (Douyin) | Platform rule | in force | No autonomous AI streaming; real-person real-time control; AI label >1/10 screen; 30-day log retention | throttle/ban |
| EU | AI Act Article 50 | **Aug 2 2026** | Machine-readable AI marking; label deepfakes/AI content | **€15M or 3% turnover** |
| US | FTC Endorsement Guides + fake-review rule | in force | Material-connection disclosure (virtual = human); no AI fake reviews | ~$51,744 / violation |
| Taiwan | FTC 薦證廣告 (2023 amendment) | in force | Truthful endorsement + sponsorship disclosure; efficacy claims policed | **NT$50K–25M** |
| Taiwan | AI-labeling | proposed | Petition/NCC+MODA in motion; no enacted law yet | — |
| Platforms (global) | IG optional "AI Creator"; TikTok mandatory AI toggle; YouTube synthetic banner | in force | Self-label synthetic creators | reach/monetization |

**Net:** design for disclosure everywhere; keep a human-in-the-loop control layer for live; avoid
regulated verticals; plan for China algorithm-filing and EU provenance once you scale.

---

## 6. LLM Implementation Plan (the models to build with)

**Headline: move off Qwen2.5 to Qwen3, using the non-thinking `Instruct-2507` variants** so the models
never emit `<think>` blocks that break persona voice or JSON. Qwen remains the strongest family for
Traditional Chinese, so we stay in Qwen. Run locally via **Ollama** (or vLLM for throughput) on the CUDA box.

> ⚠️ Fast-moving field (research 2026-07). Rumored Qwen 3.5 / Gemma 4 / GLM-5 are **unverified** — re-check
> the Ollama library at build time. For hybrid Qwen3 (8B/14B), **pin non-thinking mode** in the system template.

### 6.1 Role → model mapping (by VRAM tier)

| Role | 24 GB (primary) | 16 GB | 8 GB | Notes |
|---|---|---|---|---|
| **Persona brain** (bilingual TC+EN chat, captions, DM replies, streaming) | **Qwen3-30B-A3B-Instruct-2507** Q4_K_M (~18–22 GB) | **Qwen3-14B** `/no_think` | Qwen3-8B `/no_think` (or 4B for long ctx) | 30B-quality at 3B-active speed, native non-thinking, 256K ctx. Direct upgrade from Qwen2.5-14B. |
| **Comment classifier** (strict JSON intent/toxicity/spam) | **Qwen3-4B-Instruct-2507** Q4_K_M (~4–5 GB) | same | same (or Qwen3-1.7B) | Fits every tier; ~95%+ class acc.; **enforce JSON via Ollama `format:"json"` / vLLM `guided_json`.** |
| **Vlog script writer** | Qwen3-30B-A3B-Instruct-2507 (reuse persona model) | Gemma3-27B (~16 GB, great EN prose, TC a notch below) | Qwen3-8B | API option if available: GLM-4.6 / DeepSeek-V3 (top bilingual, not single-GPU-local). |

License: Qwen3 = **Apache-2.0** (clean commercial). Gemma = commercial-OK but subject to Google's use policy.
**Avoid reasoning models** (DeepSeek-R1 distills, Qwen3 "Thinking") for these roles — they leak chain-of-thought.

### 6.2 Concrete implementation steps

```bash
# on the CUDA box (or Mac for the smaller tiers)
ollama pull qwen3:30b-a3b-instruct-2507-q4_K_M   # persona brain (24GB)  — or qwen3:14b for 16GB
ollama pull qwen3:4b-instruct-2507-q4_K_M         # comment classifier (all tiers)
```
1. **Persona brain** — point `research/03`'s `build_system_prompt` + Orchestrator at the Qwen3 model;
   set the Ollama template to **non-thinking** (add `/no_think` or `enable_thinking=false`); require SSE
   streaming so the future TTS/avatar layers consume the same token stream.
2. **Comment classifier** (`research/11`) — use Qwen3-4B with **constrained JSON decoding**
   (`format:"json"` / a JSON grammar) so output is always schema-valid regardless of model size.
3. **Vlog tool** (`tools/vlog_app.py`) — swap the `qwen2.5:7b` call for `qwen3:14b`/`30b-a3b`
   (`/no_think`); keeps the same Ollama HTTP interface.
4. **Update the runbook** — change `CUDA_SETUP.md §D` Ollama pulls from `qwen2.5:7b/3b` to the Qwen3 tags above.

### 6.3 Why this fits the project
- One family (Qwen3) covers persona brain + classifier + script writer → **one runtime, one download set**.
- Apache-2.0 = safe for a commercial product.
- Best-in-class Traditional Chinese for the Taiwan/China-facing personas, strong English for US/EU.
- Non-thinking Instruct variants = clean persona voice + reliable JSON, no CoT leakage.

---

## 7. Recommended Go-To-Market Sequence

```
Openly-AI, compliance-first brand  →  short-video persona building (IG/TikTok/Shorts; +Bilibili/XHS for CN)
→  comment read-and-act loop (suggest mode)  →  DM / TikTok-Shop / Taobao-JD conversion
→  live digital-human selling (human-in-the-loop, Shopee Live in TW / Taobao-JD in CN)
→  scale roster incl. a dedicated European KOL
```
Lead market: **Taiwan** (native TC personas, KOC economics, cheapest to prove). Highest-upside market:
**China** (proven digital-human commerce, but build the human-supervision + labeling layer first).
Biggest gap to close: **Europe** (build the native-language KOL before the EU AI Act bites in Aug 2026).

---

## 8. Key Caveats (data reliability)

- Market-size forecasts vary by an order of magnitude by definition — directional only.
- Consumer-trust data **conflicts** (46% uncomfortable vs 76% trust) — sentiment is unsettled.
- Engagement "3× human" is marketing-blog-sourced and contradicted by real campaign data (Miquela 0.6%).
- Case GMV/earnings (Luo Yonghao, JD ¥14B, Neuro-sama, Aitana) are self-reported/estimated, not audited.
- Some China figures (林清轩 +180%, exact market size) are unverified; several Taiwan rate ranges are indicative.
- LLM landscape moves monthly — re-verify model tags/licences at build time.

*Full source lists (China, US/Europe, Taiwan, LLM) are held in the research task outputs; key sources are
linked inline above. This document should be re-validated before major spend or public launch.*
