# Brooke Sinclair — Soul v1 訓練圖批次清單

**KOL：** `brooke-sinclair`
**模型：** `soul_2`（Higgsfield Soul 2.0），style `General`
**規格：** `3:4` / 1536×2048 PNG
**成本：** ≈0.12 credit / 張
**建立日期：** 2026-06-28
**狀態：** ✅ **完成** — 8 張全數產生並已下載至 `soul_v1_training/`。

> 一致性錨點（每張必含）：鉑金長波浪髮、亮藍綠色杏眼、淡金膚色（fair to light golden）、
> 沙漏身材、soft-glam clean-girl 妝、自然皮膚質感、青春感（youthful fresh-faced）、
> SFW（性感靠時尚與氣場，不露點 / 不成人內容）。
>
> **標準臉孔（Canonical Face）：** 第 06 張（`06_pilates_activewear.png`）——較年輕、更有性感張力，
> 為用戶確認的 Brooke 正確樣貌。第 01–05 張已按此標準重抽以收斂一致性。

---

## 最終批次（已下載）

| # | 檔名 | 角度 / 場景 | job_id | seed | 狀態 |
|---|------|-------------|--------|------|------|
| 01 | `01_portrait_frontal.png` | 正臉特寫，studio 白背景 | `6a664c06-3867-4978-9deb-399aa02b8dd7` | 823124 | ✅ |
| 02 | `02_threequarter_right.png` | 3/4 右側臉，室內窗光 | `e3586090-03be-4389-b9fc-a12d1707578f` | 757211 | ✅ |
| 03 | `03_threequarter_left.png` | 3/4 左側臉，golden hour 戶外 | `03af9357-b280-4431-8088-dd268065a711` | 652558 | ✅ |
| 04 | `04_fullbody_street_ootd.png` | 全身街拍 OOTD，West Hollywood | `42299b66-33fb-4372-adff-a122301506db` | 648817 | ✅ |
| 05 | `05_home_mirror_selfie.png` | 居家全身鏡子自拍 | `ae8f5542-616b-4fc7-bbb7-6867bba5b41a` | 568136 | ✅ |
| 06 | `06_pilates_activewear.png` | 普拉提 / 運動套裝，3/4 身 ⭐ | `14a97563-5d43-45e6-bdae-4b6f5758300f` | 11343 | ✅ |
| 07 | `07_gaming_setup.png` | 遊戲椅 + 耳機，medium shot | `914c1f57-9aa5-4521-86c7-b385bfc86231` | 107029 | ✅ |
| 08 | `08_night_glam.png` | 夜間 glam，黑色 bodycon | `b3f0503f-356b-4fa5-b178-7204d54fded4` | 221126 | ✅ |

> ⭐ = 標準臉孔（Canonical Face）。第 06–08 張為用戶確認風格正確的原始批次。第 01–05 張為第二批，按修訂 base prompt 重抽以對齊第 06 張的年輕感與性感氣場。

共用 base prompt 前綴（第 01–05 張修訂版，更強調鉑金、淡金膚色、青春感）：
```
A 25-year-old white American woman, long platinum blonde hair in soft loose waves, bright blue-green almond-shaped eyes, fair light golden skin, naturally fit hourglass figure, soft-glam clean-girl makeup with nude and rosy tones, dewy luminous skin, high cheekbones, full lips, youthful fresh-faced alluring look, photorealistic, natural skin texture, shot on 35mm
```

第 06–08 張原始 base prompt 前綴：
```
A 25-year-old white American woman, long platinum-to-golden blonde hair in soft loose waves, blue-green almond-shaped eyes, sun-kissed golden tan skin, naturally fit hourglass figure, soft-glam 'clean girl' makeup, high cheekbones, photorealistic, natural skin texture, shot on 35mm
```

---

## 生成方式與一致性備註

- **採純文字（text-only）生成**：每張以 base prompt + 場景 modifier 直出，未使用 reference image。
- **為何不用 reference image**：Higgsfield `soul_2` 接收 reference media 時會自動啟用
  `enhance_prompt`，將所有 prompt 改寫成「正面特寫」，導致場景 / 角度多樣性全失（已驗證）。
  純文字才能保住全身 / 場景多樣性，是 Soul 訓練集的必要條件。
- **面孔收斂策略（Option B）**：用戶確認第 06 張為 Brooke 的標準臉孔（較年輕、性感、吸引男性）。
  第 01–05 張以修訂 base prompt（強調 platinum blonde、fair to light golden skin、youthful）
  重抽，以拉近與 06–08 張的風格距離。
- **小瑕疵**：第 07 張（gaming）椅背有 AI 生成的假 logo 文字，不影響訓練。

---

## 後續步驟
1. 確認本批 8 張人物特徵一致後，上傳至 Higgsfield 訓練 Soul v1（5–20 張）。
2. 取得 `soul_id` 回填 `profile.json` → `ai_assets.soul_v1.higgsfield_soul_id`，狀態改 `ready`。
3. 之後所有內容圖一律帶 `soul_id` 生成，確保跨鏡頭人物一致。
