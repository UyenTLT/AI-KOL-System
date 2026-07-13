# Lena Chen — Visual Prompts & Consistency Workflow

Local-first image/video pipeline for a photoreal, identity-consistent 甜妹 KOC.
Stack rationale + hardware in `research/local-ai-companion/09-realistic-visual-stack.md`.

---

## 1. 生成堆疊 (Generation stack — local-first)

| 用途 | 工具 | 備註 |
|------|------|------|
| 出圖 base | **Flux.1-dev** (GGUF on NVIDIA / MPS on Mac) | Mac 只能出圖且慢 3-5×，不能訓 LoRA |
| 鎖臉 identity | **character LoRA**（NVIDIA 24GB 自訓）或 **PuLID-Flux**（免訓 fallback）+ ReActor | LoRA = 本地版「soul」 |
| 去 AI 感 realism | Amateur-Snapshot / UltraReal / Skin-Detailer LoRA + 低 CFG (2.5-3.5) | 見下方反 AI 四層法 |
| 對嘴影片 | Wav2Lip（Mac 勉強）/ MuseTalk・LivePortrait（NVIDIA） | 語音來自 §voice（IndexTTS-2/CosyVoice2） |
| 短動態影片 | LTX-Video / Wan2.x（NVIDIA） | Mac 幾乎不可行 |
| 便宜 API fallback | Runware / fal（Seedream）| 只在量大或無 GPU 時 burst |

## 2. 一致性流程 (Consistency — the "local soul")

1. 用 `ai_prompts.base_character_prompt`（見 profile.json）出 15-25 張同一張臉的乾淨圖。
2. 人工挑臉最一致的當 **canonical face set** → 訓練 character LoRA（或建 PuLID 參考）。
3. 之後所有場景圖 = base prompt + LoRA/PuLID 鎖臉 + 場景 block（見 §4）。
4. 沿用 repo 既有 **soul_v1_training → soul_v2_verification → soul_v3_content** 的版本化資料夾慣例，
   放進 `kols/lena-chen/images/`。記錄 LoRA 檔名／PuLID 參考於 `profile.json → ai_assets`。

## 3. 反「AI 感」四層法 (Anti-AI-look recipe)

1. **生成層**：掛 realism/skin LoRA + 降 CFG（2.5-3.5），避免塑膠感。
2. **提示層**：加 phone-camera / candid / natural light / minor imperfection 關鍵字。
3. **後製層**：film grain + face-detailer 補毛孔 + 輕微色偏。
4. **動作層**：日常抓拍動作（正在做某事），不要棚拍死站。
> 專打三個露餡點：臉過度對稱、皮膚無毛孔、打光太戲劇。

## 4. 場景庫 (Scene blocks)

> base prompt 見 `profile.json → ai_prompts.base_character_prompt`；以下接在其後。
> Negative（SD）：見 `profile.json → ai_prompts.negative_prompt_sd`。

- **A 真心話開箱桌**：`sitting at a cozy pastel desk holding a skincare product to camera, ring-light catchlight, tidy product flatlay, warm window light`
- **B 甜妹 GRWM 鏡子自拍**：`mirror selfie getting ready, applying soft-glam makeup, pastel knit, phone in hand, sunlit bright bedroom`
- **C 咖啡廳好物開箱**：`aesthetic Taipei café, shopping bag + cute beauty products beside a matcha latte, laughing off-camera, soft afternoon light, film texture`
- **D 甜妹街頭穿搭**：`POV walking a sunny street (LA/Taipei), looking back, pastel mini skirt + fitted cardigan, golden hour, gentle motion blur`
- **E 深夜留言回覆**：`warm dim cozy bedroom, soft lamp, holding phone replying to followers, loungewear, intimate POV, sincere expression`

## 5. 影片與聲音 (Video + voice)

- 短影片＝關鍵幀鎖臉 → I2V（LTX/Wan，或便宜 API burst）。
- 對嘴＝TTS 語音（IndexTTS-2 精修 / CosyVoice2 即時）→ Wav2Lip/MuseTalk → RVC 統一音色。
- 語音設定見 `profile.json → ai_assets.voice` 與 `research/local-ai-companion/10-local-voice-stack.md`。

## 6. 尺度 (Boundary)

甜、可愛、一點 純欲 線條即可；**never explicit / NSFW**。保留真實膚質，不變形身材。
