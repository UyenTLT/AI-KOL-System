# AI Image Prompt Templates

給 Midjourney v6 / Stable Diffusion / Higgsfield 使用的 KOL 視覺 prompt 模板。
複製後替換 `[...]` 佔位字，再依場景接區塊。完整實例見 `kols/chloe-lin/visual_prompts.md`。

---

## 0. 三原則（每張圖都套用）

1. **反差萌：** 臉清純無辜；身材與穿搭才負責線條。
2. **Grounded Reality：** 自拍 / POV / 抓拍 / 真實場景 > 棚拍。
3. **高級色彩：** 柔色調，避開豔俗。尺度 = alluring but never explicit。

---

## 1. 角色外觀基礎設定 (Base Character Prompt)

每張圖以此墊底作為一致性錨點，再接場景區塊：

```
A ultra-realistic 8k photo of a [age]-year-old female influencer, [ethnicity],
innocent and beautiful doll-like face, clean glowing skin, subtle soft makeup,
natural messy long wavy [hair color] hair, captivating [eye color] eyes, friendly
smile. Extremely fit and toned hourglass figure, defined collarbones. --ar 3:4 --v 6.0
```

**Stable Diffusion Negative Prompt（建議）：**
```
explicit, nsfw, nudity, deformed, extra fingers, bad anatomy, oversaturated,
heavy smoothing, plastic skin, watermark, logo, text
```

---

## 2. 場景 Prompt 範本庫

接在基礎設定後（或重述主體）。`[base]` = 上面的角色描述。

### A — 純欲居家自拍
```
A candid phone selfie of [base subject], standing in front of a mirror in a sunlit
modern bedroom. Wearing a cozy oversized white knit sweater slipping off one shoulder.
Soft morning light, natural messy hair, innocent expression with a playful smirk,
highly detailed skin texture, shot on iPhone, instagram aesthetic, realistic, 8k. --ar 3:4 --v 6.0
```

### B — 陽光健身 / 街頭穿搭
```
A POV candid shot of [base subject] walking down a sunny street. Looking back at the
camera with a bright smile. Wearing tight pastel pink yoga pants and a matching sports
bra, showcasing a toned hourglass figure. Golden hour lighting, motion blur in
background, street style photography, high fashion look, attractive yet wholesome. --ar 3:4 --v 6.0
```

### C — 度假 / 沙灘風（高流量）
```
An aesthetic medium shot of [base subject] sitting by an infinity pool, ocean
background. Wearing an elegant [color] swimsuit, wet hair pushed back, minimalist gold
jewelry. Sun-kissed glowing skin, natural confident expression, high-end travel blogger
vibes, soft cinematic lighting, detailed water ripples, masterpiece. --ar 3:4 --v 6.0
```

### D — 咖啡廳午後穿搭
```
A candid lifestyle photo of [base subject] sitting in an aesthetic minimalist café, soft
afternoon window light. Wearing a fitted white tank top and beige tailored trousers, a
matcha latte on the marble table, looking slightly off-camera with a soft smile. Morandi
color palette, film-photography texture, instagram aesthetic, 8k. --ar 3:4 --v 6.0
```

### E — 深夜居家感性 (Soft POV)
```
A warm dim home portrait of [base subject] on a couch at night, only a soft warm lamp
lighting the face. Wearing a simple grey loungewear set, hair loosely down, a dreamy
slightly wistful expression looking into the camera, cozy intimate POV mood, detailed
skin, cinematic soft focus, 8k. --ar 3:4 --v 6.0
```

---

## 3. 一致性工作流 (Consistent Character)

1. **刷種子臉：** 用基礎 prompt 生成多張，挑一張最滿意的當「基準臉 (seed face)」。
2. **鎖臉：**
   - **Midjourney：** `--cref <基準臉URL>`（可加 `--cw 100` 強制臉部一致）。
   - **Stable Diffusion：** IP-Adapter / InstantID / ReActor，或訓練專屬 LoRA。
   - **Higgsfield（本專案常用）：** 用 5–15 張基準圖訓練一個 Soul，以 `soul_id` 生成各場景。
     job/檔案資訊記回 `profile.json` → `ai_assets`（見 `kols/sofia-vargas/profile.json`）。
3. **批次生成：** 鎖定後固定基礎設定，只換場景區塊，產出整套內容。
4. **存檔：** 圖放 `kols/{id}/images/`，metadata 記回 `profile.json`。

---

## 4. 後續操作建議

1. **種子圖：** 基礎 prompt 刷臉 → 選基準臉 → 鎖臉。
2. **腳本自動化：** 把人設 + 本檔餵給 Claude，批次產「一週 IG 企劃（視覺構圖 + 文案）」。
3. **影片化：** 種子圖接 image-to-video 做 Reels（參考 `docs/01-video-generation-quick-ref.md`）。
