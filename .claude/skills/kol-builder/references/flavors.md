# KOL House Flavors

This database supports more than one persona "flavor." Pick the flavor that matches the
brief, then apply the shared principles in `style-guideline.md`. Each flavor has a worked
example to mirror.

---

## Flavor 1 — 純欲風 / Innocent-Alluring

**Worked example:** `kols/chloe-lin/`

- **Core:** 反差萌 — clean / innocent doll-like face + a confident, figure-flattering body & styling.
  Innocence and allure in one person.
- **Voice:** sweet on the surface, a little-devil (小惡魔) teasing underneath; mock-innocent.
- **Color:** soft morandi / white / blush / sky blue; dreamy.
- **Scenes:** cozy mirror selfies, athleisure street POV, resort/poolside, café, late-night soft POV.
- **Aspect ratio default:** `--ar 3:4`.
- **Boundary:** alluring but classy — adult, mainstream fashion-influencer level, never explicit.

---

## Flavor 2 — Wholesome-Aspirational / Cute × Elegant × Confident × Approachable

**Worked example:** `kols/sienna-lai/`

- **Core:** NOT a cold runway model — a successful, fun, genuine creator who shares her *whole life*.
  Aspirational **but real**. "看起來很成功、很有趣、又願意分享生活的人。"
- **Brand DNA:** Cute × Elegant × Confident × Approachable.
- **Figure:** Fitness / Healthy / Athletic (clear waistline, good hip-leg ratio) over extreme-thin.
- **Personality:** optimistic, humorous, genuinely curious (tech / travel / fitness / beauty),
  shares what she's learning, friendly + sincere, has real opinions. Builds long-term brand trust.
- **Voice:** warm, upbeat, well-traveled friend; gives real opinions, ends on a genuine question.
- **Content pillars:** Lifestyle 40% · Travel 20% · Fitness 15% · Fashion 10% · Beauty 10% · Work 5%.
- **Photo distribution:** Coffee shop 25% · Travel 20% · Gym 15% · Home 15% · Street 10% · Beach 10% · Formal 5%.
- **Expression:** natural smile dominant; looking away / glancing back / mirror selfie / laughing. Avoid sustained cold looks.
- **Color:** warm cream / caramel / beige / denim blue / olive / terracotta; premium-but-approachable.
- **Camera:** angle slightly above eye level; 35 / 50 / 85mm; golden hour / window / soft light.
  Avoid harsh flash, over-HDR, "too-AI" look.
- **Aspect ratio default:** `--ar 4:5`.
- **Boundary:** wholesome, brand-safe; no diet-culture; authenticity over a fake perfect life.

### Wholesome-Aspirational master prompt

```
A highly photorealistic young woman in her mid-20s with a warm, approachable smile and a
confident yet effortless presence. She has long naturally wavy dark brown hair, healthy
glowing skin with subtle natural texture, expressive brown eyes, soft feminine facial
features, small face with soft contours, and an athletic, well-proportioned figure with a
clear waistline. Her fashion is modern, casual, and elegant rather than flashy, combining
timeless pieces with current trends. Natural window light, golden hour, shallow depth of
field, candid lifestyle photography, DSLR realism, subtle cinematic color grading, premium
influencer aesthetic, editorial quality, authentic social media photography, highly detailed
skin, realistic proportions, genuine emotion, confident but approachable. --ar 4:5 --v 6.0
```

---

## Flavor 3 — Real-IP Sexy / Authentic-Bold

**Worked example:** `kols/mika-tran/`
**Style inspiration handle:** `@11.mzzz` (referenced as inspiration only — see note below)

- **Core:** a confident, sexy adult creator whose signature is feeling like a **real person**
  ("真實 IP 的風格"), not a polished studio fantasy. The appeal is *bold + genuinely relatable*:
  "the hot girl you actually follow because she feels real."
- **Contrast (the hook):** overtly confident / sexy visuals paired with unfiltered, personal,
  everyday-life energy — real apartment, real phone camera, real mood.
- **Difference vs 純欲風 (Flavor 1):** Flavor 1 = innocent face + alluring body (fantasy contrast).
  Flavor 3 = openly bold/sexy but grounded in raw authenticity (realness is the differentiator).
- **Figure & styling:** confident casual-sexy — bodycon, crop tops, going-out fits, gym sets,
  swimwear at mainstream IG level. Owns her look without apology.
- **Personality / voice:** casual, direct, a little bold and teasing; personal, over-shares in a
  relatable way; talks straight to camera like a close friend.
- **Visual aesthetic:** "real-IP" look — real phone-camera selfies, mirror shots, candid grain,
  natural/available light, minimal over-editing, small imperfections kept on purpose. Avoids the
  glossy studio / "too-AI" polish. Authenticity > perfection.
- **Scenes:** bedroom/bathroom mirror selfies, car selfies, getting-ready, night-out, gym,
  casual home lounging, everyday candids.
- **Aspect ratio default:** `--ar 4:5` (feed) / `9:16` (stories & reels).
- **Generation stack (house default for this flavor):** **Seedream** text-to-image +
  a Higgsfield **Reference Element** for identity consistency (generate canonical face →
  `show_reference_elements(create)` → Seedream content shots). Note: Higgsfield **Souls** are
  `soul_2`-only, so they are NOT used with Seedream — use an Element instead.
- **Boundary (non-negotiable):** adult persona, confident/sexy but still **mainstream IG level —
  never explicit / NSFW**. Realness must never become non-consensual-looking, private, or explicit.

### Real-IP Sexy master prompt

```
A candid, authentic phone-camera photo of a confident young woman in her mid-20s with a bold,
relaxed presence and a subtle knowing smile. Natural long hair, healthy skin with real texture
and minor imperfections, expressive eyes, an attractive toned figure. Wearing a casual-sexy
everyday outfit (fitted top / going-out fit), in a real lived-in setting — bedroom mirror,
car, or apartment. Natural available light, slight phone-camera grain, unretouched realism,
authentic social-media selfie aesthetic, real-person influencer vibe, not studio-polished,
genuine and grounded, tasteful. --ar 4:5 --v 6.0
```

### Note on real-person references

`@11.mzzz` is recorded as a *style/aesthetic reference only*, exactly like the existing
`@sophieraiin` / `@miakhalifa` handles in this repo. When building a Flavor-3 KOL: create an
**original** identity, face, and name — do **not** clone or reproduce the likeness, identity, or
private details of any real account holder. Extract the *style* (authentic real-IP look), not the person.

---

## Flavor 4 — Male Real-IP / Confident-Casual

**Worked example:** `kols/jax-calloway/`
**Style standard:** `docs/03-kol-male-real-ip-standard.md` (extends `docs/02`'s Film Candid
base with male-specific identity anchors, styling motifs, and scene genres)
**Style inspiration:** 3 user-uploaded reference photos (festival, road-trip, streetwear) —
recorded as style reference only; the KOL uses an **original** identity, not the pictured
person's likeness.

- **Core:** the first male flavor in this house. Same real-IP doctrine as Flavor 3 (candid,
  unstaged, film-grain, never studio) but the identity/styling spec is male: sharp jawline,
  gym-lean (not bodybuilder) build, recurring waistband/necklace/belt-buckle motifs.
- **Contrast:** confident/attractive but always "caught doing something" — never a static
  posed stance. A direct-camera glance still reads as "caught looking up," not a model stare.
- **Scene genres (3, not one studio look):** festival golden hour, desert/road-trip casual,
  streetwear fast-food candid — each proves the styling holds up under a different real-world
  light (warm backlight, flat hazy daylight, mixed fluorescent).
- **Generation stack:** **Seedream** (`seedream_v4_5`) + Higgsfield **Reference Element**
  (embed `<<<element_id>>>` in the prompt) — same mechanism as Flavor 3, Souls are
  soul_2-only so not used.
- **Aspect ratio default:** `--ar 3:4`.
- **Boundary:** adult persona, mainstream/brand-safe (shirtless festival/beach content is
  standard mainstream social content) — confident and attractive, **never explicit/NSFW**.

---

## Choosing / adding a flavor

- Match the brief to a flavor; if it's a new direction, document it here with a one-line core,
  a color/scene/voice summary, a worked example, and an explicit boundary line.
- Whatever the flavor, the non-negotiables in `style-guideline.md` always apply:
  adult persona, mainstream level, never explicit, keep real skin texture, end posts on an
  open question.
