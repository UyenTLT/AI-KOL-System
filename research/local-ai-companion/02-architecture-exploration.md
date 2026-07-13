# 初始架構探索 — Local AI Companion (Phase 1)

本文件是 Phase 1（純文字本地互動）的**草案架構**，目的是把模組邊界與介面先定下來，讓
`local-ai-companion-architect` 之後能在這個骨架上展開細部設計，而不用從零討論。所有具體技術選型
都標記為「初步建議」，非最終決定。

## 設計原則

1. **人格資料只有一份來源**：`kols/{kol-id}/profile.json` + `character.md` 是唯一的人格真相來源，
   companion 系統只能「讀取並轉換」它，不可另建一套平行的人設格式。
2. **每一層可獨立替換**：換模型、換推論引擎、之後加語音/虛擬形象，都不該動到其他層的程式碼。
3. **面向未來但不過度設計 Phase 1**：介面（interface/contract）要為 Phase 2/3 預留，但 Phase 2/3
   的實作本身完全不在本次範圍內。
4. **全部跑在本機**：不依賴雲端 API 是硬性需求，所有選型都以「單機可行」為前提。

## 模組架構（Phase 1）

```
┌─────────────────────────────────────────────────────────────────┐
│                        Interface Layer                          │
│   （Phase 1）CLI 或最小本地 Web UI — 文字輸入 / 文字輸出          │
│   （Phase 2 預留）語音 I/O 接入點                                 │
│   （Phase 3 預留）虛擬形象 / 直播輸出接入點                        │
└───────────────────────────┬───────────────────────────────────────┘
                             │  對話文字（使用者輸入 / AI 回應，可 streaming）
┌───────────────────────────▼───────────────────────────────────────┐
│                 Conversation Orchestrator                        │
│  - 管理對話 session / 短期上下文視窗                               │
│  - 呼叫 Persona Layer 取得 system prompt                          │
│  - （需要才加）呼叫 Memory 取得長期記憶片段                        │
│  - 基本安全邊界檢查（人設扮演 vs 真正有害內容）                     │
└───────┬───────────────────────────────────────────┬───────────────┘
        │ system prompt + persona 設定                │ chat completion request
┌───────▼────────────────┐                 ┌─────────▼───────────────┐
│     Persona Layer       │                 │   LLM Inference Backend │
│ 讀取 kols/{id}/          │                 │ 本地執行，OpenAI-        │
│ profile.json +           │                 │ compatible API           │
│ character.md，轉換為      │                 │ （初步建議：Ollama）      │
│ system prompt /          │                 │ 須支援 token streaming    │
│ character card           │                 │ （為 Phase 2 語音鋪路）    │
└──────────────────────────┘                 └──────────────────────────┘
```

## 各層說明與初步技術建議

### 1. Interface Layer（Phase 1 唯一要做的使用者介面）

- 最小可行版本：CLI（stdin/stdout 迴圈）即可驗證端到端可行性。
- 若要更好的使用體驗，可以做一個極簡本地 Web UI（單一 HTML + 呼叫本地 API），不需要引入
  SillyTavern 這種重量級前端 —— Phase 1 的需求（單一使用者、單一角色、純文字）不需要它的多角色/
  world info 等進階功能。
- 介面層只認得「Conversation Orchestrator 暴露的一個對話 API」，不直接碰 LLM 後端，這樣以後
  Phase 2 加語音時，只需要在 Interface Layer 新增語音輸出（TTS 消費同一個 streaming 文字輸出），
  不用改 Orchestrator。

### 2. Conversation Orchestrator

- 職責：維護單一對話 session 的歷史、組裝送給 LLM 的訊息（system prompt + 歷史 + 新輸入）、
  處理超出 context window 時的裁剪/摘要策略。
- Phase 1 記憶策略建議從「sliding window（保留最近 N 輪）+ 超出時摘要壓縮」開始，向量記憶
  （RAG）留到有實際需要（例如使用者反應 AI 忘記重要設定）再加，避免過早引入複雜度。
- 安全邊界：需要和使用者一起定義清楚「人設扮演的尺度」與「不可跨越的紅線」，這是產品決策，
  應由使用者拍板，寫進本文件的待決策清單。

### 3. Persona Layer — 與既有 KOL 資料庫的整合點

這是本研究最關鍵的整合點：本 repo 已經有結構化的人格資料（`kols/schema.json` 定義的
`profile.json`，加上敘事更完整的 `character.md`）。Persona Layer 的工作就是把這份資料**機械式地**
轉換成 system prompt（或相容於 SillyTavern Character Card V2 格式，方便未來換前端），大致對應：

| KOL 既有欄位 | 對應到 companion 的 | 
|---|---|
| `identity`（姓名、年齡、族裔、語言、外型） | System prompt 開頭的角色設定 |
| `persona`（原型、個性、價值觀、背景故事、語氣） | System prompt 主體 + 語氣範例 |
| `content`（內容支柱、視覺美學） | 選配：作為話題偏好背景知識，非對話核心 |

這個映射邏輯應該是**通用的、可套用在任何 KOL 身上**的一段轉換程式，而不是每個角色手刻一份 prompt。

### 4. LLM Inference Backend

- 初步建議：**Ollama** 作為起點 —— 安裝簡單、模型倉庫方便、暴露 OpenAI-compatible API，且底層
  就是 llama.cpp，之後若要換更細的量化控制或效能調校，遷移成本低。
- 具體模型大小/量化等級留給 `local-llm-engineer` 依使用者實際硬體（VRAM/RAM）決定；方向是
  7B–14B 等級、具中英雙語能力的開放權重模型。
- **硬性要求**：後端必須支援 streaming 輸出（逐 token 回傳），即使 Phase 1 只用在讓文字「打字機
  效果」顯示，也要現在就選對支援這件事的後端 —— 這樣 Phase 2 要把文字流接到 TTS 做語音時，
  不需要換後端。

## 資料流（一輪對話）

1. 使用者在 Interface Layer 輸入文字
2. Interface → Orchestrator：附上 session id
3. Orchestrator 組裝訊息：Persona Layer 提供的 system prompt + 對話歷史（含摘要/記憶片段）+ 新輸入
4. Orchestrator → LLM Inference Backend：送出 chat completion 請求（streaming）
5. LLM 逐 token 串流回應 → Orchestrator 邊收邊轉送 → Interface Layer 即時顯示
6. Orchestrator 把這輪對話存入 session 歷史，供下一輪組裝上下文

## 待決策問題（留給後續 agent 設計時解決）

這些是需要使用者拍板或需要更深入設計的問題，刻意不在本文件自行決定：

1. **單引擎多角色 vs 各角色獨立部署**：一套 companion 引擎服務所有 KOL（動態換 persona），還是
   每個 KOL 各自一份部署？影響資源佔用與併發需求。
2. **內容邊界**：人設扮演（含本 repo 部分 KOL 的「性感/挑逗」風格設定）與「有害內容」的界線要
   怎麼定義並在 Orchestrator 的安全檢查中落地？
3. **目標硬體規格**：使用者實際的 GPU/VRAM/OS 是什麼？這直接決定模型大小與量化等級的可行範圍，
   `local-llm-engineer` 需要這個資訊才能給出具體建議而非泛用建議。
4. **第一個試跑角色**：從 `kols/` 選一個資料最完整的角色（例如 `chloe-lin` 或 `sienna-lai`）作為
   Phase 1 的驗證對象，還是先用一個全新的最小測試人格驗證架構本身？
5. **Phase 2/3 的觸發時機**：語音與虛擬形象/直播何時真正排入開發，或者永遠只是「架構預留但不做」？
   這會影響現在要不要為 Interface Layer 多花力氣做抽象。

## 與 `.claude/agents/` 三個角色的分工

- 上述待決策問題中，**1、2、5** 屬於整體產品/架構決策 → 找 `local-ai-companion-architect`（連同
  使用者）拍板。
- **3、模型/量化/推論後端細節** → 找 `local-llm-engineer`。
- **Phase 2/3 一旦排入時程** → 找 `livestream-tech-specialist` 展開語音/虛擬形象的詳細設計，
  它會從 `01-landscape-existing-solutions.md` 第 4 節的調查繼續往下做。
