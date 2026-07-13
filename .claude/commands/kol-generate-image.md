# /kol-generate-image — KOL 靜態圖像生成 Skill

> 本 Skill 是 KOL Agent 生成靜態圖像的**唯一入口**。
> 所有生成必須遵守本 Skill 定義的攝影標準、場景分類、服裝類型與動作準則。
> 完整技術文件：`docs/02-kol-image-photography-standard.md`

---

## 使用方式

```
/kol-generate-image [KOL-ID] [場景類型] [數量]
```

**範例：**
```
/kol-generate-image brooke-sinclair street 3
/kol-generate-image brooke-sinclair bikini-lounge 5
/kol-generate-image brooke-sinclair cover-up 2
```

---

## Step 1：從 profile.json 取得 soul_id

```
kols/{kol-id}/profile.json → ai_assets.primary_soul_id
```

必填，所有圖像生成皆需帶入。若 `soul_status` 不是 `ready`，停止並提示用戶先完成 Soul 訓練。

---

## Step 2：選擇場景類型

### 核心四大場景（Film Candid 驗證通過的標準服裝類別）

以下四類場景為 KOL 對外內容的核心展示，生成優先從此清單取材：

---

#### A. `wet-hair-portrait` — 游泳後 / 海灘剛上岸
**場景定位：** 最貼近 candid 原始感的主力肖像。展示自然美、皮膚質感、自信的隨性氣場。

**服裝：** 比基尼上衣 / 泳衣肩帶 / 輕薄沙灘蓋巾
**髮型：** 濕髮自然散落，不刻意整理
**背景：** 白色薄紗窗簾、飯店浴室、沙灘更衣間、游泳池邊

**生活化動作範例：**
- 用毛巾隨意擦頭髮，側臉偷看鏡頭
- 雙手撩起濕髮往後撥，眼神直視
- 靠著牆，眼神放空，微微噘嘴
- 低頭看手機，陽光打在臉頰

**Prompt 結構：**
```
[髮型] wet hair loose and wavy after swimming, wearing [比基尼 / 泳衣 top],
[動作], [背景], close-up portrait or medium shot,
shot on 35mm film camera, film grain, soft diffused natural light through sheer white curtains,
authentic candid beach moment, natural dewy skin, no makeup look
```

---

#### B. `street-candid` — 街拍 / 日常外出
**場景定位：** 展示全身比例與 LA 生活美學的主力 OOTD 格式。

**服裝選項（按季節 / 目的選一）：**
- 比基尼上衣 + 迷你短裙或牛仔短褲（最強視覺衝擊）
- Crop top + 高腰裙 / 牛仔褲
- 運動上衣 + 瑜珈褲（健身後外出）
- 日常輕便：oversized 帽 T + biker shorts

**必帶道具（至少一項）：**
- Iced coffee / iced latte（Brooke 的人設道具）
- 麂皮托特包 / 藤編包
- 墨鏡（cat-eye 或 retro 款）
- AirPods

**背景：** 有樹蔭的街道、咖啡廳外、停車場牆面、West Hollywood 商圈

**生活化動作範例：**
- 走路中回頭看，順手撥頭髮
- 拿著 iced coffee 走路，另一手滑手機
- 在店門口查看包包裡的東西
- 站在路邊等 Uber，隨性靠牆

**Prompt 結構：**
```
Full body candid street photography, [髮型] hair, wearing [服裝],
[道具]，[動作],
walking down a sunny tree-lined street in West Hollywood,
shot on 35mm film, film grain, warm summer sunlight,
analog photography aesthetic, authentic candid lifestyle shot
```

---

#### C. `bikini-lounge` — 泳池 / 海灘 Lounge
**場景定位：** 展示身材線條與悠閒氛圍的高吸引力內容，同時保持 SFW。

**服裝：** 細帶比基尼、繩結比基尼、運動型泳裝（一件式）
**顏色偏好：** 白色、奶油色、黑色、棕色、動物紋（斑馬紋 / 豹紋）

**姿態（從以下選一，避免刻意 pose）：**
- 側躺在 lounge chair，腿微彎，手撐頭
- 坐在泳池邊緣，腳泡在水裡，微微低頭
- 趴著翻雜誌或看手機，頭側轉看鏡頭
- 剛從水裡出來站著，順手整理比基尼帶

**背景：** 白色戶外躺椅、LA 屋頂泳池、飯店私人泳池、Malibu 海灘沙地

**生活化動作範例：**
- 一手拿飲料，另一手撐頭，懶洋洋望著遠處
- 在 lounge 上打電話，腿交叉蹺起
- 剛推開墨鏡放在頭頂，對鏡頭微笑

**Prompt 結構：**
```
[姿態] at a sun-soaked [LA rooftop pool / Malibu beach], wearing a [顏色] [比基尼款式],
[動作], toned figure, warm golden afternoon sunlight,
shot on 35mm film grain, analog film photography,
sun-drenched authentic poolside moment, natural skin texture
```

---

#### D. `cover-up` — 輕覆蓋 Cover-up（晨間 / 度假）
**場景定位：** 最接近 IG 「軟性性感」的格式——既展示身材線條，又帶有生活感和居家溫度。

**服裝：** 
- 超大白色亞麻襯衫（僅扣下兩顆扣子）
- 薄透白色長裙 + 比基尼上衣
- 男友 oversized T-shirt（睡到自然醒款）
- 沙灘遮陽巾、sarong 式圍裙

**場景：** 飯店陽台早晨、度假屋廚房、出門前在玄關照鏡

**必帶道具：** Iced coffee / matcha latte / 手機

**生活化動作範例：**
- 靠著陽台欄杆，單手托咖啡，另一手撩髮看遠處
- 在廚房等咖啡機，隨意看手機，沒在特別 pose
- 出門前站在門口整理一下頭髮，包包掛手腕
- 坐在陽台椅子上，腿搭在欄杆上刷 IG

**Prompt 結構：**
```
Standing on a [bright apartment balcony / hotel balcony / beach house porch] in [morning / early afternoon] light,
wearing an oversized [white linen button-down / white T-shirt] as a cover-up over a bikini,
[動作], casual relaxed expression [looking off-camera / subtle smile at camera],
warm soft [morning / golden] sun, [green plants / ocean view] behind her,
shot on 35mm film camera, film grain, candid analog lifestyle photography,
LA [morning / vacation] aesthetic
```

---

## Step 3：Film Candid 攝影標準後綴（所有場景通用）

每張 prompt 結尾必帶：

```
shot on 35mm film camera, film grain, analog photography aesthetic,
candid natural light, authentic unstaged moment, natural skin texture
```

**因場景調整的光線關鍵詞：**

| 場景 | 光線關鍵詞 |
|------|-----------|
| 戶外白天 | `warm sun-drenched, dappled sunlight` |
| 晨間室內 | `soft diffused morning window light` |
| 游泳後 | `soft diffused natural light through sheer white curtains` |
| 黃金時刻 | `golden hour warm backlight, sun-kissed glow` |
| 夜間外出 | `warm ambient bar lighting, candid night out energy` |

---

## Step 4：生活化動作原則

> 「生活化」是本標準最重要的 prompt 意圖之一。

**要做：**
- 給予具體的微小動作（拉比基尼帶、撥髮、拿飲料、滑手機）
- 視線不一定對準鏡頭（45° 側視、低頭、遠眺均可）
- 帶道具（飲料、包包、手機、墨鏡）增加場景真實感
- 描述環境動態細節（陽光斜射、海風、背景模糊的路人）

**避免：**
- ~~`posing for camera`~~ — 會生成廣告棚拍感
- ~~`smiling at camera`~~ — 改為 `soft smile` 或 `subtle smirk`
- ~~`standing straight`~~ — 改為重心偏一邊、手有在做事
- ~~`professional model pose`~~ — 使 soul 輸出偏向廣告感

---

## Step 5：Higgsfield 工具呼叫格式

```python
mcp__higgsfield__generate_image({
  "params": {
    "model": "soul_2",
    "soul_id": "{primary_soul_id}",       # 從 profile.json 取得
    "aspect_ratio": "3:4",                # 預設垂直格式
    "prompt": "{場景 prompt} + {Film Candid 後綴}",
    # ❌ 不帶 medias（避免觸發 enhance_prompt）
  }
})
```

---

## Step 6：生成後作業

1. 用 `job_display` 逐張確認結果
2. 確認人物一致性（soul_id 是否正確鎖定）、光線自然感、無明顯 AI 瑕疵
3. 用 `curl` 下載至 `kols/{kol-id}/images/soul_v{n}_{batch-name}/`
4. `git add → git commit → git push`
5. 如有多人入鏡（非預期）或臉部不穩定，記錄 job_id 並重抽

---

## 常見問題

| 症狀 | 原因 | 解法 |
|------|------|------|
| 場景全變成正面特寫 | 誤帶 `medias` reference image | 移除 medias，改純文字生成 |
| 臉部一致性差 | 使用錯誤的 soul_id | 確認 `profile.json` → `primary_soul_id` |
| 畫面太廣告感 | prompt 含 `posing` / `professional` 等詞 | 改用生活化動作描述 |
| 出現多人 | prompt 提到「friends」作為主角 | 改為「blurred figures in background」 |
| 底片感不足 | 未加 Film Candid 後綴 | 補上標準風格後綴 |
