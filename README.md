# Buildup KOL — Character Database

KOL 角色設定資料庫。每個 KOL 為一個獨立目錄，包含結構化 JSON 資料與完整角色文件。

---

## 目錄結構

```
Buildup_KOL/
├── kols/
│   ├── index.json          # 所有 KOL 的主索引
│   ├── schema.json         # 標準欄位定義（JSON Schema）
│   └── {kol-id}/
│       ├── profile.json    # 結構化角色資料（符合 schema）
│       ├── character.md    # 完整角色 Bible（中文敘述）
│       └── content_style.md # 內容方向與風格指南
```

---

## 現有 KOL

| ID | 姓名 | 類型 | 族裔 | 狀態 |
|----|------|------|------|------|
| [sofia-vargas](kols/sofia-vargas/) | Sofia Vargas | 生活風格 | 哥倫比亞裔拉丁美洲人 | active |
| [xie-yizhen](kols/xie-yizhen/) | 謝宜蓁 | 生活風格 | 台灣人 | active |
| [xiang-xiang](kols/xiang-xiang/) | 香香 | 餐飲 / 生活風格 | 台灣人 | photos_collected |
| [chloe-lin](kols/chloe-lin/) | Chloe Lin（林可昕） | 生活風格（純欲風） | 歐亞混血（英台） | draft |
| [sienna-lai](kols/sienna-lai/) | Sienna Lai（賴思妍） | 生活風格（健康生活系 / Cute×Elegant） | 台裔加拿大人 | draft |
| [brooke-sinclair](kols/brooke-sinclair/) | Brooke Sinclair | 生活風格 × 遊戲（性感） | 美國白人 | draft |
| [mika-tran](kols/mika-tran/) | Mika Tran | 生活風格（真實 IP 風格 / Real-IP Sexy） | 越南裔美國人 | draft |
| [jax-calloway](kols/jax-calloway/) | Jax Calloway | 生活風格（Male Real-IP，首個男性 KOL） | 美國白人 | draft |
| [lena-chen](kols/lena-chen/) | Lena Chen（陳語彤） | 甜妹賣貨 KOC（R2 Active Seller，台/美/歐市場） | 歐亞混血（台美） | draft |
| [lin-wanqing](kols/lin-wanqing/) | Lin Wan-Ching（林晚晴） | 溫柔知性慢生活（F6，R1 Soft-Seller，film-candid 自然美） | 台灣人 | draft |

---

## 新增 KOL 流程

1. 在 `kols/` 下建立新目錄，命名規則：`{firstname}-{lastname}`（kebab-case）
2. 按照 `kols/schema.json` 建立 `profile.json`
3. 撰寫 `character.md`（角色 Bible）與 `content_style.md`（內容指南）
4. 在 `kols/index.json` 新增對應紀錄

---

## Schema

所有 `profile.json` 須符合 [`kols/schema.json`](kols/schema.json) 定義的結構，主要欄位：

- `meta`：建立時間、狀態、分類、參考帳號
- `identity`：姓名、年齡、族裔、現居地、語言、外型
- `persona`：人物原型、個性、價值觀、背景故事、語氣風格
- `content`：內容支柱、格式、發文頻率、視覺美學、品牌合作原則
- `social`：各平台帳號資訊、互動風格、粉絲社群名稱

---

## 工具 Tools

`tools/vlog_app.py` — 本地端把 KOL 照片變成直式 9:16 TikTok/Reels vlog（LLM 腳本 → `say` 配音 →
Ken Burns + 字幕 → ffmpeg 合成）。100% local、免費。用法見 [`tools/README.md`](tools/README.md)。

**在 NVIDIA/CUDA 機器上跑完整系統**（影像面部鎖定、GPT-SoVITS 自然語音、LiveTalking 即時數位人、
LLM 大腦）的一站式指南見 [`CUDA_SETUP.md`](CUDA_SETUP.md)。

---

## 延伸研究：本地端互動 AI 伴侶

`research/local-ai-companion/` 是一條探索中的延伸研究：如何把 `kols/` 裡的靜態人格資料，變成一個
可在本地端即時對話的 AI 伴侶（文字互動優先，語音/虛擬形象/直播為預留擴充）。詳見該資料夾的
`README.md`，以及新增的三個專責 subagent：`local-ai-companion-architect`、
`livestream-tech-specialist`、`local-llm-engineer`（定義於 `.claude/agents/`）。
