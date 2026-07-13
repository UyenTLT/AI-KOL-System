# Lin Wan-Ching — Visual Prompts & Consistency Workflow

目標美感：**同 `kols/xie-yizhen` 的自然 film-candid 路線**（35mm Kodak Portra、自然窗光、真實膚質、
暖調顆粒），獨立臉孔。Local-first 於 Apple Silicon。

---

## 1. 生成堆疊 (Stack)

| 用途 | 工具 | 備註 |
|------|------|------|
| seed 出圖 (soul_v1) | **RealVisXL (SDXL)** via diffusers + **MPS** | M1 Pro 本地，~2.5 分/張 @ 832×1216，guidance ~4.5 |
| 鎖臉 (production) | 遷移到 **Flux + character LoRA / PuLID** + ReActor | 跨圖一致性；見 research/09 |
| 對嘴 / 影片 | MuseTalk / LivePortrait（需 NVIDIA）| Mac 不可，burst cloud |

> ⚠️ CLIP 限 77 token：prompt 前段（film、自然美、低髮髻、杏眼、微笑）最重要，寫在最前面；
> 過長的尾段會被截斷。要用完整長 prompt 可改用 `compel` 加權。

## 2. 一致性流程 (Consistency)

1. 用 `ai_prompts.base_character_prompt` 出 15–20 張同一臉孔的 seed 圖 → `images/soul_v1_training/`。
2. 人工挑臉最一致者為 canonical set → 訓練 character LoRA（需 NVIDIA 或 cloud burst）。
3. 之後場景圖 = base + LoRA/PuLID 鎖臉 + 場景 block。
4. 沿用 repo 版本化：`soul_v1_training → soul_v2_verification → soul_v3_content`；記錄於 `profile.json → ai_assets`。

## 3. 反「AI 感」重點 (Anti-AI-look)

自然窗光、film 顆粒、真實膚質與毛孔、暖調不過曝、留白構圖、日常抓拍動作。
避免：棚拍白背、閃光、塑膠磨皮、過度對稱臉、豔麗過曝。

## 4. 場景庫 (Scene blocks)

> 接在 `profile.json → ai_prompts.base_character_prompt` 之後；Negative 見 `negative_prompt_sd`。

- **A 自然光肖像**：`gentle smile looking off toward the window, cream tee, cozy sunlit room`
- **B 雨天窗邊茶**：`side profile gazing out a rainy window, holding a warm ceramic cup of tea, contemplative`
- **C 咖啡廳閱讀**：`by a bright cafe window with an open book and a flat white, looking down reading, soft afternoon light`
- **D 晨間手沖**：`making pour-over coffee at a minimalist sunlit kitchen counter, morning light, calm`
- **E 底片散步**：`walking a quiet old street holding a vintage film camera, warm late-afternoon light, candid`

## 5. 生成指令 (Repro)

種子腳本：`scratchpad/gen_wanqing.py`（RealVisXL + MPS）。範例：
`./sd-venv/bin/python gen_wanqing.py portrait window cafe kitchen`

## 6. 尺度 (Boundary)

溫柔得體、自然美；**never explicit / NSFW**。保留真實膚質，不變形、不過曝豔麗。
