# Sofia Hsu — Visual Prompts

**建立：** 2026-08-14（recast 後第一版；舊的拉丁裔影像資產已全數刪除）
**風格取向：** Flavor 1 純欲風（反差萌）× 房規預設 **Film Candid**（`docs/02-kol-image-photography-standard.md`）
**預設比例：** `--ar 3:4`（1536×2048）
**尺度界線（不可協商）：** 成年角色、主流 IG 等級、**永不露骨**。可愛與性感靠**臉與身形的反差**，不靠裸露。

---

## 0. 為什麼這批圖必須「從零開始」

`kols/sofia-vargas/profile.json` 裡的 **Soul v1 / v2 / v3 全部鎖著拉丁裔那張臉**。
用它們生圖只會再生出舊的 Sofia。而且 `profile.json` **根本沒有 `primary_soul_id` 這個欄位**
（`docs/02` 的快查表也寫著「待建」），所以 `/kol-generate-image` 的 Step 1 會直接停住。

因此這一版的流程是**反過來的**：

```
先用【無 soul_id 的純文字 prompt】刷種子臉
   → 挑一張基準臉
   → 用 5–15 張同臉圖訓練 Soul v4
   → 之後所有內容圖才帶 soul_id 生成
```

**第 2 節就是「刷種子臉」那一步——也就是這次要的那張全新圖。**

---

## 1. 外型鎖定（Identity Lock）

Recast 後的外型，與 [character.md](character.md) 一致。**這份設定一旦訓練成 Soul v4 就不要再改**，
改了等於換人。

| 項目 | 設定 |
|---|---|
| 年齡感 | 22，臉要「還沒完全長開」的少女感，不要輕熟 |
| 族裔 | 台裔美國人（East Asian / Taiwanese-American） |
| 臉型 | 柔和心形臉，臉頰帶一點嬰兒肥 → **可愛的那一半** |
| 眼睛 | 深棕杏眼、雙眼皮、眼尾微微下垂（無辜感、有點睏） |
| 鼻 | 小巧直鼻，**鼻樑上有淡淡雀斑** |
| 唇 | 唇形飽滿，放鬆時微嘟 |
| 髮 | 黑棕色長髮、中分、直髮尾端微捲、有修飾臉型的層次、略帶凌亂 |
| 膚 | 偏白暖調，**毛孔可見、保留真實質感**，濕潤感淡妝 |
| 身形 | 165 cm，纖細但有線條，腰線明顯、鎖骨清楚 → **性感的那一半** |
| 風格 | 日常性感：合身羅紋背心／短版上衣、低腰牛仔褲、金色細鍊疊戴 |

### 一致性錨點（Soul 鎖臉的關鍵，每張圖都要出現）

1. **左眼下方一顆小痣**
2. **鼻樑上的淡雀斑**
3. **三條金色細項鍊疊戴**
4. **左耳三個耳洞**

> 這四項是刻意設計的。Soul 訓練靠反覆出現的細節收斂；沒有錨點的臉，換場景就會換人。

---

## 2. ⭐ 種子臉 Prompt（這次要生的那張新圖）

反差萌的配置：**臉負責可愛（圓頰、雀斑、下垂眼），身形與穿搭負責性感（腰線、鎖骨、合身背心）**，
再用 Film Candid 的自然光與底片顆粒把它拉回真實感，避免變成廣告棚拍。

```
A ultra-realistic candid portrait of a 22-year-old Taiwanese-American woman,
soft heart-shaped face with gently rounded cheeks, warm dark-brown almond eyes with
double eyelids and slightly downturned outer corners giving a sweet innocent look,
small straight nose with faint natural freckles across the bridge, full lips with a
soft resting pout, a small beauty mark below her left eye.
Long black-brown hair, middle part, straight with softly curled ends and face-framing
layers, slightly messy. Fair warm-toned skin with visible pores and real texture,
minimal dewy makeup, glossy lip.
Slim athletic figure with a clear waistline, soft natural curves and defined collarbones.
Wearing a fitted cream ribbed tank top and low-rise light-wash jeans, three thin gold
necklaces layered, small gold hoop earrings, three piercings on her left ear.
Sitting sideways on the arm of a couch by a window in a lived-in Los Angeles apartment,
one knee pulled up, tucking her hair behind her ear and glancing up as if caught
mid-sentence, subtle smirk.
Soft diffused natural window light, warm late afternoon.
shot on 35mm film camera, film grain, analog photography aesthetic, candid natural light,
authentic unstaged moment, natural skin texture, no heavy retouching
```

**呼叫格式**（照 `.claude/commands/kol-generate-image.md` Step 5，**刻意不帶 `soul_id`、不帶 `medias`**）：

```python
mcp__higgs__generate_image({
  "params": {
    "model": "soul_2",
    "aspect_ratio": "3:4",
    "prompt": "<上面整段>"
    # ❌ 無 soul_id —— 這一步是在「創造」臉，不是「重現」臉
    # ❌ 無 medias —— 會觸發 enhance_prompt，強制轉正面特寫
  }
})
```

**建議刷 8–12 張再挑**。種子臉是往後每一張圖的地基，值得多抽幾次。

### Stable Diffusion 用的 Negative Prompt

```
explicit, nsfw, nudity, deformed, extra fingers, bad anatomy, oversaturated,
heavy smoothing, plastic skin, airbrushed, HDR, studio lighting, ring light, flash,
watermark, logo, text, multiple people
```

---

## 3. 挑基準臉的標準

刷出來後照這四條挑，**不要挑最漂亮的，挑最像「同一個人」的**：

1. **四個錨點都清楚**（左眼下痣、鼻樑雀斑、三條項鍊、左耳三洞）
2. **臉是可愛的、身形是有線條的**——兩邊只要有一邊沒到位就重抽，反差是整個人設的鉤子
3. **皮膚看得到毛孔**。磨皮 = 廢圖
4. **不是在對鏡頭擺姿勢**，是「剛好被拍到」

---

## 4. Soul v4 訓練圖清單（基準臉定了之後）

15 張，場景照 `docs/02` 的四大類分佈。**服裝與場景換，四個錨點不換。**

| # | 檔名 | 場景 |
|---|---|---|
| 01 | `closeup_neutral` | 正面特寫，自然光，素顏感 |
| 02 | `threequarter_right` | 四分之三側臉，右 |
| 03 | `threequarter_left` | 四分之三側臉，左 |
| 04 | `car_selfie` | 車內自拍，午後光 |
| 05 | `mirror_bedroom` | 臥室鏡子自拍，寬鬆背心 |
| 06 | `boba_shop` | 手搖店等飲料，低頭滑手機 |
| 07 | `laughing_couch` | 沙發上大笑，室內軟光 |
| 08 | `golden_hour_street` | 聖蓋博谷街頭中英雙語招牌，逆光 |
| 09 | `gym_set` | 健身房，運動內衣＋緊身褲，擦汗中 |
| 10 | `mom_kitchen` | 媽媽家廚房，靠流理台吃東西 |
| 11 | `surprised` | 誇張驚訝表情（縮圖用） |
| 12 | `night_out` | 夜晚外出，暖色環境光 |
| 13 | `hiking` | 週末爬山，素顏，硬光 |
| 14 | `speaking_gesturing` | 講話比手勢（影片幀取樣用） |
| 15 | `beach_day` | 海灘，比基尼上衣＋短褲，主流 IG 等級 |

存到 `kols/sofia-vargas/images/soul_v4_training/`，驗證圖 5 張存
`soul_v4_verification/`，然後把 `higgsfield_soul_id` 寫回 `profile.json`
→ `ai_assets.soul_v4`，**並補上目前不存在的 `ai_assets.primary_soul_id`**。

---

## 5. 內容圖場景庫（Soul v4 ready 之後才用）

帶 `soul_id`，**prompt 裡不要再重複外型描述**（`docs/02`：重複描述會干擾 soul 鎖定），
只寫場景＋服裝＋動作＋風格後綴。

**A｜手搖店（她的招牌場景）**
```
Wearing a cropped white tee and a pleated mini skirt, standing at the counter of a
Taiwanese bubble tea shop in the San Gabriel Valley, holding a plastic cup, looking
down at the menu board with a slight frown of concentration.
shot on 35mm film camera, film grain, candid natural light, warm sun-drenched,
authentic unstaged moment, natural skin texture
```

**B｜臥室鏡子自拍（純欲風核心）**
```
A candid phone mirror selfie, wearing an oversized cream knit sweater slipping off one
shoulder and shorts, hair messy, innocent expression with a playful smirk, sunlit
bedroom with an unmade bed.
shot on 35mm film camera, film grain, soft diffused natural window light,
cozy indoor warmth, candid unstaged home moment, natural skin texture
```

**C｜街頭穿搭（626 golden hour）**
```
Wearing a fitted black tank top and baggy low-rise jeans, walking past bilingual
Chinese-English shop signs on a San Gabriel Valley street, iced drink in hand,
looking back over her shoulder mid-stride.
shot on 35mm film camera, film grain, golden hour warm backlight, sun-kissed glow,
candid outdoor lifestyle, natural skin texture
```

**D｜健身房（線條，但不色情）**
```
Wearing a sage green sports bra and matching leggings, sitting on a bench between sets,
head tilted back, catching her breath, gym in soft background blur.
shot on 35mm film camera, film grain, candid natural light, authentic unstaged moment,
natural skin texture
```

**E｜深夜沙發（軟 POV）**
```
Wearing a simple grey loungewear set, curled up on the couch at night lit only by a warm
lamp, hair loosely down, dreamy slightly wistful expression looking into the camera.
shot on 35mm film camera, film grain, warm ambient indoor lighting, cozy intimate mood,
natural skin texture
```

---

## 6. 禁用詞（`docs/02` 禁止事項）

| 禁用 | 原因 |
|---|---|
| `posing for camera` / `professional model pose` / `hands on hips` | 廣告感，殺掉 candid |
| `smiling at camera` | 改用 `soft smile` / `subtle smirk` |
| `studio lighting` / `ring light` / `flash` | 破壞 Film Candid 自然光 |
| `smooth skin` / `airbrushed` / `perfect skin` | 磨皮，失去真實感 |
| `HDR` / `vibrant colors` / `ultra sharp` | 過飽和，破壞底片暖調 |
| `medias` / reference image | 觸發 `enhance_prompt`，強制正面特寫 |
| 帶 soul_id 時重複外型描述 | 干擾 soul 鎖臉 |
| 任何露骨、暴露、未成年暗示的描述 | 房規紅線，無例外 |
