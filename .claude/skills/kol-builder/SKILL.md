---
name: kol-builder
description: Base guideline and workflow for designing AI KOL / virtual-influencer personas in this repo. Use when creating, designing, drafting, or extending a KOL character — building a new persona, writing a character bible, defining content pillars/voice, or producing AI image prompts (Midjourney/Stable Diffusion/Higgsfield). Encodes the 純欲風 (innocent-yet-alluring) visual rules, the persona/voice principles, the profile.json schema workflow, and reusable prompt + character-card templates.
---

# KOL Builder — AI KOL 角色設定基礎指南

This skill captures the house methodology for building attractive, "scroll-stopping"
AI KOL personas in the `Buildup_KOL` database. Use it as the base guideline whenever a
new KOL is being designed or an existing one extended.

## What this repo is

A KOL **character database**. Each KOL is one directory under `kols/` with structured
JSON + narrative docs. See `README.md` and `kols/schema.json` for the canonical structure.

```
kols/{kol-id}/
├── profile.json        # structured data — MUST conform to kols/schema.json
├── character.md        # full character bible (Chinese narrative)
├── content_style.md    # content cadence, formulas, interaction templates
├── visual_prompts.md   # MJ/SD/Higgsfield prompt templates + consistency workflow
└── images/             # generated/seed images (keep a .gitkeep)
```

The strongest worked examples to mirror are **`kols/chloe-lin/`** (純欲風 flavor) and
**`kols/sienna-lai/`** (Cute×Elegant×Confident×Approachable flavor); also `kols/sofia-vargas/`.

## When to use

- "建立 / 設計一個新的 KOL"，or design a virtual influencer / AI avatar persona
- Writing or revising a character bible, persona, voice, or content pillars
- Generating AI image prompts for a KOL (base character + scenes + consistency)
- Producing a weekly content plan (visual + caption) for a KOL

## Workflow — adding a new KOL

1. **Pick an id**: kebab-case `{firstname}-{lastname}` (e.g. `chloe-lin`).
2. **Pick a flavor**: load `references/flavors.md` and choose the persona flavor
   (e.g. 純欲風 → `chloe-lin`; Cute×Elegant×Confident×Approachable → `sienna-lai`),
   then load `references/style-guideline.md` for the shared visual + persona rules.
3. **Fill the profile**: copy `assets/profile.template.json` → `kols/{id}/profile.json`,
   complete every field, conform to `kols/schema.json`. Keep `status: "draft"` until assets exist.
4. **Write the docs**: `character.md`, `content_style.md`, `visual_prompts.md` — match the depth,
   bilingual tone, and section layout of `kols/chloe-lin/`.
5. **Add prompts**: use `references/prompt-templates.md` for the base character prompt + scene blocks.
6. **Register it**: add an entry to `kols/index.json` and the table in `README.md`.
7. **Validate**: `python3 -c "import json,glob; [json.load(open(f)) for f in glob.glob('kols/**/*.json',recursive=True)]; print('JSON OK')"`.

## Core principles (summary — full detail in references/style-guideline.md)

These are shared defaults; flavor-specific nuance lives in `references/flavors.md`.

- **反差 (Contrast):** the hook is a contrast — innocent face + confident figure (純欲風),
  or polished/successful + honest/relatable (wholesome-aspirational). Pick per flavor.
- **Grounded Reality:** selfies / POV / candid / real locations over sterile studio shots.
- **High-end color:** soft palettes (morandi, white, blush, sky blue) — never gaudy.
- **Voice:** talks like voice-noting a best friend; short sentences, emoji, always ends on an
  open question to pull comments.
- **Boundary (non-negotiable):** alluring but **classy** — adult personas only, mainstream
  fashion/travel-influencer level, never explicit / NSFW. Encode this in every `brand_dont`.

## Reference files

- `references/flavors.md` — the house persona flavors: 純欲風 / innocent-alluring →
  `chloe-lin`; Cute×Elegant×Confident×Approachable wholesome-aspirational → `sienna-lai`;
  Real-IP sexy / authentic-bold (real-person-feel) → `mika-tran`; Male Real-IP /
  Confident-Casual → `jax-calloway` (first male KOL; see `docs/03-kol-male-real-ip-standard.md`).
  Each has its own
  master prompt, color/scene/camera notes, and boundary. Pick one first.
- `references/style-guideline.md` — full visual rules, persona archetypes, voice, content pillars,
  the four reference-profile archetypes and how to blend them.
- `references/prompt-templates.md` — base character prompt, scene prompt library, SD negative
  prompt, and the consistent-character workflow (--cref / IP-Adapter / Higgsfield Soul).
- `assets/profile.template.json` — fill-in-the-blank profile conforming to the schema.
- `assets/character-card.template.md` — the structured "Claude brain" card for writing posts/replies.

## Tooling notes

- Image/video/voice generation runs through the **Higgsfield (`higgs`) MCP** tools
  (`generate_image`, `generate_video`, `create_voice`, etc.). A `PostToolUse` hook in
  `.claude/settings.json` auto-commits + pushes after image/video/audio generation.
- For face consistency, train a Higgsfield **Soul** from 5–15 seed images and record the
  `soul_id` under `profile.json` → `ai_assets` (see `kols/sofia-vargas/profile.json`).
- Generating media costs credits — confirm with the user before a generation run.
