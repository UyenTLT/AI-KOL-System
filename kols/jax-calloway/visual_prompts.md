# Jax Calloway — Visual / AI Image Prompts

Flavor 4 — **Male Real-IP / Confident-Casual**（首個男性 KOL）。
完整攝影標準見 [`docs/03-kol-male-real-ip-standard.md`](../../docs/03-kol-male-real-ip-standard.md)。
（結構化版本同步存於 [`profile.json`](profile.json) 的 `ai_prompts` 區塊。）

> ⚠️ 視覺標準參考 3 張使用者提供的真實照片，但僅提取風格 / 一致性方法論——
> Jax 是原創身分，不複製任何真實個人的肖像。

---

## 0. Male Real-IP 三原則

1. **手機抓拍 candid**——每張都在「做一件事」，不站直擺拍。
2. **35mm 底片顆粒 + 自然光**，三種場域各自的光線都要撐得住。
3. **保留真實膚理與體態**——不誇張肌肉線條、不磨皮；confident and attractive, never explicit。

---

## 1. 角色外觀基礎設定 (Base Character Prompt)

用於種子生成的文字錨點：

```
A candid, authentic phone-camera photo of Jax, a 23-year-old White American man, gym-lean
athletic build with visible abs and a natural shoulder line, sharp defined jawline, straight
nose, full lips, hazel eyes with a relaxed confident gaze, light-to-medium brown wavy
tousled hair, fair-to-light-olive skin with real texture and natural sheen. Real-person
influencer vibe, not studio-polished. Shot on 35mm film camera, film grain, natural
available light, authentic unstaged moment, natural skin texture. --ar 3:4
```

**Negative（SD 參考）：**
```
exaggerated bodybuilder muscle, studio lighting, glossy, over-retouched, plastic skin,
heavy smoothing, airbrushed, posing for camera, professional model pose, oversaturated,
fake AI look, nsfw, explicit, deformed, extra fingers, watermark, logo, text
```

---

## 2. 場景 Prompt 範本庫（三大場域）

生成內容圖時，用 `<<<element_id>>>` 取代文字外型描述（Higgsfield Reference Element 會自動注入）。

### A — 音樂節黃金時刻 (festival-golden-hour)
```
<<<element_id>>>, shirtless, layered thin necklace, white cat-eye sunglasses, stacked
colorful festival wristbands, rings, hooking thumbs into waistband looking off to the side,
at an outdoor music festival at golden hour, blurred crowd and a ferris wheel silhouette in
the background, warm backlight, sun-kissed skin with natural sweat sheen, shot on 35mm film,
film grain, authentic candid festival moment, natural skin texture. --ar 3:4
```

### B — 沙漠公路旅行 (road-trip-casual)
```
<<<element_id>>>, shirtless with grey drawstring sweatpants, silver cross necklace, sneakers
kicked off on the ground nearby, looking down adjusting his waistband, leaning against a
vintage green off-road vehicle parked on a sandy coastal cliff, flat hazy late-afternoon
daylight, relaxed road-trip mood, shot on 35mm film, film grain, authentic unstaged moment,
natural skin texture. --ar 3:4
```

### C — 速食店街拍 (streetwear-candid)
```
<<<element_id>>>, sleeveless acid-wash denim western shirt with snap buttons, layered silver
chain necklaces, white rectangular sunglasses, engraved western belt buckle, holding two
fast-food drinks walking out of a storefront glass door, direct glance at camera like caught
looking up, mixed fluorescent and daylight indoor-outdoor lighting, blurred figures in
background, shot on 35mm film, film grain, authentic street candid moment, natural skin
texture. --ar 3:4
```

### D — 健身房鏡子 (gym-mirror)
```
<<<element_id>>>, wearing grey gym shorts, post-workout gym mirror selfie, natural toned
physique, slightly flushed, phone in hand, relaxed confident half-smile, natural gym
daylight, shot on 35mm film, film grain, authentic candid moment, natural skin texture. --ar 3:4
```

---

## 3. 種子鏈工作流 (Seed Chain — Seedream + Reference Element)

1. **基準臉：** 用「基礎設定 prompt」以 **Seedream (`seedream_v4_5`)** text-to-image 生成 4 張，挑一張最符合人設的當基準臉。
2. **建立 Element：** `show_reference_elements(action='create')`，用基準臉那張 job → 取得 `element_id`。
3. **內容種子：** 用 **Seedream + `<<<element_id>>>`** 生成場景 A/B/C/D，維持同一人臉與體態。
4. **存檔：** 圖放 `kols/jax-calloway/images/seedream_v1/`，`element_id` / job_id 記回
   `profile.json` → `ai_assets`，commit + push。
