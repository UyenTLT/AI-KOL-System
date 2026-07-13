# Chloe Lin — Visual / AI Image Prompts

給 Midjourney v6 / Stable Diffusion 等繪圖 AI 使用的角色視覺設定。
（結構化版本同步存於 [`profile.json`](profile.json) 的 `ai_prompts` 區塊。）

---

## 0. 純欲風視覺三原則

1. **反差萌：** 臉清純無辜乾淨；身材與穿搭才負責線條。臉不辣，身材辣。
2. **Grounded Reality：** 手機自拍 / 男友視角 POV / 動態抓拍 / 真實場景 > 死板棚拍。
3. **高級色彩：** 柔和色調（莫蘭迪、白、粉、天藍）營造清純與高級，避開豔俗。

> 尺度守則：alluring，但 **never explicit**。維持標準時尚 / 旅遊網紅尺度。

---

## 1. 角色外觀基礎設定 (Base Character Prompt)

每張圖都以這段墊底，作為一致性錨點，再接場景區塊。

```
A ultra-realistic 8k photo of a 22-year-old female influencer, mix of
Caucasian and Asian ethnicity, innocent and beautiful doll-like face,
clean glowing skin, subtle soft makeup, natural messy long wavy brown hair,
captivating hazel eyes, friendly smile. Extremely fit and toned hourglass
figure, defined collarbones. --ar 3:4 --v 6.0
```

**Stable Diffusion 建議 Negative Prompt：**
```
explicit, nsfw, nudity, deformed, extra fingers, bad anatomy,
oversaturated, heavy smoothing, plastic skin, watermark, logo, text
```

---

## 2. 經典場景 Prompt

### 場景 A — 純欲居家自拍（Sophie Raiin / Corinna Kopf 居家風）
```
A candid phone selfie of the 22-year-old female influencer, standing in
front of a mirror in a sunlit modern bedroom. Wearing a cozy oversized
white knit sweater slipping off one shoulder. Soft morning light, natural
messy hair, innocent facial expression with a playful smirk, highly detailed
skin texture, shot on iPhone, instagram aesthetic, realistic, 8k.
--ar 3:4 --v 6.0
```

### 場景 B — 陽光健身 / 街頭穿搭（健康美 × 吸睛）
```
A POV candid shot of the 22-year-old female influencer walking down a sunny
street in Los Angeles. Looking back at the camera with a bright smile.
Wearing tight pastel pink yoga pants and a matching sports bra, showcasing a
toned hourglass figure. Golden hour lighting, motion blur in background,
street style photography, high fashion look, attractive yet wholesome.
--ar 3:4 --v 6.0
```

### 場景 C — 度假 / 沙灘風（高流量吸睛密碼）
```
An aesthetic medium shot of the 22-year-old female influencer sitting by an
infinity pool in Bali, ocean background. Wearing an elegant emerald green
one-piece, wet hair pushed back, minimalist gold jewelry. Sun-kissed glowing
skin, natural and confident expression, high-end travel blogger vibes, soft
cinematic lighting, detailed water ripples, masterpiece. --ar 3:4 --v 6.0
```

### 場景 D — 咖啡廳午後穿搭（日常 × 高級感）
```
A candid lifestyle photo of the 22-year-old female influencer sitting in an
aesthetic minimalist café, soft afternoon window light. Wearing a fitted
white tank top and beige tailored trousers, a matcha latte on the marble
table, looking slightly off-camera with a soft smile. Morandi color palette,
film-photography texture, instagram aesthetic, 8k. --ar 3:4 --v 6.0
```

### 場景 E — 深夜居家感性（Soft POV / 製造親密感）
```
A warm dim home portrait of the 22-year-old female influencer on a couch at
night, only a soft warm lamp lighting her face. Wearing a simple grey
loungewear set, hair loosely down, a dreamy slightly wistful expression
looking into the camera, cozy intimate POV mood, detailed skin, cinematic
soft focus, 8k. --ar 3:4 --v 6.0
```

---

## 3. 一致性工作流 (Consistent Character)

1. **刷種子臉：** 用「基礎設定 Prompt」生成多張，挑一張最滿意的當「基準臉（seed face）」。
2. **鎖臉：**
   - **Midjourney：** 用 `--cref <基準臉圖片URL>`（可加 `--cw 100` 強制臉部一致）。
   - **Stable Diffusion：** 用 IP-Adapter / ReActor / InstantID 等臉部參考，或訓練專屬 LoRA。
   - **Higgsfield (本專案常用)：** 用 5–15 張基準圖訓練一個 Soul，再以該 Soul ID 生成各場景（參考 `sofia-vargas/profile.json` 的 `ai_assets` 結構）。
3. **批次生成：** 基準臉鎖定後，固定基礎設定，只替換場景區塊，產出整套內容。
4. **存檔：** 採用圖的 job/檔案資訊建議比照其他 KOL，記錄回 `profile.json`，並把圖放進 `kols/chloe-lin/images/`。

---

## 4. 後續操作建議

1. **種子圖建立：** 先用基礎 Prompt 刷出滿意臉孔 → 選定基準臉 → 鎖臉。
2. **腳本自動化：** 把本檔 + `profile.json` 餵給 Claude，要求批次產出「一週 IG 企劃（視覺構圖 + 對應文案）」。
3. **影片化：** 種子圖可接 image-to-video（參考 `docs/01-video-generation-quick-ref.md` 與 Sofia 的 self-intro 製作流程）做成 Reels。
