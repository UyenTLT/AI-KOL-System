# 現成方案調查 — Local AI Companion Landscape

調查目的：Phase 1（純文字）需要的東西幾乎都已經有成熟開源方案；不需要從零造輪子。本文件把
生態系拆成四層，Phase 1 只用到前兩層，後兩層留給 Phase 2/3 的 `livestream-tech-specialist` 參考。

---

## 1. 對話前端 / Persona 管理層（Frontend / Character layer）

| 方案 | 說明 | 適用性 |
|---|---|---|
| **SillyTavern** | 最成熟的開源角色扮演聊天前端，本身不跑模型，只透過 API 連接各種本地/雲端後端。定義了事實上的標準 **Character Card V2**（PNG/JSON，含 persona、開場白、world info/lorebook）。 | Persona 格式可參考，甚至直接把 `kols/{id}/profile.json` 轉成相容格式 |
| **Open WebUI** | 類 ChatGPT 介面，透過 OpenAI-compatible API 接 Ollama 等後端，多使用者、多模型管理較完整。 | 介面更通用，客製人格需自行處理 system prompt |
| **text-generation-webui (oobabooga)** | 一站式：載入模型 + 聊天介面 + 角色卡，功能最全但配置也最重。 | 適合想要「模型+介面」一體的重度玩家 |
| **LM Studio** | GUI 桌面應用，內建聊天介面 + 本地模型管理 + OpenAI-compatible server 模式。上手最快。 | 適合快速原型驗證 |
| **Jan.ai / GPT4All** | 更輕量的桌面聊天 App，內建模型下載器。 | 備選，功能通常比 SillyTavern 陽春 |

**要點**：這些前端多數都可以「只當作聊天介面」，真正的角色人格是靠 **system prompt / character
card** 灌進去的。這代表 Phase 1 完全可以自己寫一個最小前端，直接呼叫推論後端的 API，把
`kols/{id}/profile.json` + `character.md` 轉成 system prompt——不一定要引入 SillyTavern 本體。

---

## 2. 本地 LLM 推論後端（Inference backend）

| 後端 | 特點 | Tradeoff |
|---|---|---|
| **Ollama** | 一鍵安裝、內建模型倉庫（`ollama pull`）、OpenAI-compatible REST API（port 11434）。目前是新手/單機最快上手的選擇。 | 換模型/量化細節的彈性比原生 llama.cpp 小一點 |
| **llama.cpp（原生）** | GGUF 量化模型的參考實作，Ollama 底層其實也是包這個。CPU/GPU 都能跑，量化選項最細。 | 需要自己管理模型檔案與 server 參數 |
| **KoboldCpp** | llama.cpp 的一個分支，內建針對角色扮演優化的 sampler（repetition penalty、DRY 等），常與 SillyTavern 搭配。 | 生態較小眾，但角色扮演手感常被認為比預設 llama.cpp 好 |
| **vLLM** | 高吞吐、PagedAttention，適合併發多請求。 | 對單一使用者的本地伴侶來說是過度設計，VRAM 需求也更高 |
| **LM Studio server 模式** | GUI 一鍵切換模型並開 OpenAI-compatible server。 | 適合原型，正式部署仍建議 Ollama/llama.cpp |
| **ExLlamaV2 / TabbyAPI** | Nvidia GPU 上速度最快的量化格式之一（EXL2）。 | 上手門檻較高，僅在有獨立 GPU 且追求速度時考慮 |

**建議起點**：Ollama —— 安裝簡單、API 穩定、之後要換 llama.cpp/vLLM 也只是換掉同一層的實作，
不影響上層架構（見 `02-architecture-exploration.md` 的介面設計）。

**模型選型方向**（細節留給 `local-llm-engineer` 依實際硬體定案）：7B–14B 等級開放權重模型，
需具備一定中英雙語能力與角色扮演可用性；量化等級依 VRAM/RAM 決定（如 Q4_K_M 起跳）。避免 3B
以下小模型 —— 人格一致性與對話深度明顯不足。

---

## 3. 記憶與人格一致性層

- **System prompt / character card**：最基本、Phase 1 必備。把人設、語氣、邊界寫進 system prompt。
- **Sliding window + summarization**：對話超出 context window 時，把較舊內容摘要壓縮，保留最近
  對話原文，是最簡單可行的短期記憶策略。
- **向量記憶（RAG）**：如 Chroma、SQLite-vec 等輕量向量庫，儲存長期互動歷史/事實，用相似度檢索
  拉回相關記憶再塞進 prompt。屬於「需要才加」的選項，Phase 1 不一定需要。
- **Lorebook / World Info（SillyTavern 概念）**：關鍵字觸發式的背景設定注入，適合角色背景很豐富
  的 KOL（本 repo 的 `character.md` 已經有類似深度的素材可重用）。

---

## 4. 語音與虛擬形象層（Phase 2 / 3 預留，供 `livestream-tech-specialist` 延伸）

| 類別 | 代表方案 |
|---|---|
| **串流 ASR（語音辨識）** | faster-whisper、sherpa-onnx、FunASR |
| **串流 TTS（語音合成）** | Coqui-TTS、GPT-SoVITS（可做聲音克隆）、Bark、MeloTTS、RVC（聲音轉換） |
| **虛擬形象渲染** | Live2D（透過 VTube Studio 的外掛/OSC API 驅動）、VRM（three-vrm / Unity）、
  audio-driven talking-head 生成模型（如 Alibaba 的 LiveAvatar 等 2026 年新出現的即時串流方案） |
| **即時傳輸** | WebRTC（互動場景，次秒級延遲）vs RTMP（單向廣播到 Twitch/YouTube/TikTok 等平台） |
| **全端參考實作** | **Open-LLM-VTuber**（開源、完全可離線執行、支援 Ollama 等多種 LLM 後端 + 多種 ASR/TTS +
  Live2D 桌寵模式，是目前最接近「本地 LLM + 語音 + 虛擬形象」完整拼圖的開源專案，值得作為 Phase 2/3 的
  架構參考，但功能遠超 Phase 1 範圍） |

**延遲觀察（2026 業界現況）**：雲端渲染的虛擬人像 pipeline 端到端延遲常見在 3 秒以上；追求自然
對話感的方案（如商用的 Tavus Phoenix-4）做到 600ms 以下，靠的是把 avatar 生成放進通話本身
（WebRTC 參與者）而非「生成後再串流」的兩段式架構。這個教訓對 Phase 3 很重要：**如果之後要做
即時互動直播，語音/形象生成必須跟對話迴圈同進程或同房間，不能是事後疊加的批次處理**——這也是
Phase 1 架構要求 LLM 推論後端必須支援 token streaming 輸出的原因（見架構文件）。

---

## 參考來源（2026-07 搜尋）

- [SillyTavern + Local LLM Setup Guide (2026)](https://theservitor.com/sillytavern-local-llm-setup-guide/)
- [Ollama Guide for SillyTavern & MiniTavern (2026)](https://blog.mini-tavern.com/blog/ollama-guide-local-llm-sillytavern-minitavern-privacy-c9f5e4d8)
- [SillyTavern character cards with local LLMs — privacy-focused guide (2026)](https://blog.mini-tavern.com/blog/how-to-use-sillytavern-character-cards-with-local-llms-a-complete-privacy-focuse-b615af)
- [Open-LLM-VTuber (GitHub)](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber)
- [Open-LLM-VTuber Guide: Run a Local AI Companion with Live2D, Voice, and LLMs](https://knightli.com/en/2026/06/10/open-llm-vtuber-local-ai-companion-live2d/)
- [WebRTC.ventures — Don't Mistake the AI Avatar for the Voice AI System Behind It (2026)](https://webrtc.ventures/2026/05/ai-avatar-voice-ai-system/)
- [Spatius — On-Device vs Cloud AI Avatar Architecture (2026)](https://www.spatius.ai/blog/on-device-vs-cloud-ai-avatar-architecture/)
- [Alibaba-Quark/LiveAvatar (GitHub, ECCV 2026)](https://github.com/Alibaba-Quark/LiveAvatar)
