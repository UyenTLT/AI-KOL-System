# KOL 影片生成快速參考

**版本：** v1.0  
**制定日期：** 2026-06-27  
**適用範圍：** `Buildup_KOL/kols/` 所有 KOL 角色的影片內容生成  
**完整技術文件：** `virtual-strategy-lab/docs/09-ai-kol-video-skills.md`

> 本文件是 KOL 資料庫與影片生成管線的橋接文件。每次為特定 KOL 製作影片前，先查本文件確認角色資產是否齊備，再到完整技術文件查工具操作細節。

---

## KOL 生成資產清單（每位 KOL 必備）

以下資產應存放於 `kols/{kol-id}/` 目錄下：

| 資產 | 檔案名稱 | 規格要求 | 對應技術 |
|------|---------|---------|---------|
| 正臉參考圖 | `ref-face-front.png` | 1024×1024+，正面，無遮擋 | InstantID / S6-01 |
| 側臉參考圖 | `ref-face-side.png` | 1024×1024+，45° 側臉 | LoRA 訓練 / S6-02 |
| LoRA 模型 | `{kol-id}_lora_v1.safetensors` | rank 32，2000–3000 steps | S6-02 |
| LoRA 觸發詞 | 記錄在 `profile.json` → `generation.lora_trigger` | `{kol-id}_v1` 格式 | S6-02 |
| 固定 Seed | 記錄在 `profile.json` → `generation.base_seed` | 一個通過審核的基準 Seed | S6-04 |
| 聲音樣本 | `voice-sample.wav` | 3–10 秒，44.1kHz/16-bit，乾淨人聲 | CosyVoice / S8-01 |
| 膚色 LUT | `{kol-id}_skin_v1.cube` | DaVinci Resolve 匯出 | S9-03 |

---

## 各 KOL 生成資產狀態

| KOL | ID | 正臉圖 | LoRA | 觸發詞 | 固定Seed | 聲音樣本 | LUT | 備註 |
|-----|-----|-------|------|-------|---------|---------|-----|------|
| Sofia Vargas | sofia-vargas | ✅ | 待建 | — | 待定 | 待建 | 待建 | 第一優先 |
| 香香 | xiang-xiang | ✅ | 待建 | — | 待定 | 待建 | 待建 | |
| 謝奕甄 | xie-yizhen | ✅ | 待建 | — | 待定 | 待建 | 待建 | |
| Brooke Sinclair | brooke-sinclair | ✅ | 待建 | — | 待定 | 待建 | 待建 | Soul v1 訓練圖 8 張已備（待訓練 Soul） |

> 資產建立後更新此表，並在 `profile.json` 的 `generation` 欄位記錄對應值。

---

## 快速生成流程

```
1. 確認 KOL 資產清單 ✅（本文件）
   ↓
2. 載入角色聖經 character.md + content_style.md
   ↓
3. 載入 LoRA（觸發詞 + weight 0.7–0.9）+ 固定 Seed
   ↓
4. 靜態圖像生成（InstantID 輔助，S6-01）
   ↓
5. LivePortrait 加入表情動態（S6-03，α = 0.65–0.80）
   ↓
6. CosyVoice 聲音克隆配音（S8-01）
   ↓
7. Linly-Talker 對嘴同步（S8-02，Δt ≤ 30ms）
   ↓
8. Real-ESRGAN 4K 放大 + RIFE 60fps 補幀（S9-01/S9-02）
   ↓
9. 套用 KOL 專屬 LUT 色調（S9-03）
   ↓
10. 交付品質檢核（G4）
```

---

## `profile.json` 生成欄位規範

每個 `profile.json` 應包含以下 `generation` 物件：

```json
{
  "generation": {
    "lora_trigger": "{kol-id}_v1",
    "lora_weight": 0.8,
    "base_seed": null,
    "checkpoint": "realisticVisionV60B1_v51VAE",
    "ip_adapter_weight": 0.7,
    "liveportrait_alpha": 0.72,
    "voice_sample": "voice-sample.wav",
    "skin_lut": "{kol-id}_skin_v1.cube",
    "notes": ""
  }
}
```

> 建立 LoRA 後填入 `base_seed`（通過標準測試的 Seed 值）。

---

## 常見問題速查

| 問題症狀 | 可能原因 | 對應技術節 |
|---------|---------|---------|
| 跨鏡頭臉部變化大 | LoRA 未建立 / Seed 未固定 | S6-01、S6-04 |
| 表情僵硬無生氣 | LivePortrait α 值過低 | S6-03 |
| 嘴形對不上聲音 | 對嘴管線誤差 > 50ms | S8-02、S8-03 |
| 影片解析度不足 | 未跑超解析度 | S9-01 |
| 動態有殘影 | RIFE 未開 Scene Detection | S9-02 |
| 不同鏡頭膚色跳色 | LUT 未套用 | S9-03 |
