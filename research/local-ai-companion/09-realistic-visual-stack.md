# 09 — 本地端「像真人」視覺生成技術棧 / Local Photorealistic Visual Stack

> **Status（2026-07-13）**：draft。本文件回答一個新目標——**讓 KOL「看起來像真人、沒有 AI 味」，
> 同時把「靜態圖 + talking-head 影片」的產線盡量搬到本地端（省 API／省資源）**。
>
> **與前面文件的關係**：
> - `docs/02-kol-image-photography-standard.md` + `.claude/commands/kol-generate-image.md`：目前靜態圖
>   走 **Higgsfield Soul（`soul_2` 雲端 API）** + `soul_v1/v2/v3` 迭代訓練，風格預設 **Film Candid**
>   （35mm 底片、自然光、無修）。本文件的目標是把這條產線的「引擎」換成**本地可跑的等價物**，
>   但**沿用 Film Candid 的視覺語言與去 AI 味原則**（兩者理念一致，見第 2 節）。
> - `04-realtime-avatar-integration.md`：已選定 **LiveTalking（Wav2Lip/MuseTalk）** 作為**即時直播**
>   talking-head 整合對象。本文件**不重複即時直播路線**，只補上「**離線、單支高品質短影片**」的
>   talking-head 與短影片方案（產內容用，非直播用），並和 04 對齊硬體分流。
> - `03-phase1-detailed-design.md`：對話核心（persona→prompt→LLM）不受本文件影響；本文件只動「視覺
>   呈現層」。
>
> 一句話定位：**03 = 會聊天的靈魂；04 = 會即時直播的臉；09 = 平常發文用、看起來像真人的圖與短影片。**

---

## 0. 目標與驗收 / Goals & Acceptance

| # | 條件 | 驗收方式 |
|---|---|---|
| A | 靜態圖可**本地生成**，人物臉部**跨圖一致**（等同現行 `soul_id` 的作用） | 同一角色連生 20 張，路人辨識為「同一個人」 |
| B | 產出**沒有明顯 AI 味**（膚質、光、瑕疵、手機感） | 縮圖級盲測，非專家難分辨 AI/真人 |
| C | 能產**talking-head 短影片**（嘴型對嘴、輕微頭動） | 給一張圖 + 一段語音 → 對嘴影片 |
| D | 明確標出**何時必須用 API**，並給最便宜 fallback | 見第 6 節決策表 |

**硬前提**：像真人的本地影像生成需要 GPU。**NVIDIA（CUDA）為一等公民**；Apple Silicon 可跑圖但慢、
影片/對嘴受限（見第 5 節）；純 CPU/AMD 不建議。

---

## 1. 靜態圖生成：模型底座選型 / Base Model for Stills

### 1.1 結論：以 **Flux.1** 取代 SDXL 當「像真人」的底座

2025–2026 的共識：**Flux.1 dev（12B DiT）開箱即比任何 SDXL 微調更接近真人**——膚質、光影、手部
解剖、prompt 理解都更好，因為模型大 5 倍、訓練集更精。SDXL 的優勢只剩「LoRA 生態龐大」（CivitAI
5000+ vs Flux ~500+），但對「像真人」這個單一目標，Flux 底座勝出。([Will It Run AI][wr-flux]、
[InsiderLLM][insider])

| 底座 | 像真人（開箱） | 一致性工具 | VRAM（量化後） | 本案建議 |
|---|---|---|---|---|
| **Flux.1 dev** | ★★★★★ | LoRA / PuLID-Flux / IPAdapter | Q4~Q8 GGUF ≈ 6–12GB | **主力**（品質圖） |
| **Flux.1 schnell** | ★★★★ | 同上 | 同上，1–4 步超快 | 批量草圖 / 低配 |
| **SDXL（RealVis 等）** | ★★★☆ | InstantID / IP-Adapter 生態最全 | 6–8GB | 低配、需大量現成 LoRA 時 |
| **FLUX.2 klein（4B）** | ★★★★ | LoRA（新，較少） | Q4 ≈ 2.6GB，4 步 | 8GB 以下 / 極省 VRAM 新選擇 |

> 低 VRAM 關鍵：用 **city96 的 GGUF 量化**（Q4_K_S≈6.8GB、Q5_K_S≈保 95% 品質）＋ `--lowvram`
> 權重從系統 RAM 串流；**T5 文字編碼器也要用量化版**（fp16 的 T5 單獨就 ~9GB，8GB 卡放不下）。
> 更省可看 **Nunchaku / SVDQuant（4-bit）** 加速。([Local AI Master][lam-flux]、[Apatero][apa-gguf])

### 1.2 臉部一致性：四條路線（對應現行 `soul_id`）

現行 Higgsfield `soul` = 「用幾張訓練圖 → 得到一個一致的臉 ID → 之後純文字生成都鎖臉」。本地端有
四種等價機制，可單用或疊用：

| 方法 | 原理 | 一致性 | 表情/角度自由度 | 訓練成本 | 對應 soul 概念 |
|---|---|---|---|---|---|
| **角色 LoRA**（Flux）| 用 15–30 張同人臉微調一顆 LoRA | ★★★★★（最穩，等同 soul_v2/v3 再訓練）| 高 | 需訓練（20–40 min/RTX 4090）| **最貼近 `soul_v{n}` 迭代訓練** |
| **PuLID-Flux II** | InsightFace 抽臉特徵，免訓練注入 | ★★★★ | 中（表情較受限）| 免訓練 | 快速起臉、無訓練資料時 |
| **InstantID**（SDXL）| 臉關鍵點 + IP-Adapter | ★★★☆（82–86% 相似）| 中 | 免訓練 | SDXL 底座時的等價物 |
| **IP-Adapter FaceID / ReActor 換臉** | 生成後把「標準臉」貼回去 | ★★★★（後處理硬鎖）| 高（姿態不受限）| 免訓練 | **收尾保險**，鎖死身分 |

**推薦組合（最像現行 soul 工作流）**：
1. 先為每個 KOL 訓練一顆 **Flux 角色 LoRA**（= 建立這個角色的「本地 soul」，命名沿用
   `soul_v{n}` 語意，見第 4 節）。
2. 生成時 **LoRA 為主**；臉若飄，事後用 **ReActor / IP-Adapter FaceID** 以一張「canonical face」
   把臉鎖死（等同 chloe-lin profile 裡的 `canonical_face_job_id` 概念）。
3. 純起步、還沒有 LoRA 訓練圖時，用 **PuLID-Flux** 免訓練頂著先出圖。

> PuLID 的已知弱點：**跨圖不易保持完全一致、表情較僵**；InstantID 表情較平衡但相似度略低；
> 角色 LoRA 仍是「跨圖同一人」的天花板。([MyAIForce][mya-pulid]、[Apatero][apa-face])

---

## 2. 去「AI 味」/ 增真實感技術（本文件核心價值）

現行 Film Candid 標準（35mm 底片、自然光、毛孔可見、無磨皮、candid 抓拍）**理念完全正確**，本地端
可以把它做得比雲端 API 更徹底，因為我們能疊 LoRA + 後處理節點。分四層：

### 2.1 模型/LoRA 層（生成當下）

| 手段 | 作用 | 具體 |
|---|---|---|
| **Amateur Snapshot LoRA** | 破除「攝影棚完美感」，加隨手拍不完美 | Civitai `Amateur Snapshot Photo`（trigger 隨模型）([Civitai][civ-amateur]) |
| **UltraReal / InstaPic LoRA** | 社群媒體真實感、硬閃光、手機直出 | trigger：`shot on iphone / hard flash / candid / smartphone photo`([Civitai][civ-ultra]、[Civitai][civ-insta]) |
| **Skin Detailer（DoRA）** | 毛孔、細毛、雀斑、痘、膚色不均 | Civitai `Flux Skin Detailer` / `Photorealistic Skin No-plastic`([Civitai][civ-skin]) |
| **降 CFG / 加噪** | 太高 guidance = 塑膠感；適度降低更真 | Flux guidance ~2.5–3.5、加 Detail-Daemon 節點 |

### 2.2 Prompt 層（沿用並強化 Film Candid 後綴）

沿用 `docs/02` 的標準後綴，並補「手機/瑕疵」關鍵詞：
```
shot on iPhone, casual snapshot, candid, slightly imperfect framing, mild motion blur,
visible skin pores and texture, subsurface scattering, natural uneven skin tone,
35mm film grain, warm natural window light, no makeup look, no retouching
```
沿用 `docs/02` 的**禁止詞**（`smooth skin / airbrushed / HDR / ultra sharp / vibrant / studio lighting`），
本地端一樣適用。

### 2.3 後處理層（生成後，ComfyUI 節點串）

真實感常靠「先生成乾淨圖 → 再破壞一點」：
- **加底片顆粒**：`LayerFilter: FilmV2`（`grain_strength≈0.05` 起）
- **臉部細節重繪**：SD1.5/專用 skin model 做 face-detailer，把塑膠臉重採樣成粗糙自然膚質
- **色彩/曲線**：輕微降飽和、暖調、加輕微色偏（模擬手機/底片非中性白平衡）
- **輕微壓縮/銳度不均**：模擬社群平台二次壓縮的「不完美」
（來源：ComfyUI 官方 realism workflow、MyAIForce Fix-Plastic-Skin、Prompting Pixels）([ComfyUI.org][cui-skin]、[MyAIForce][mya-plastic]、[Prompting Pixels][pp-real])

### 2.4 「別過頭」原則
去 AI 味是**加噪與不完美**，不是加銳度與飽和。三個最常見的 AI 破綻：對稱到不自然的臉、零毛孔的
塑膠膚、過度戲劇化的打光——本節三層專打這三點。**與 `docs/02` 的「生活化動作」準則搭配**（主角在做
一件事、視線不必對鏡頭）效果最好。

---

## 3. 動態：talking-head 與短影片（本地）

### 3.1 定位切分（避免和 04 重複）

| 用途 | 需求 | 方案 | 文件 |
|---|---|---|---|
| **即時直播**（互動、可打斷）| realtime ≥25fps | **LiveTalking（Wav2Lip/MuseTalk）** | 見 `04` |
| **離線發文短影片**（單支高品質對嘴）| 品質 > 即時 | 見下表 | **本文件** |
| **純運鏡/氛圍短片**（無對嘴）| I2V 動態 | Wan / LTX（見 3.3）| **本文件** |

### 3.2 離線 talking-head 方案比較

| 方案 | 驅動方式 | 品質 | 本地 VRAM | 即時？ | Mac | 適用 |
|---|---|---|---|---|---|---|
| **Wav2Lip** | 音訊→嘴 | ★★☆（只動嘴，可能糊）| ~4–8GB | 準即時 | ✅(MPS,慢) | 最省、快 draft |
| **SadTalker** | 音訊→臉+頭動 | ★★★ | ~8GB | 否（批次）| ⚠️ | 單圖出頭動說話 |
| **LivePortrait**（快手）| 影片/表情驅動 | ★★★★（表情細）| ~8–12GB | 近即時 | ⚠️部分 | 表情遷移、最擬真臉部 |
| **MuseTalk**（騰訊）| 音訊→嘴（latent inpaint）| ★★★★（30+fps）| ~8–12GB | ✅ | ❌ | 高品質對嘴、也可即時 |
| **Hallo2/Hallo3**（復旦）| 音訊→全臉（diffusion）| ★★★★★（長片穩、抗身分漂移）| ~16–24GB+ | 否（慢）| ❌ | 最高品質、長 talking 片 |
| **Wan2.2 S2V / InfiniteTalk** | 音訊→全身表演+對嘴 | ★★★★★ | GGUF Q4 ~25–30GB / FP8 45–50GB | 否 | ❌ | 全身、無限長、最強但最重 |

（來源：Pixazo / lipsync.com 開源對嘴評比、ComfyUI blog Wan2.2-S2V、Wan-AI HF）([Pixazo][px-lip]、[ComfyUI blog][cb-s2v]、[HF][hf-wan])

**建議**：
- **消費級主力**：**LivePortrait**（臉部表情最自然、近即時）＋ **MuseTalk**（嘴型品質高）搭配。
- **要頂級單支片**且有 16–24GB：**Hallo2**。
- **有 24GB+ 且要全身表演**：**Wan2.2 S2V / Animate + InfiniteTalk**（也可做無對嘴運鏡）。

### 3.3 純動態短影片（I2V，無對嘴，做氛圍 Reels）

| 模型 | 消費級可行性 | 品質 | 備註 |
|---|---|---|---|
| **LTX-Video 2.x** | ★★★★（8–12GB fp8 最順）| ★★★☆ | 每幀最快、低配首選 |
| **Wan 2.1/2.2 14B** | ★★★（GGUF+CPU offload 可壓到 6–8GB GPU）| ★★★★★ | 品質最佳、較慢 |
| **HunyuanVideo** | ★★（FP8+tiling ~8GB，門檻高）| ★★★★ | 重、非首選 |

（來源：Will It Run AI VRAM 指南、RunAIHome Wan 指南、LTXWorkflow 對比）([Will It Run AI][wr-vram]、[RunAIHome][rah-wan]、[LTXWorkflow][ltxw])

---

## 4. 建議技術棧（依硬體分級）/ Recommended Stack by Hardware

### 4.1 NVIDIA 消費級 GPU（一等公民）

| VRAM | 靜態圖 | 一致性 | 去 AI 味 | talking-head | 短影片 |
|---|---|---|---|---|---|
| **8GB**（3060 8G/4060）| Flux **GGUF Q4** 或 FLUX.2 klein | PuLID-Flux（免訓練）+ ReActor 收尾 | Snapshot+Skin LoRA + FilmV2 | **Wav2Lip**（~4–8GB）| **LTX-Video**（低配）|
| **12GB**（3060 12G/4070）| Flux dev **GGUF Q5/Q6** | **角色 LoRA**（本地 soul）+ ReActor | 全套 2.1–2.3 | **LivePortrait / MuseTalk** | **Wan2.1**（GGUF+offload）|
| **16GB**（4060Ti 16G/4080）| Flux dev fp8/Q8 | 角色 LoRA + PuLID | 全套 | MuseTalk / **Hallo2** | Wan2.2 14B / LTX |
| **24GB**（3090/4090）| Flux dev **全精度**，可本地訓 LoRA | 角色 LoRA 本地訓練（20–40min）| 全套 + face-detailer | **Hallo2 / Wan2.2 S2V** | Wan2.2 / Hunyuan |

> 24GB 是甜蜜點：**能本地訓角色 LoRA**（自產「soul」不靠雲端）+ 跑最高品質對嘴。
> chat 模式若同機跑 LLM（見 `04` 第 4 節），注意 VRAM 競合——出圖/出片時通常不同時跑 LLM，衝突小。

### 4.2 Apple Silicon（Mac，二等公民，能做但受限）

| 能力 | 狀態 | 說明 |
|---|---|---|
| Flux 出圖（ComfyUI + MPS）| ✅ 可跑但慢 | M3/M4 Max 出 1024² 約 **85–180 秒**（RTX 4090 為 12–18 秒），**慢 3–5×**；建議 ≥32GB 統一記憶體、用 GGUF([Apatero][apa-mac]) |
| 角色 LoRA / PuLID / IP-Adapter | ⚠️ 部分 | 出圖端可用；**訓練 LoRA 不建議在 Mac 做**（極慢）|
| Wav2Lip | ✅ 可（Easy-Wav2Lip 支援 M1/2/3，MPS）([Local AI][loc-mac]) | 品質普通但能本地 |
| LivePortrait | ⚠️ 部分社群成功、非官方保證 | |
| **MuseTalk / Hallo2 / Wan / Hunyuan** | ❌ 實質不可行 | 依賴 CUDA-only 運算元；Mac 上跑不動或極慢 |

**Mac 現實建議**：Mac 適合**出靜態圖（慢但能離線）+ Wav2Lip 級對嘴**；**高品質對嘴與影片生成請用
NVIDIA 機或退 API**。訓練角色 LoRA 一律用 NVIDIA。

### 4.3 本地 soul 迭代（沿用現行 v1/v2/v3 語意）

把 Higgsfield 的迭代訓練搬到本地 Flux LoRA：
- **soul_v1（local）**：8–15 張種子臉（可先用雲端/現有素材）→ 訓第一顆 Flux 角色 LoRA。
- **soul_v2（local）**：用 v1 生成的高品質內容圖回訓，強化跨場景一致性（同現行做法）。
- **soul_v3（local）**：加入影片抽幀/多角度，做最終穩定版。
- 收尾一律配 **ReActor canonical face** 硬鎖身分。

---

## 5. 何時「必須」用 API + 最便宜 fallback / When API Is Mandatory

**必須用 API 的情境**：
1. **完全沒有 NVIDIA GPU 且 Mac 也扛不住**（要影片/高品質對嘴）→ 本地路線斷。
2. **要即時大量產能**（一天上百張品質圖 / 多支影片），本地單卡吞吐不夠。
3. **趕時程、不想處理 CUDA/ComfyUI 依賴地獄**（`04` 已記載此摩擦）。

**最便宜 fallback（2026 行情，1024² 每張）**：

| 供應商 | Flux schnell / 開源模型 | 備註 |
|---|---|---|
| **Runware / Together AI** | **~$0.0006–0.003 /張**（最便宜，聚合開源權重）| 高量產首選，比原廠 API 省 50–70% |
| **fal.ai** | schnell ~$0.003/MP；Seedream V4 ~$0.03/張 | 現行 chloe-lin 用的 Seedream 就在此區間 |
| **Replicate** | Flux ~$0.003–0.04/張 | 生態成熟 |

（來源：pricepertoken、fal pricing、SiliconFlow 便宜模型整理）([PricePerToken][ppt]、[fal][fal-price]、[SiliconFlow][sf-cheap])

**決策原則**：**靜態圖優先本地（成本趨近 0）**；**影片/對嘴** 若無 24GB 卡，短期用 API（fal.ai
Seedream/Kling 影片、或 Wan API）比買卡快。**混合策略**：本地產「臉一致的關鍵幀」→ 丟便宜影片 API
做 I2V，兼顧一致性與成本。

---

## 6. 落地步驟 / Implementation Steps

> 目標：把一個現有 KOL（建議 `chloe-lin`，已有 `ai_assets` 結構）跑通「本地出一致像真人的圖 → 一支對嘴短片」。

1. **裝環境**：ComfyUI（NVIDIA：CUDA 版；Mac：`--use-pytorch-cross-attention --force-fp16`）+
   `ComfyUI-GGUF`(city96) + `ComfyUI-Manager`。
2. **下模型**：依 4.1 選 Flux GGUF 檔位 + 量化 T5 + VAE；抓 realism LoRA（Amateur Snapshot、
   UltraReal/InstaPic、Skin Detailer）。
3. **建本地 soul_v1**：收 8–15 張 `chloe-lin` 種子臉 → 訓 Flux 角色 LoRA（24GB 本地訓；否則先 PuLID
   免訓練頂著）。
4. **出圖驗證 A+B**：用 `docs/02` Film Candid 後綴 + 2.2 手機/瑕疵詞 + realism LoRA，連生 20 張，
   確認同一人（A）+ 盲測無 AI 味（B）。臉飄的用 ReActor 收尾。
5. **對嘴短片 C**：挑一張定稿圖 + 一段語音（GPT-SoVITS 克隆該角色聲，見 `04`）→ **LivePortrait 或
   MuseTalk**（低配 Wav2Lip）出一支 talking-head。
6. **（可選）氛圍 Reels**：定稿圖 → **LTX/Wan** I2V 出無對嘴運鏡短片。
7. **回填 profile**：把本地 LoRA 路徑/canonical face 寫進 `kols/{id}/profile.json.ai_assets`
   （見第 7 節欄位建議），存檔 → commit。

---

## 7. 與 `kols/` 及 soul 產線的整合點 / Integration

1. **`profile.json.ai_assets` 擴充**（沿用現有 `soul_v{n}` 命名，新增本地欄位；不改 schema 必填）：
   ```jsonc
   "ai_assets": {
     "generation_model": "flux-dev-local",        // 由 seedream/soul_2 → 本地
     "consistency": "character_lora + reactor",
     "local_soul_v1": {
       "engine": "flux.1-dev-gguf-q6",
       "lora_path": "kols/chloe-lin/loras/soul_v1_flux.safetensors",
       "canonical_face": "kols/chloe-lin/images/canonical_face.png",  // ReActor 鎖臉來源
       "realism_loras": ["amateur-snapshot", "skin-detailer"],
       "status": "pending"
     }
   }
   ```
2. **沿用 `docs/02` Film Candid 標準**：prompt 後綴、生活化動作、禁止詞照舊；本文件的 2.2 手機/瑕疵詞
   是「加強包」，不是取代。
3. **與 `/kol-generate-image` skill 對齊**：可新增一個 `--engine local` 分支，soul_id → 本地 LoRA
   路徑；工作流與現行 Higgsfield 版一致（選場景 → 套後綴 → 生成 → 驗一致性 → 存檔）。
4. **與 `04` 對齊**：本文件產的**定稿圖/影片**可當 LiveTalking `/avatar.html` 的形象來源；聲音共用
   GPT-SoVITS 克隆。**09 出素材、04 拿去即時直播**，不重工。
5. **不改 `03`**：對話核心、persona→prompt 完全不動。

---

## 8. 風險與限制 / Top Risks

1. **NVIDIA GPU 是硬前提**：像真人的本地影片/對嘴/LoRA 訓練實質 CUDA-only。**Mac 只能做圖 + Wav2Lip
   級對嘴**，高品質動態一定得 NVIDIA 或退 API——這是最大結構限制。
2. **一致性 vs 真實感的張力**：鎖臉工具（LoRA/ReActor）鎖太死會回到「每張同角度同表情」的 AI 味；
   realism LoRA/降 CFG 加太多又可能傷一致性。需逐角色調平衡，且**臉部一致性天花板仍是角色 LoRA**
   （PuLID/InstantID 免訓練但跨圖較不穩、表情僵）。
3. **依賴地獄與維運成本**：ComfyUI/CUDA/PyTorch 版本敏感（`04` 已記載），LoRA 訓練需時間與 24GB 卡；
   模型/LoRA 更新快（Flux→FLUX.2、Wan2.1→2.2→2.7），需持續跟進，否則品質落後雲端。
4. **（延伸）合規**：仍是全 AI 虛擬角色、無真人肖像問題；但多地要求 AI 生成內容揭露（見 `07`），
   對嘴影片上架前確認平台規範。

---

## 附：來源 / Sources

- Flux vs SDXL 真實感：[Will It Run AI][wr-flux]、[InsiderLLM][insider]
- 臉一致性（PuLID/InstantID/IP-Adapter）：[MyAIForce][mya-pulid]、[Apatero][apa-face]
- 去 AI 味 / 膚質：[ComfyUI.org][cui-skin]、[MyAIForce][mya-plastic]、[Prompting Pixels][pp-real]
- realism LoRA：[Amateur Snapshot][civ-amateur]、[UltraReal][civ-ultra]、[InstaPic][civ-insta]、[Skin Detailer][civ-skin]
- 低 VRAM Flux GGUF：[Local AI Master][lam-flux]、[Apatero GGUF][apa-gguf]
- talking-head 評比：[Pixazo][px-lip]、[ComfyUI blog S2V][cb-s2v]、[Wan-AI HF][hf-wan]
- 短影片 VRAM：[Will It Run AI VRAM][wr-vram]、[RunAIHome][rah-wan]、[LTXWorkflow][ltxw]
- Apple Silicon：[Apatero Mac][apa-mac]、[Local AI Wav2Lip Mac][loc-mac]
- API 價格：[PricePerToken][ppt]、[fal pricing][fal-price]、[SiliconFlow][sf-cheap]

[wr-flux]: https://willitrunai.com/blog/flux-vs-sdxl-vs-sd35-comparison
[insider]: https://insiderllm.com/guides/best-photorealism-checkpoints-local-image-generation/
[mya-pulid]: https://myaiforce.com/flux-pulid-vs-ecomid-vs-instantid/
[apa-face]: https://apatero.com/blog/instantid-vs-pulid-vs-faceid-ultimate-face-swap-comparison-2025
[cui-skin]: https://comfyui.org/en/boost-texture-and-skin-realism-with-comfyui
[mya-plastic]: https://myaiforce.com/fix-plastic-skin/
[pp-real]: https://www.promptingpixels.com/tutorial/how-to-make-ai-images-look-more-realistic-in-comfyui
[civ-amateur]: https://civitai.com/models/970862/amateur-snapshot-photo-style-lora-flux
[civ-ultra]: https://civitai.com/models/796382/ultrarealistic-lora-project
[civ-insta]: https://civitai.com/models/2168120/instapic-ultrareal-the-authentic-social-media-lora-or-realism-flux-or-zit-or-flux-2-klein
[civ-skin]: https://civitai.com/models/1018511/flux-skin-detailer-realistic-skin-dora
[lam-flux]: https://localaimaster.com/blog/run-flux-on-low-vram-gpu
[apa-gguf]: https://apatero.com/blog/flux-gguf-quantization-8gb-vram-guide-2026
[px-lip]: https://www.pixazo.ai/blog/best-open-source-ai-lip-sync-models
[cb-s2v]: https://blog.comfy.org/p/wan22-s2v-in-comfyui-audio-driven
[hf-wan]: https://huggingface.co/Wan-AI/Wan2.2-Animate-14B
[wr-vram]: https://willitrunai.com/blog/video-generation-gpu-guide-2026
[rah-wan]: https://runaihome.com/blog/wan-video-local-ai-gpu-guide-2026/
[ltxw]: https://ltxworkflow.com/blog/ltx-2-3-vs-hunyuanvideo-vs-wan2-2-comparison-2026
[apa-mac]: https://www.apatero.com/blog/flux-apple-silicon-m1-m2-m3-m4-complete-performance-guide-2025
[loc-mac]: https://locally-ai.com/2024/07/15/20-Mac%20Easy-Wav2Lip/
[ppt]: https://pricepertoken.com/image
[fal-price]: https://fal.ai/pricing
[sf-cheap]: https://www.siliconflow.com/articles/en/the-cheapest-image-gen-models
