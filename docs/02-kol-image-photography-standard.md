# KOL 圖像生成攝影標準（Film Candid Default）

**版本：** v1.0  
**制定日期：** 2026-06-29  
**適用範圍：** `Buildup_KOL/kols/` 所有 KOL 的靜態圖像生成  
**工具：** Higgsfield Soul（`soul_2` 模型 + KOL 專屬 `soul_id`）

> 本標準源自 Brooke Sinclair `soul_v3_film_candid` 系列的驗證結果。
> 35mm 膠片感 + 自然光 + candid 無修感被確認為跨 KOL 的最佳預設視覺語言。
> **所有 KOL 靜態圖像生成，須以本標準作為預設起點，除非場景明確需要另一種風格。**

---

## 核心風格定義：Film Candid

### 視覺特徵
| 維度 | 標準描述 |
|------|---------|
| 相機感 | 35mm 底片機，類比攝影質感，輕微噪點顆粒 |
| 光線 | 自然光為主：溫暖陽光、柔和窗光、黃金時刻、樹影斑駁；避免閃光燈、棚燈 |
| 後製感 | 無感後製：自然膚色、毛孔可見、微微露出光澤但不磨皮 |
| 構圖 | Candid 抓拍感——非刻意擺拍的自然姿態，主角看似剛被拍到 |
| 色調 | 暖調、輕微降飽和、有機底片色彩；非冷藍、非過度對比 |
| 情緒 | 真實、放鬆、有個性——生活的真實瞬間，而非廣告棚拍感 |

### 標準風格後綴（每張 prompt 必加）
```
shot on 35mm film camera, film grain, analog photography aesthetic,
candid natural light, warm sun-drenched, authentic unstaged moment,
natural skin texture, no heavy retouching
```

---

## Prompt 公式

### 基本結構
```
[KOL 外型描述（透過 soul_id 注入）] + [場景 + 服裝 + 姿態] + [Film Candid 標準後綴]
```

### 範例（以 Brooke Sinclair 為例）
```
Platinum blonde wavy hair, wearing a triangle bikini top and cat-eye sunglasses,
holding an iced coffee cup in one hand and a suede tote bag on shoulder,
walking down a sunny tree-lined street in West Hollywood,
confident casual stride, slightly looking at camera,
shot on 35mm film, film grain, warm summer sunlight,
analog photography aesthetic, authentic candid lifestyle shot
```

> 外型細節（髮色、眼色、膚色）透過 `soul_id` 自動注入，prompt 中僅需描述服裝與場景，
> 無需重複 KOL 的外型描述。

---

## Higgsfield 生成參數規範

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `model` | `soul_2` | 所有 KOL 圖像生成統一使用 |
| `soul_id` | KOL 專屬 ID（見各 `profile.json` → `ai_assets.primary_soul_id`） | 必填，確保跨鏡人物一致性 |
| `aspect_ratio` | `3:4`（1536×2048） | 垂直 IG / TikTok 格式，與 Soul 訓練集一致 |
| `medias` | ❌ 不帶 reference image | 帶 reference 會觸發 `enhance_prompt`，破壞場景多樣性 |
| `enhance_prompt` | `false`（預設，不帶 reference 時自動關閉） | 確保 prompt 忠實執行 |

---

## 核心四大服裝 / 場景類別

以下四類為 Film Candid 標準驗證通過的核心場景，KOL Agent 生成時優先從此清單取材：

| # | 場景代碼 | 場景描述 | 代表服裝 | 代表道具 |
|---|---------|---------|---------|---------|
| A | `wet-hair-portrait` | 游泳後 / 海灘剛上岸肖像 | 比基尼上衣、泳衣肩帶 | 白色薄紗窗簾背景、毛巾 |
| B | `street-candid` | 街拍 / 日常外出全身 | 比基尼上衣 + 短裙、crop top、帽 T | Iced coffee、墨鏡、麂皮托特包 |
| C | `bikini-lounge` | 泳池 / 海灘 lounge 悠閒 | 細帶比基尼、繩結比基尼 | Lounge chair、飲料、墨鏡 |
| D | `cover-up` | 輕覆蓋 cover-up 晨間 / 度假 | 超大白色亞麻襯衫、男友 T-shirt | Iced coffee / matcha、手機 |

> 完整 prompt 公式見 `.claude/commands/kol-generate-image.md`

---

## 生活化動作準則

**核心原則：** 每張圖的主角必須「有在做一件事」，而非只是站著等拍照。

| 好的動作（生活化）| 避免的描述（廣告感）|
|-----------------|------------------|
| 撩濕髮往後撥 | `posing for camera` |
| 拿 iced coffee 走路中回頭 | `professional model pose` |
| 靠欄杆看遠處 | `smiling at camera`（改用 `soft smile` 或 `subtle smirk`） |
| 整理比基尼肩帶 | `standing straight looking forward` |
| 低頭滑手機 | `symmetrical pose` |
| 在 lounge 懶洋洋翻雜誌 | `hands on hips` |

**視線不必對準鏡頭：**
- `direct gaze into camera` — 偶用，適合肖像
- `looking slightly off-camera` — 最自然
- `gazing into the distance` — 度假感、思考感
- `looking down at phone / coffee` — 日常感最強

---

## 場景分類與風格微調

### A. 日常生活（預設 Film Candid）
適用：戶外街拍、咖啡廳、居家、健身、海灘、泳池

風格後綴：
```
shot on 35mm film camera, film grain, candid natural light,
warm sun-drenched, authentic unstaged moment, natural skin texture
```

### B. 夜間 / 派對 / 夜店
光線從自然光改為：`warm ambient bar lighting` / `neon glow` / `cinematic night lighting`

風格後綴：
```
shot on 35mm film camera, film grain, warm ambient night lighting,
candid candid night out energy, authentic party moment, natural skin
```

### C. 室內軟光（GRWM / 居家）
光線改為：`soft diffused window light` / `warm morning indoor light`

風格後綴：
```
shot on 35mm film camera, film grain, soft diffused natural window light,
cozy indoor warmth, candid unstaged home moment, natural skin texture
```

### D. 黃金時刻（Golden Hour）
```
shot on 35mm film camera, film grain, golden hour warm backlight,
sun-kissed glow, candid outdoor lifestyle, natural skin texture
```

---

## 禁止事項

| 禁止 | 原因 |
|------|------|
| ~~`reference image` / `medias`~~ | 觸發 `enhance_prompt`，強制轉成正面特寫，喪失場景多樣性 |
| ~~`studio lighting` / `ring light` / `flash`~~ | 破壞 Film Candid 的自然光感 |
| ~~`smooth skin` / `airbrushed` / `perfect skin`~~ | 造成磨皮感，喪失真實感 |
| ~~`HDR` / `vibrant colors` / `ultra sharp`~~ | 色調過飽和，破壞底片溫暖色調 |
| ~~過多外型描述~~ | `soul_id` 已注入外型；過多描述反而干擾 soul 鎖定 |

---

## 各 KOL soul_id 快查

| KOL | ID | Primary Soul ID | Soul 版本 |
|-----|----|----------------|----------|
| Brooke Sinclair | brooke-sinclair | `a88ed2a4-a62f-454e-9829-216f505fc560` | soul_v3 |
| Sofia Vargas | sofia-vargas | 待建 | — |
| 香香 | xiang-xiang | 待建 | — |
| 謝宜蓁 | xie-yizhen | 待建 | — |

> 所有 KOL 的 soul_id 以各自 `profile.json` → `ai_assets.primary_soul_id` 為準。

---

## 輸出與存檔規範

```
kols/{kol-id}/images/
├── soul_v{n}_training/          # Soul 訓練圖
├── soul_v{n}_verification/      # 驗證圖（確認人物一致性）
└── soul_v{n}_{batch-name}/      # 內容圖批次，命名描述場景風格
    ├── 01_{scene}.png
    ├── 02_{scene}.png
    └── ...
```

每批生成後：
1. 以 `job_display` 確認結果
2. 下載至對應目錄
3. 更新 `profile.json`（如有新 soul 版本）
4. `git add` → `git commit` → `git push`
