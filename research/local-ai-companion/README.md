# 本地端互動 AI 伴侶 — 技術研究

> Status: **exploratory research** — 本資料夾建立基礎框架與初步架構探索，尚未進入實作。
> 後續細部設計交由三個專責 subagent（見下）展開。

## 目標

在使用者自己的電腦（本地端，不依賴雲端 API）上，實現一個可以**用文字互動、具備固定 AI 人格**的
AI 伴侶（概念上類似「AI 女友」）：使用者輸入文字，AI 以角色人格產生對話回應。

這與本 repo 既有的 KOL 角色資料庫（`kols/`）是同一條路的延伸：現有資料庫把人格「寫成靜態文件」
（`profile.json` / `character.md`），這個研究則是探索如何把同一份人格資料變成一個「可以即時對話」
的本地系統 —— 讓 KOL 從純內容創作者，進化為可互動的虛擬角色。

## 範圍與分期（Phases）

| Phase | 範圍 | 狀態 |
|---|---|---|
| **Phase 1** | 純文字本地聊天：文字輸入 → 本地 LLM → 人格化文字回應 | **本次任務範圍**，架構探索見 `02-architecture-exploration.md` |
| Phase 2（預留） | 語音輸入輸出（ASR/TTS）、自然打斷、即時語音對話 | 尚未設計，僅在架構中預留介面 |
| Phase 3（預留） | 即時虛擬形象（Live2D/VRM）+ 直播串流，讓 AI 伴侶可被「看見」甚至公開直播 | 尚未設計，僅在架構中預留介面 |

刻意先只做 Phase 1，但架構必須讓 Phase 2、3 是「新增模組」而不是「重寫」。這也是為什麼本研究
一開始就找了解直播/即時互動技術的角色加入 —— 避免 Phase 1 的設計決策堵死之後語音與直播的路。

## 文件結構

```
research/local-ai-companion/
├── README.md                          # 本文件：目標、分期、角色分工
├── 01-landscape-existing-solutions.md # 現成方案調查（frontend / 推論後端 / 語音 / 虛擬形象）
├── 02-architecture-exploration.md     # 針對本案的初始模組化架構草案
├── 03-phase1-detailed-design.md       # Phase 1 詳細設計（可直接動手實作）：目錄結構、persona
│                                       # 轉換演算法、session/context 演算法、API 契約、預設模型
├── 04-realtime-avatar-integration.md  # Phase 2/3 決策：選定 lipku/LiveTalking 為真人數位人整合對象
│                                       # （文字→語音→真人臉→直播），含可行性評分與落地步驟
├── 05-poc-execution-plan.md           # POC 實驗計畫書：把 04 的落地步驟展開成逐字可照做的指令、
│                                       # 驗收判準、疑難排解、執行記錄表（在你自己的 GPU 機器上跑）
├── 06-agent-execution-charter.md      # 給執行 agent 的規範書：Mac mini/筆電硬體分流判斷、目標、
│                                       # 明確禁止事項、時間預算、回報格式 —— 交給實際執行的 agent 讀
├── 07-literature-and-china-market-review.md # 學術文獻回顧（Wav2Lip/MuseTalk/VASA-1/Live Avatar 等）
│                                       # ＋大陸數位人直播市場規模、廠商、案例、法規現況
├── 08-livetalking-effectiveness-evidence.md # 動手前先看：LiveTalking 官方展示影片、可線上試用的
│                                       # demo 網站、GitHub Issues 裡真實使用者回報的優缺點
└── references/                         # 外部參考資料（原件 + 導讀）
    ├── AI_Livestream_Report.pdf        #   Evelyn 的 AI 直播帶貨技術報告（原件保存）
    └── AI_Livestream_Report.md         #   ↑ 導讀：重點整理 + 對應到本專案 Phase 2/3 的註記
```

## 三個新增的專責角色（`.claude/agents/`）

本次任務新增三個 subagent 定義，供後續設計工作呼叫：

1. **`local-ai-companion-architect`** — 系統架構師。負責模組邊界、資料流、技術選型取捨、
   跨 Phase 的介面設計。當你要規劃整體架構或做「這一塊該怎麼接」的決策時呼叫它。
2. **`livestream-tech-specialist`** — 直播／即時互動技術專家。負責 Phase 2/3 會用到的
   低延遲音視訊、串流 ASR/TTS、Live2D/VRM 虛擬形象、WebRTC/RTMP 等領域知識。當問題聚焦在
   「語音、打斷、虛擬形象、直播」時呼叫它。
3. **`local-llm-engineer`** — 本地 LLM 部署工程師。負責推論後端／模型選型、量化、人格
   （character card）綁定、記憶體/上下文策略。當問題聚焦在「跑哪個模型、用哪個推論引擎、
   人格怎麼綁進 prompt」時呼叫它。

架構師負責整合，另外兩個是領域專家；三者的 `description` 已寫明何時該用哪一個，避免職責重疊。

## 現況與下一步

- ✅ 研究框架建立（本資料夾）
- ✅ 現成方案調查（`01-landscape-existing-solutions.md`）
- ✅ 初始架構探索（`02-architecture-exploration.md`）
- ✅ Phase 1 詳細設計（`03-phase1-detailed-design.md`）—— 目錄結構、persona → system prompt
  轉換演算法（含真實 KOL 渲染範例）、session/context 組裝與裁剪/摘要演算法、Orchestrator API
  契約、預設模型建議（暫定，待硬體資訊確認）
- ✅ 收錄外部參考：Evelyn 的 AI 直播帶貨技術報告（`references/`）—— 產業現況、商用平台、留言→行為
  互動 pipeline，供 Phase 2/3 與 `livestream-tech-specialist` 使用（導讀已標註哪些可回填 01 文件）
- ✅ **Phase 2/3 真人數位人整合對象定案（`04-realtime-avatar-integration.md`）** —— 以「本地可立即
  整合、可行性最高」為目標盤點後，選定 **`lipku/LiveTalking`**（可行性 ~91% > 80% 門檻）：單一 repo
  打通「打字文案 → 聲音（可克隆真人聲）→ 真人樣貌數位人對嘴 → RTMP/虛擬攝影機直播」。已附可行性
  評分、Wav2Lip/MuseTalk 雙硬體路徑、與 kols/ 及 03 設計的整合點、可執行落地步驟
- ✅ **POC 實驗計畫書（`05-poc-execution-plan.md`）** —— 把 `04` 的落地步驟展開成逐字可照做的
  安裝指令、API 呼叫範例、驗收判準、疑難排解對照表、執行記錄表，需在有 NVIDIA GPU 的機器上實跑
  （此研究環境本身無 GPU，指令未實測，已據官方 README/`docs/api.md`/`config.py` 逐條核實）
- ✅ **Agent 執行規範書（`06-agent-execution-charter.md`）** —— 因應「準備 Mac mini 或筆電、交給
  agent 執行」的需求：Gate 0 硬體偵測分流（**Mac mini 確定無法跑 CUDA，屬 Track B 低優先探索**；
  有 NVIDIA GPU 的筆電走 Track A = `05` 文件）、明確禁止事項（不公開直播、不用未授權真人素材、
  不花錢、不深度移植原始碼、不自動 push 回 repo）、時間預算上限、機器可驗證 vs 需人類親自確認的
  回報格式
- ✅ **學術文獻與大陸市場回顧（`07-literature-and-china-market-review.md`）** —— 確認 Wav2Lip
  （ACM MM 2020）、MuseTalk（TMElyralab）等 `04`/`05` 選用的模型本身是同儕審查發表過的研究，
  非野生工具；阿里巴巴 Live Avatar（ECCV 2026）驗證同技術方向已有大廠頂會投入；大陸數位人直播
  市場規模（京東×艾瑞白皮書：2026 年超過 845.7 億人民幣）、主要廠商（騰訊智影/百度曦靈/硅基智能/
  阿里通義曉橙/商湯如影）、真實案例（羅永浩、京東 618、杭州/廣州店家 ROI）、法規時間點（2026/05
  四大類禁令、2026/06 強制標示 AI 主播）已整理，可回填 `04` 文件風險章節
- ✅ **LiveTalking 效果證據彙整（`08-livetalking-effectiveness-evidence.md`）** —— 動手前先看：
  README 官方三支展示影片（Wav2Lip/ER-NeRF/MuseTalk，Bilibili）、可線上試用的官方 demo 站
  `livetalking.top`、GitHub Issue #525 回報硬體門檻可能更低（T4/A30、~4GB VRAM 即可）、Issue #510
  回報即時打斷對話能力偏弱（最快 3 秒響應，官方尚未修復，但不影響 POC 主線的 echo 模式範圍）
- ⬜ 你決定要準備哪一台機器（建議優先 NVIDIA 獨顯筆電；Mac mini 僅作次要嘗試），把
  `06-agent-execution-charter.md` 交給實際在那台機器上執行的 agent
- ⬜ 由 `livestream-tech-specialist` 依實測結果回填 `04` 文件的可行性評分與效能數據
- ⬜ 由 `local-llm-engineer` 依實際硬體核定/調整 `03-phase1-detailed-design.md` 第 4.2 節的
  模型選型，並視需要展開更細的推論效能調校
- ⬜ 選一個既有 KOL（例如 `kols/chloe-lin` 或 `kols/sienna-lai`）作為第一個試跑角色，驗證 Phase 1 端到端可行性
