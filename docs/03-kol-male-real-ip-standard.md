# KOL 男性圖像生成標準（Male Real-IP Candid）

**版本：** v1.0
**制定日期：** 2026-07-05
**適用範圍：** `Buildup_KOL/kols/` 男性 KOL 的靜態圖像生成（首個範例：`jax-calloway`）
**工具：** Seedream（`seedream_v4_5`）+ Higgsfield Reference Element

> 本標準源自使用者提供的 3 張男性參考照片（音樂節黃金時刻、沙漠公路旅行、速食店街拍）
> 的分析結果 —— 三張照片在完全不同場景與光線下，人物一致性與生活感都維持在極高水準。
> 本文件延伸 [`docs/02-kol-image-photography-standard.md`](02-kol-image-photography-standard.md)
> 的 Film Candid 核心美學，只記錄**男性專屬的差異**：身分錨點、造型母題、姿態準則、
> 三種場域類型。共通的底片感 / 生活化動作 / 禁止事項請直接參照 `docs/02`。
>
> ⚠️ **參考照片僅作為「風格 / 標準」提取來源，不複製該真實個人的臉孔或身分。**
> 依本 repo 既有慣例（比照 `@11.mzzz` 之於 Mika Tran），新建的男性 KOL 一律使用
> **原創身分**，僅提取其構圖、光線、造型與一致性方法論。

---

## 生成堆疊：Seedream + Reference Element（非 Soul）

Higgsfield **Soul** 僅支援 `soul_2` / `soul_cinema`，Seedream 不適用。男性 KOL 的人物一致性
改用 **Reference Element**：

1. 用 Seedream 生成一批基準臉（文字生成，無需任何真人參考圖）。
2. 挑選最一致、最符合人設的一張，`show_reference_elements(action='create')` 存成 Element。
3. 之後所有內容圖：`generate_image(model='seedream_v4_5', prompt="... <<<element_id>>> ...")`，
   讓後端自動注入該 Element 對應的臉孔／識別特徵，維持跨場景人物一致。

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `model` | `seedream_v4_5`（或視覺品質需求用 `seedream_v5_lite`） | 依使用者指示，男性/女性 KOL 皆以 Seedream 為主力生成模型 |
| `aspect_ratio` | `3:4` | Seedream 原生支援，不會被系統修正 |
| Element 注入 | prompt 中嵌入 `<<<element_id>>>` | 取代文字外型描述，鎖定臉孔一致性 |
| `medias` | 除 Element 注入外不額外帶 reference image | 避免不必要的 `enhance_prompt` 干擾 |

---

## 核心風格定義：Male Real-IP Candid

在 `docs/02` 的 Film Candid 基礎上，男性版本強調「有能力感的自信」而非單純性感展示——
肌肉線條與造型是敘事的一部分，不是唯一焦點。

| 維度 | 標準描述 |
|------|---------|
| 相機感 | 35mm 底片機，類比攝影質感，輕微噪點顆粒（同 `docs/02`） |
| 光線 | 自然光為主：黃金時刻逆光、沙漠平光、混合室內螢光——三種真實場域各自的光線都要撐得住 |
| 後製感 | 保留皮膚真實質感（汗光、毛孔），**不磨皮、不誇張肌肉線條後製** |
| 構圖 | Candid 抓拍——正在做一件事（調整腰帶、走路拿飲料、低頭），而非站直擺拍 |
| 色調 | 暖調、底片有機色彩，室內場景也維持一絲暖意，避免冷白/棚拍感 |
| 情緒 | 自信、放鬆、有點漫不經心的酷——「剛好很帥」而非「刻意擺拍」 |

---

## 身分錨點（Identity Anchors — 必須跨場景維持一致）

| 部位 | 標準描述 |
|------|---------|
| 臉型 | 銳利/立體下顎線、直挺鼻樑、飽滿唇形 |
| 髮型 | 淺至中棕色微捲/凌亂瀏海，側掃或自然抓亂，非過度造型 |
| 眼睛 | 淡棕/榛色，眼神帶點漫不經心的自信 |
| 膚色 | 白皙偏健康小麥色，皮膚保留真實光澤與汗感 |
| 體態 | 精瘦運動型（gym-lean）——腹肌線條清晰、肩線自然，**不是健美型**、不誇張肌肉量 |

---

## 造型母題（Recurring Styling Motifs — 品牌內品牌錨點）

延續本 repo「重複道具強化識別度」的doctrine（同 Brooke Sinclair 的 iced coffee）：

- **腰帶品牌外露**（如運動內著腰帶）作為招牌造型元素，貫穿多個場景
- **疊戴項鍊**（鏈條 / 十字架或吊墜）、戒指、小耳環
- **西部 / 復古街頭配件**：雕花皮帶扣、丹寧單品、太陽眼鏡（貓眼款或方框復古款）

---

## 姿態與動作準則（Pose / Action Doctrine）

> 核心原則：主角必須「正在做一件事」，而非站著等拍照——與 `docs/02` 的生活化動作準則一致，
> 但男性版本更常見「調整衣物 / 提著東西走動 / 眼神放空望遠方」的漫不經心感。

| 好的動作 | 避免的描述 |
|---------|-----------|
| 雙手勾住腰帶或口袋，重心偏一邊 | `posing for camera` |
| 提著飲料/物品邊走邊回頭 | `professional model pose` |
| 低頭看自己在整理衣服 | `smiling at camera`（改用 `subtle smirk` 或 `confident half-smile`） |
| 靠著車輛 / 欄杆，眼神望向遠方 | `standing straight looking forward` |
| 直視鏡頭但像「被抬頭看到」而非模特凝視 | `symmetrical pose` / `hands on hips` |

---

## 三種核心場域類型（Scene Genres）

以下三種場域對應參考照片分析出的真實敘事類型，男性 KOL 內容生成優先從此取材：

### A. `festival-golden-hour` — 音樂節 / 戶外活動黃金時刻
**造型：** 赤膊或敞開襯衫、疊戴項鍊、太陽眼鏡、彩色手環堆疊、腰帶外露的運動內著
**背景：** 音樂節场地地標（摩天輪 / 舞台剪影）、模糊人群、黃昏漸層天空
**光線：** `golden hour warm backlight, sun-kissed sweat sheen, hazy dusk sky`
**動作：** 勾腰帶、側身望向遠方、被抓拍的自信瞬間

**Prompt 結構：**
```
<<<element_id>>>, shirtless or open shirt, layered necklace, sunglasses, festival wristbands,
[動作], at an outdoor music festival at golden hour, blurred crowd and ferris wheel silhouette
in the background, warm backlight, sun-kissed skin with natural sweat sheen,
shot on 35mm film, film grain, authentic candid festival moment, natural skin texture
```

### B. `road-trip-casual` — 公路旅行 / 戶外悠閒
**造型：** 赤膊或家居 T、寬鬆運動長褲、項鍊、球鞋（可脫放在地上）
**背景：** 復古休旅車、沙漠 / 海岸荒地、隨性道具（藍牙喇叭、行李）
**光線：** `flat hazy daylight, soft late-afternoon light`
**動作：** 低頭調整衣物、倚車而站、隨性不經意的瞬間

**Prompt 結構：**
```
<<<element_id>>>, casual loungewear or shirtless with sweatpants, necklace, sneakers kicked
off nearby, [動作], leaning against a vintage off-road vehicle on a desert coastal cliff,
flat hazy daylight, relaxed road-trip mood,
shot on 35mm film, film grain, authentic unstaged moment, natural skin texture
```

### C. `streetwear-candid` — 街頭穿搭 / 日常外出
**造型：** 削袖丹寧襯衫或街頭單品、疊戴銀飾、復古太陽眼鏡、雕花皮帶扣
**背景：** 速食店 / 街邊店面、混合日光與室內燈、路人模糊背景
**光線：** `mixed indoor fluorescent and daylight, neutral-warm balance`
**動作：** 提著飲料走出店門、被抬頭抓拍的直視鏡頭

**Prompt 結構：**
```
<<<element_id>>>, sleeveless denim shirt with silver hardware, layered silver necklaces,
retro sunglasses, engraved belt buckle, holding drinks walking out of a storefront,
[動作], mixed fluorescent and daylight indoor-outdoor lighting, blurred passersby background,
shot on 35mm film, film grain, authentic street candid moment, natural skin texture
```

---

## 禁止事項

同 `docs/02`，額外強調：

| 禁止 | 原因 |
|------|------|
| ~~exaggerated bodybuilder muscle~~ | 破壞「gym-lean 自然感」，偏向不真實的健美廣告感 |
| ~~studio lighting / ring light / flash~~ | 破壞 Film Candid 的自然光感 |
| ~~smooth skin / airbrushed / perfect skin~~ | 造成磨皮感，喪失真實感 |
| ~~explicit / nsfw~~ | 維持主流、品牌安全尺度——自信有魅力，但不露骨 |

---

## 各 KOL Element 快查

| KOL | ID | Primary Element ID | 生成模型 |
|-----|----|--------------------|---------|
| Jax Calloway | jax-calloway | 待建 | seedream_v4_5 |

> 所有男性 KOL 的 element_id 以各自 `profile.json` → `ai_assets.primary_element_id` 為準。

---

## 輸出與存檔規範

```
kols/{kol-id}/images/
└── seedream_v1/                 # 內容圖批次
    ├── 01_canonical_face.png
    ├── 02_{scene}.png
    └── ...
```

每批生成後：
1. 以 `job_display` 確認結果（一致性、光線自然感、無 AI 瑕疵）
2. 下載至對應目錄
3. 更新 `profile.json`（`ai_assets.primary_element_id` 等）
4. `git add` → `git commit` → `git push`
