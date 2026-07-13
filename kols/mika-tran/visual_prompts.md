# Mika Tran — Visual / AI Image Prompts

Flavor 3 — **Real-IP Sexy / Authentic-Bold（真實 IP 風格）**。
生成必須遵守 [`/kol-generate-image`](../../.claude/commands/kol-generate-image.md) 的 Film Candid 攝影標準。
（結構化版本同步存於 [`profile.json`](profile.json) 的 `ai_prompts` 區塊。）

---

## 0. Real-IP 三原則

1. **手機 / 鏡子 / 朋友隨手拍**——絕不棚拍。
2. **35mm 底片顆粒 + 自然光**，少修圖，保留膚理與瑕疵。
3. **生活化動作 + 視線不一定對鏡頭**；suggestive but tasteful，never explicit。

---

## 1. 角色外觀基礎設定 (Base Character Prompt)

用於種子鏈的文字生成錨點：

```
A candid, authentic phone-camera photo of Mika, a 24-year-old Vietnamese-American woman,
petite and curvy with a natural toned figure, soft round-oval face with high cheekbones,
dark brown expressive slightly-sleepy eyes, natural monolid-to-low-crease, long dark
brown-black hair in a messy claw-clip bun or air-dried waves, healthy skin with real
texture and a few small freckles and moles, minimal or no makeup, a bold relaxed knowing
expression. Real-person influencer vibe, not studio-polished. Shot on 35mm film camera,
film grain, natural available light, authentic unstaged moment, natural skin texture. --ar 3:4
```

**Negative（SD 參考）：**
```
studio lighting, glossy, over-retouched, plastic skin, heavy smoothing, airbrushed,
posing for camera, professional model pose, oversaturated, fake AI look, deformed,
extra fingers, watermark, logo, text
```

---

## 2. 場景 Prompt 範本庫（Film Candid）

### A — 臥室鏡子自拍
```
Mika taking a candid mirror selfie on her phone in a lived-in East-LA bedroom, slightly
messy room in background, wearing a fitted white tank top and low-rise baggy jeans,
claw-clip bun, one hand holding the phone, relaxed knowing expression, warm indoor lamp
light, shot on 35mm film, film grain, authentic unstaged moment, natural skin texture. --ar 3:4
```

### B — GRWM 浴室鏡
```
Mika getting ready in front of a bathroom mirror, mid-makeup, holding a makeup product,
natural everyday makeup half done, wearing a cropped tank, hair clipped up, glancing at
the mirror with a subtle smirk, soft diffused indoor light, shot on 35mm film, film grain,
candid GRWM moment, natural skin texture. --ar 3:4
```

### C — 夜出街頭 candid
```
Mika out at night with friends (blurred figures in background), wearing a fitted black
slip dress and hoop earrings, holding a drink, laughing candidly not at the camera, warm
ambient bar lighting, shot on 35mm film, film grain, candid night out energy, natural
skin texture. --ar 3:4
```

### D — 健身房鏡子
```
Mika taking a post-workout gym mirror selfie, wearing a matching activewear set, natural
toned figure, slightly flushed, hair up, phone in hand, relaxed confident expression,
natural gym daylight, shot on 35mm film, film grain, authentic candid moment, natural
skin texture. --ar 3:4
```

### E — 沙發居家 candid
```
Mika lounging on a worn couch in an oversized T-shirt and shorts, half-eating takeout,
looking at her phone, hair messy, cozy chaotic apartment, warm lamp light, shot on 35mm
film, film grain, authentic unstaged everyday moment, natural skin texture. --ar 3:4
```

### F — 街拍拿咖啡
```
Full body candid street shot of Mika walking down a sunny East-LA street, wearing a
cropped tank and baggy jeans, holding an iced coffee, other hand on her phone, looking
off to the side mid-stride, warm dappled sunlight, shot on 35mm film, film grain, analog
lifestyle photography, authentic candid moment. --ar 3:4
```

---

## 3. 種子鏈工作流 (Seed Chain — Seedream + Reference Element)

> **模型指定：Seedream**（使用者指示：建立 KOL IP 用 Seedream）。
> Higgsfield 的 **Soul** 只支援 `soul_2` / `soul_cinema`，不能用 Seedream，因此一致性改用
> **Reference Element**。

1. **基準臉：** 用「基礎設定 prompt」以 **Seedream** text-to-image 生成 4 張，挑一張最符合人設的當基準臉。
   （確切 Seedream 模型 id 以 `models_explore` 查詢確認。）
2. **建立 Element：** `show_reference_elements(action='create')`，用基準臉那張 job → 取得 `element_id`。
3. **內容種子：** 用 **Seedream + 該 Element** 生成 5–6 張 film-candid 場景圖，維持同一人臉。
4. **存檔：** 圖放 `kols/mika-tran/images/seedream_v1/`，`element_id` / job_id 記回
   `profile.json` → `ai_assets`，commit + push。

（若要改走 Soul 路線：改用 soul_2 生成 + `show_characters(action='train')` 訓練 Soul，
但內容模型即為 soul_2 而非 Seedream。）

---

## 4. Film Candid 攝影標準後綴（所有場景通用）

```
shot on 35mm film camera, film grain, analog photography aesthetic,
candid natural light, authentic unstaged moment, natural skin texture
```

避免 `posing for camera` / `smiling at camera` / `professional model pose`（會產生廣告棚拍感）。
