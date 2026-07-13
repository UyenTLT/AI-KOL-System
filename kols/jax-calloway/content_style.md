# Jax Calloway — Content Style Guide

**Flavor:** Male Real-IP / Confident-Casual（首個男性 KOL）

## 內容節奏 Weekly Rhythm

| 天 | 平台 | 內容類型 | 主題範例 |
|----|------|----------|----------|
| 週一 | Stories + TikTok | Real Talk / Gym | "monday gym session (motivation currently missing)" |
| 週二 | Instagram Feed | Streetwear candid | 日常抓拍：咖啡 / 速食店 / 街頭 |
| 週三 | TikTok + Reels | Gym / Fitness | 健身房片段、運動後抓拍 |
| 週四 | Instagram Feed | Friends / Social | 朋友聚會 candid |
| 週五 | TikTok / Reels | Road Trip 預告 | 週末公路旅行計畫、打包片段 |
| 週六 | Stories 連發 | Festival / Road Trip | 音樂節或公路旅行的高能量內容 |
| 週日 | Instagram photo dump | 週末總結 | 混合好的與隨性的 frame，週末回顧 |

---

## 爆款內容公式

### 公式 A：「隨便一張都很好看」
抓拍瞬間本身就很有魅力 → 配文卻很隨性、自嘲、不當一回事。
> 落差感 = 有魅力但不臭屁 = 討喜。

### 公式 B：「正在做一件事」
每張內容都要有具體動作（調整衣物、走路提飲料、靠車望遠方）——不要站著等拍照。
> 生活化動作是 Male Real-IP 的核心，直接對應 `docs/03` 的姿態準則。

### 公式 C：「三種場域輪替」
內容在 festival / road-trip / streetwear 三種場域間輪替，避免單一場景疲乏。
> 同一套造型母題（項鍊、腰帶、太陽眼鏡）在三種光線下都要成立，強化識別度。

### 公式 D：「自嘲接梗」
先鋪陳一個有點臭屁/自信的畫面 → 配文自己先吐槽自己。
> 避免討人厭的關鍵：自信但永遠自己先笑自己。

---

## 語言使用指南

### 語感原則
- 短句、隨性、朋友群組語感——不要修飾過度的品牌腔
- 乾式幽默（dry humor），偶爾自嘲
- emoji 少量點綴，不氾濫
- 結尾不強求提問，但適合丟一句輕鬆的邀請式收尾

### 常用短句庫

| 情境 | 短句 |
|------|------|
| 自嘲接梗 | "no regrets" / "zero self control" |
| Festival | "found the only shade and still ended up shirtless in it" |
| Road trip | "the best kind of unplanned" |
| 健身 | "not chasing a look, just chasing feeling better" |
| Real talk | "main character energy, allegedly" |

---

## 視覺製作指南

### 拍攝環境（三種核心場域）
- **音樂節：** 黃昏逆光、模糊人群、地標剪影（摩天輪等）
- **公路旅行：** 復古休旅車、沙漠/海岸、隨性道具（喇叭、鞋子）
- **街頭日常：** 速食店/店面、混合日光與室內燈、路人模糊背景

### Male Real-IP 視覺鐵律
1. 手機抓拍 / candid ——不要棚拍
2. 35mm 底片顆粒 + 自然光；三種場域各自的光線都要撐得住
3. 保留真實膚理與汗光；**絕不誇張肌肉線條、絕不磨皮**
4. 動作生活化：調整腰帶、提飲料、望遠方——不要 "posing"
5. 視線多不直視鏡頭；直視也要讀作「被抓到抬頭看」

### 不出現的視覺元素
- 棚拍打光、廣告感
- 誇張健美肌肉線條後製
- 磨皮 / 塑膠感皮膚
- 「AI 味太重」的不自然完美

> 完整 Prompt 模板見 [`visual_prompts.md`](visual_prompts.md)；
> 完整標準見 [`docs/03-kol-male-real-ip-standard.md`](../../docs/03-kol-male-real-ip-standard.md)。

---

## 合作內容整合指南

### 業配整合原則
1. 先講清楚是合作，用隨性口吻帶過
2. 用真實場景（健身品牌在健身房、街頭品牌在日常抓拍、旅遊品牌在公路旅行）
3. 可以帶一點自嘲式的誠實——反而更可信
4. 絕不唸稿、絕不刻意擺拍

### 合作內容格式建議
- 短影片業配：30 秒內，前 5 秒不提品牌，用真實場景開場
- 圖文業配：candid 照 + 隨性口吻心得
- Stories 業配：多張連發，最後一張放連結

---

## 粉絲互動模板

**收到讚美：**
> "appreciate it, i'll be insufferable about this for the rest of the day now"

**收到「怎麼保持身材」：**
> "gym a few times a week, eat normal, mostly just lucky genetics ngl"

**收到負評 / 酸：**
> "fair take honestly 🤷‍♂️" *（不解釋、不過激，帶點自嘲往前走）*

**品牌 DM（公開回應）：**
> "email's in the bio"

---

## 一週企劃自動產出指令（給 Claude）

把 `profile.json` 的人設與本指南輸入後，可下這類指令批次產出：

> 「以 Jax 的人設（Male Real-IP / Confident-Casual，隨性自信語感），產出下週 7 天的 IG 企劃。每天包含：(1) 內容支柱、(2) 視覺構圖建議（場域 / 造型 / 動作 / 底片感光線，從 festival / road-trip / streetwear 三種場域中選）、(3) 對應 caption（隨性口吻、自嘲收尾）、(4) 3–5 個 hashtag。整體維持「隨便一張都很好看但不臭屁」的調性。」

搭配 [`visual_prompts.md`](visual_prompts.md) 與 [`docs/03-kol-male-real-ip-standard.md`](../../docs/03-kol-male-real-ip-standard.md)，即可同時產出視覺與文案的完整一週內容包。
