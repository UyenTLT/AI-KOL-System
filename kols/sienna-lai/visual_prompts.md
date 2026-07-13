# Sienna Lai — Visual / AI Image Prompts

給 Midjourney v6 / SDXL / Higgsfield 使用的角色視覺設定。
**Brand DNA：Cute × Elegant × Confident × Approachable。**
（結構化版本同步存於 [`profile.json`](profile.json) 的 `ai_prompts` 區塊。）

---

## 0. 拍攝鐵律

1. **鏡頭高度：** 略高於眼睛
2. **焦段：** 35mm / 50mm / 85mm
3. **光線：** Golden Hour / Window Light / Soft Light
4. **表情：** 自然微笑為主，避免長期高冷
5. **避免：** 強閃光、過度 HDR、AI 味太重、塑膠感磨皮、浮誇

> 尺度守則：wholesome、品牌安全，aspirational but real。

---

## 1. 角色外觀基礎設定 (Base Character Prompt)

每張圖以此墊底作為一致性錨點，再接場景區塊。這就是可直接交給影像模型的 master prompt：

```
A highly photorealistic young woman in her mid-20s with a warm, approachable smile
and a confident yet effortless presence. She has long naturally wavy dark brown hair,
healthy glowing skin with subtle natural texture, expressive brown eyes, soft feminine
facial features, small face with soft contours, and an athletic, well-proportioned
figure with a clear waistline. Her fashion is modern, casual, and elegant rather than
flashy, combining timeless pieces with current trends. Natural window light, golden hour,
shallow depth of field, candid lifestyle photography, DSLR realism, subtle cinematic
color grading, premium influencer aesthetic, editorial quality, authentic social media
photography, highly detailed skin, realistic proportions, genuine emotion, confident but
approachable. --ar 4:5 --v 6.0
```

**Stable Diffusion Negative Prompt（建議）：**
```
flashy, gaudy, harsh flash, over-HDR, oversaturated, plastic skin, heavy smoothing,
fake AI look, deformed, extra fingers, bad anatomy, nsfw, explicit, watermark, logo, text
```

---

## 2. 場景 Prompt 範本庫（依照片風格分佈）

`[base]` = 上面的角色基礎描述（建議每張重述主體以鎖定一致性）。

### A — Coffee Shop（25%）
```
[base] sitting in a sunlit minimalist café by a large window, a flat white on a wooden
table, glancing up from a book with a warm natural smile, candid lifestyle photo, 50mm,
shallow depth of field, soft window light, premium influencer aesthetic. --ar 4:5 --v 6.0
```

### B — 旅行（20%）
```
[base] walking through a charming European old-town street at golden hour, light linen
outfit and a tote bag, looking back over her shoulder with a relaxed smile, candid travel
photography, 35mm, warm cinematic grade. --ar 4:5 --v 6.0
```

### C — 健身房（15%）
```
[base] in a bright modern gym, wearing a clean matching athleisure set, mid-stretch with
an energetic confident expression, natural daylight, athletic healthy figure, candid
fitness lifestyle, 50mm. --ar 4:5 --v 6.0
```

### D — 家裡（15%）
```
[base] relaxing at home on a cozy linen sofa near a window, oversized knit and casual
shorts, holding a mug, soft genuine laugh, warm interior, candid lifestyle, 35mm, soft
natural light. --ar 4:5 --v 6.0
```

### E — 街拍（10%）
```
[base] candid street-style shot on a city sidewalk, casual elegant outfit (white tee,
tailored trousers, sneakers), mid-stride looking off-camera, golden hour, 85mm, shallow
depth of field, editorial. --ar 4:5 --v 6.0
```

### F — 海邊（10%）
```
[base] on a calm beach at sunset, light summer dress or a tasteful one-piece with an open
linen shirt, wind in her hair, serene confident smile, warm golden light, candid travel
photography, 50mm. --ar 4:5 --v 6.0
```

### G — 正式活動（5%）
```
[base] at an evening event, elegant cocktail dress, minimal jewelry, soft poised smile,
soft ambient event lighting, editorial portrait, 85mm, shallow depth of field. --ar 4:5 --v 6.0
```

---

## 3. 一致性工作流 (Consistent Character)

1. **刷種子臉：** 用基礎 prompt 生成多張，挑一張最符合 brand DNA 的當「基準臉」。
2. **鎖臉：**
   - **Midjourney：** `--cref <基準臉URL>`（可加 `--cw 100`）。
   - **Stable Diffusion：** IP-Adapter / InstantID / ReActor，或訓練專屬 LoRA。
   - **Higgsfield（本專案常用）：** 5–15 張基準圖訓練一個 Soul，以 `soul_id` 生成各場景，
     job/檔案資訊記回 `profile.json` → `ai_assets`（見 `kols/sofia-vargas/profile.json`）。
3. **批次生成：** 固定基礎設定，依「照片風格分佈」比例替換場景區塊，產出整套內容。
4. **存檔：** 圖放 `kols/sienna-lai/images/`，metadata 記回 `profile.json`。

---

## 4. 後續操作建議

1. **種子圖：** 用 master prompt 刷臉 → 選基準臉 → 鎖臉。
2. **腳本自動化：** 把人設 + 本檔餵給 Claude，批次產「一週 IG 企劃（視覺構圖 + 文案）」。
3. **影片化：** 種子圖接 image-to-video 做 Reels（參考 `docs/01-video-generation-quick-ref.md`）。
