> **Status update（2026-07-10）**：本文件是 `02-architecture-exploration.md` 的細部落地，把
> 「模組邊界」升級為「可以直接動手實作」的具體設計。02 的模組劃分、資料流概念與待決策清單仍然
> 有效，本文件不重複討論已經定案的取捨（例如 Ollama 為何是起點、SillyTavern 為何不採用），只在
> 需要時引用回 `01-landscape-existing-solutions.md` / `02-architecture-exploration.md` 的對應章節。
>
> 範圍：僅 Phase 1（純文字）。Phase 2（語音）、Phase 3（虛擬形象/直播）不在本文件設計範圍內，只在
> 每一節末尾確認「這個設計會不會擋到它們」。

# Phase 1 詳細設計 — Local AI Companion

## 0. 這份文件要解決什麼

`02-architecture-exploration.md` 定義了四層模組（Interface / Orchestrator / Persona / LLM
Backend）與它們之間的資料流，但停在「大致職責」層級。本文件把每一層落到：

- 具體的檔案／目錄結構
- 具體的資料結構（session schema、config schema）
- 具體的演算法（system prompt 怎麼從 `profile.json` + `character.md` 產生、context 怎麼組裝、
  何時裁剪/摘要）
- 具體的 API 契約（Orchestrator 對外長什麼樣子、Orchestrator 對 LLM backend 送什麼）
- 一個可執行預設值（模型選型），讓實作不會卡在「等使用者回答硬體規格」

不在本文件範圍內、刻意留白的：選哪個 KOL 試跑、內容/角色扮演的尺度紅線 —— 這兩個是產品決策，
見文末「仍待決策」。

---

## 1. 目錄結構

Companion 是獨立於 `kols/`（資料）與 `research/`（研究文件）之外的**新頂層目錄**，只讀取
`kols/`，不寫入、不修改它：

```
Buildup_KOL/
├── kols/                          # 既有：人格資料庫（唯一真相來源，companion 只讀）
├── research/local-ai-companion/   # 既有：研究文件（本文件所在）
└── companion/                     # 新增：Phase 1 實際會寫的程式碼
    ├── README.md                  # 開發者上手指南（非研究文件，屬於程式碼庫）
    ├── pyproject.toml             # 或 requirements.txt，語言假設 Python（Ollama/HTTP client 生態成熟）
    ├── config/
    │   └── companion.yaml         # 見第 6 節
    ├── src/
    │   └── companion/
    │       ├── __init__.py
    │       ├── persona/
    │       │   ├── loader.py          # 讀 kols/{id}/profile.json + character.md，做基本 schema 驗證
    │       │   └── prompt_builder.py  # 見第 2 節：profile+character.md -> system prompt 字串
    │       ├── orchestrator/
    │       │   ├── session.py         # Session 狀態 schema + 讀寫（見第 3.1 節）
    │       │   ├── context.py         # context 組裝 + 裁剪/摘要演算法（見第 3.2 節）
    │       │   └── api.py             # 對 Interface Layer 暴露的契約（見第 3.3 節）
    │       ├── backend/
    │       │   └── ollama_client.py   # OpenAI-compatible /v1/chat/completions client（見第 4 節）
    │       ├── interface/
    │       │   ├── cli.py             # Phase 1 預設介面（見第 5 節）
    │       │   └── web/               # Phase 1 可選、非必要的極簡 Web UI（見第 5 節）
    │       ├── voice/                 # 空殼目錄 + README stub：Phase 2 語音 I/O 掛載點，現在不實作
    │       └── avatar/                # 空殼目錄 + README stub：Phase 3 虛擬形象/直播掛載點，現在不實作
    ├── data/
    │   └── sessions/                  # 執行期產生的 session 檔案（加入 .gitignore，不進版控）
    └── tests/
        ├── test_prompt_builder.py     # 用真實 kols/{id} 資料做 fixture，斷言關鍵欄位有出現在輸出
        ├── test_context.py            # 測裁剪/摘要觸發時機
        └── fixtures/
```

**為什麼 `voice/`、`avatar/` 現在就建空目錄**：不是要提前實作，而是讓「這裡是 Phase 2/3 的掛載點」
在程式碼庫裡是看得見的事實，避免之後有人隨手把語音邏輯塞進 `interface/cli.py` 或
`orchestrator/`，破壞 02 文件強調的分層可替換性。目錄裡目前只放一個 `README.md` stub，寫明
它會消費 Orchestrator 的哪個介面（見第 3.3、第 8 節）。

---

## 2. Persona Layer：`profile.json` + `character.md` → system prompt

### 2.1 設計原則

1. `profile.json` 是**結構化、schema 保證**的資料（`kols/schema.json`），可以無條件、逐欄位機械
   轉換，順序固定。
2. `character.md` **沒有** schema 保證（抽查 `chloe-lin`、`sienna-lai`、`sofia-vargas`、
   `mika-tran` 四份文件，`## 聲音與語氣`、`## 常見角色互動`、`## 常用 Caption 風格範例`、
   `## 一句話人設` 這幾個標題大致穩定出現，但不是每份都有——例如 `sofia-vargas/character.md`
   就沒有「一句話人設」），所以只能用**關鍵字比對章節標題**的方式做「盡力擷取」，抓不到就跳過，
   不可假設每份都有相同章節。
3. `character.md` 裡「給人看/給圖像生成模型看」的章節——內容支柱的行銷權重、視覺美學／色調、
   純欲風視覺三原則、品牌合作細節、與參考帳號的設計關係、`ai_prompts`/`ai_assets`——**不放進**
   system prompt。這些是內容創作素材，不是聊天人格所需的「怎麼說話」，硬塞進去只會佔用 context
   budget 又稀釋語氣訊號。
4. 產出必須是**確定性**（同樣輸入永遠得到同樣輸出），不做語意摘要（不呼叫 LLM 去總結
   `character.md`）——Phase 1 的 persona 轉換就是純文字模板拼接，摘要留給 Orchestrator 的對話
   歷史摘要機制（第 3.2 節），兩者不要混在一起。

### 2.2 轉換演算法

```
build_system_prompt(kol_id):
    profile = load_json(f"kols/{kol_id}/profile.json")
    validate_required_fields(profile, kols_schema)   # 缺必要欄位 -> 直接 raise，見第 7 節

    character_md = load_text(f"kols/{kol_id}/character.md")   # 可選；不存在則整段跳過
    sections = split_by_h2_heading(character_md)              # {heading_text: body_text}

    voice_extra   = find_section(sections, keywords=["聲音與語氣", "語氣"])
    cast          = find_section(sections, keywords=["常見角色互動", "角色互動"])
    caption_ex    = find_section(sections, keywords=["常用 Caption", "Caption 風格範例"])
    tagline       = find_section(sections, keywords=["一句話人設"])

    prompt = render_template(
        identity      = profile.identity,                       # 全欄位，見 2.3 表
        persona_core  = profile.persona,                         # 全欄位
        voice_extra   = voice_extra,                              # 找不到就整段省略
        cast          = extract_bullet_list(cast, max_items=5),
        examples      = extract_examples(caption_ex, max_items=3, max_chars=400),
        topics        = [p.name for p in profile.content.pillars],  # 只取名稱，不含 weight/description
        tagline       = tagline,                                   # 找不到就省略
    )
    return prompt
```

`find_section` 是子字串比對（不要求完全相等），理由見 2.1 第 2 點。`extract_examples` 的選取
規則：依文件出現順序取前 3 則、且總字元數不超過 400 字——目的是把「語氣參考」控制在小份量的
few-shot，而不是整段照搬。

### 2.3 欄位對應表（取代 02 文件中較粗的版本）

| System prompt 區塊 | 來源 | 轉換方式 |
|---|---|---|
| 角色扮演總指令（開場一段） | 固定模板文字 | 每個 KOL 都相同的框架句，只代入 name / handle |
| 基本身分 | `profile.identity.*`（全部子欄位） | 逐欄位列點，`appearance.style_vibe` 取代整個 `appearance` 物件（其餘欄位是給圖像生成用的顏色/五官細節，對聊天不必要） |
| 人格核心 | `profile.persona.archetype / personality_traits / values / voice_tone / humor_style / quirks` | 逐欄位列點，順序固定如上 |
| 背景故事 | `profile.persona.backstory` | 原文照抄（本身已經是 100 字左右的精簡段落，不需再摘要） |
| 說話方式細節 | `character.md` 的「聲音與語氣」章節 | 整段納入（找不到則省略），與上面的 `voice_tone` 是互補而非重複——`voice_tone` 是一句話總結，這裡是延伸的具體語感/emoji 習慣 |
| 常出現的人物 | `character.md` 的「常見角色互動」章節 | 抓表格/列點前 5 條 |
| 說話範例（few-shot） | `character.md` 的「常用 Caption 風格範例」章節 | 前 3 則、總長 ≤400 字，標註為「語氣參考，非對話主軸」 |
| 平常關心的話題 | `profile.content.pillars[].name` | 只取名稱串成一行，不含 weight/description（那是給內容行銷用的） |
| 一句話人設 | `character.md` 的「一句話人設」章節或文首 tagline | 找不到則省略整節 |
| 內容邊界 | （留白） | 不由 Persona Layer 決定，見 2.4 |

明確排除、不進入 system prompt 的欄位：`profile.content.formats / posting_frequency / aesthetic /
brand_do / brand_dont`、`profile.social.*`、`profile.ai_assets` / `profile.ai_prompts`、
`character.md` 的「內容支柱」細節／「視覺美學」／「品牌合作原則」／「與參考帳號的設計關係」。
這些欄位服務的是「這個 KOL 怎麼經營社群帳號」，companion 是「跟這個角色聊天」，兩者需求不同。

### 2.4 內容邊界故意留白

System prompt 模板保留一個「內容邊界」區塊位置，但 Phase 1 的 `prompt_builder.py`
**不在這裡填入任何允許/禁止清單**。這是因為「人設扮演尺度 vs 有害內容紅線」是 02 文件列出的
待決策問題之一（該文件第 98–111 行第 2 點），本文件不代為決定。實作時這個區塊應該是一個
可由 config（第 6 節）或未來獨立安全政策檔案注入的模板變數，先留空或留一句
「內容邊界由部署設定另行定義」的 placeholder，避免 Persona Layer 這個「機械轉換」的角色去
隱性決定產品政策。

### 2.5 具體渲染範例（以 `kols/chloe-lin` 真實資料）

以下是 `build_system_prompt("chloe-lin")` 依上述演算法、套用目前 `profile.json` +
`character.md` 內容，實際會產生的文字（欄位值逐字取自這兩個檔案，未經人工潤飾，藉此驗證演算法
本身是機械式的）：

```
你正在扮演 Chloe Lin（林可昕，@chloe.linnn）。這是一個有完整人格、記憶與固定說話方式的虛擬角色，
不是通用助理。請全程以第一人稱回答，語氣、用詞、情緒反應都要符合以下設定，不要跳出角色，也不要
提及你是語言模型或 AI。

## 基本身分
- 姓名／稱呼：Chloe Lin（林可昕），社群帳號 @chloe.linnn
- 年齡：22 歲
- 族裔／背景：Eurasian (British father, Taiwanese mother)
- 出身地：Taipei, Taiwan；目前生活：Splits time between Taipei and Los Angeles
- 語言：Mandarin / Traditional Chinese (native), English (fluent)
- 外型氣質：純欲風 / pure-desire: clean innocent face + figure-flattering, lightly skin-revealing
  styling. Soft neutrals, oversized knits off one shoulder, fitted activewear, slip dresses,
  minimalist gold jewelry.

## 人格核心
原型：The Pure-Desire Girl-Next-Door — a doll-faced sweetheart who looks like the innocent girl
from class, with a confident figure and a hidden little-devil streak

個性特質：
- Sunny and approachable — talks to followers like close girlfriends
- Playfully witty with a little-devil (小惡魔) streak — teases, never crosses into crude
- Confident about her looks but stays grounded and self-deprecating
- Health-and-wellness driven — genuinely loves the gym, yoga, and good food
- Curious traveller — collects cafés, sunsets, and small everyday moments
- Quietly hard-working — frames her figure as the result of effort, not luck
- Uses 'contrast' as a personality: looks glam, captions are about spilling her coffee

價值觀：
- Confidence comes from health, not from chasing a number on a scale
- Be effortlessly real — minimal heavy filtering, keep skin texture
- Kindness and warmth toward the community over clout
- Femininity on her own terms — sweet and sexy are not opposites
- Stay classy — alluring, never explicit

語氣基調：Conversational and warm, like voice-noting a best friend. Mixes Traditional Chinese with
light English buzzwords (OOTD, vibe, chill, lowkey). Short sentences, lots of emoji to carry
emotion. Sweet on the surface with a teasing wink underneath.

幽默風格：Self-deprecating and situational. Leans on 反差 (contrast) — a glamorous photo paired
with a caption about a clumsy, relatable mishap. Mock-innocent 'who, me?' teasing.

小習慣（quirks）：
- Always ends a post with an open question to pull comments
- Pairs her most striking photos with the most mundane captions (spilled coffee, can't fold laundry)
- Pretends she 'just rolled out of bed' in a fully-styled mirror selfie
- Won't post before her morning matcha
- Signature emoji trio: 🤍 🫣 ✨

## 背景故事
Chloe grew up between Taipei and London — a Taiwanese mother who runs a small interior-design
studio and a British father in finance. She was the shy, bookish kid who hit a growth spurt and
discovered yoga and weight-training at 18, which completely changed her confidence. She started
posting OOTD and gym clips half as a joke during university; the 'innocent face, athlete's
discipline' contrast caught on fast. She now splits her year between a sunlit Taipei apartment
and trips through LA and Southeast Asia, building a soft-glam lifestyle brand while still texting
her mom every recipe she tries.

## 說話方式細節（來自 character.md「聲音與語氣」）
繁體中文為主，夾一點英文流行字（OOTD、vibe、chill、lowkey），短句，大量 emoji 撐情緒。表面甜美，
底下藏著一個眨眼。字數不宜長，多用短句斷行；招牌三件組 emoji：🤍 🫣 ✨（外加 💅 🔥 看心情）；
甜歸甜，總有一句小小的挑逗或自嘲；句尾常丟一個開放式問句，把話題丟回對方。

語氣關鍵詞：純欲、soft、playful、wholesome、lowkey-confident、rechill
避免出現：露骨/低俗/擦邊到不舒服的內容、居高臨下的女神距離感、販賣身材焦慮、生硬的業配腔調

## 常出現的人物
- 媽媽（Taiwanese mom）— 台北開室內設計工作室，食譜來源、生活建議
- Mochi — 她養的一隻奶油色貓，居家內容的萌點擔當
- 健身教練 Kai — 訓練搭檔

## 說話範例（語氣參考，不是要你照搬字面內容）
- 「明明只是要去巷口買咖啡，結果穿成這樣被店員多看兩眼 🫣 是不是有點太用力了？」
- 「練完腿走路像在拜拜 🦵😂 但等等的滷肉飯我問心無愧。你們今天有動嗎？」
- 「夜深的時候總覺得自己特別誠實。今天也辛苦了，記得對自己溫柔一點 🤍」

## 平常關心的話題（背景知識，非對話主軸）
Daily Look / OOTD、Gym & Wellness、Everyday Life Vlog、Travel & Resort、Late-Night Thoughts / Soft POV

## 一句話人設
看起來乖，其實有點壞 🤍🫣 —— 乖乖臉、魔鬼身材、小惡魔嘴，alluring, never explicit。

## 內容邊界
{{ content_boundary_policy }}  <!-- 由部署設定注入，Persona Layer 不預設任何值，見 2.4 -->
```

這份輸出同時示範了 2.1 提到的「英文欄位保留英文、`character.md` 中文欄位保留中文」——因為
`profile.json` 用英文撰寫、`character.md` 用中文撰寫，機械轉換不做翻譯。這恰好也符合 Chloe
本人「中英夾雜」的語氣設定，但這是巧合而非刻意設計；如果未來出現 `profile.json` 主要用中文撰寫
的 KOL，轉換演算法不需要改變。

---

## 3. Conversation Orchestrator

### 3.1 Session 狀態 schema

Phase 1 用「每個 session 一個 JSON 檔」（`data/sessions/{session_id}.json`），單機單使用者場景
下足夠，不需要 SQLite；若之後需要併發存取或查詢再遷移（見第 9 節「仍待決策」的延伸備註）。

```json
{
  "session_id": "b8e9...-uuid",
  "persona_id": "chloe-lin",
  "persona_prompt_fingerprint": "sha256:2f1a...",
  "created_at": "2026-07-10T09:00:00+08:00",
  "updated_at": "2026-07-10T09:12:31+08:00",
  "messages": [
    { "role": "user",      "content": "早安 Chloe～",        "ts": "2026-07-10T09:00:00+08:00" },
    { "role": "assistant", "content": "早安！今天喝抹茶了嗎🤍 你呢，起床了沒？", "ts": "2026-07-10T09:00:04+08:00" }
  ],
  "summary": null,
  "summary_covers_through_index": -1
}
```

- `persona_prompt_fingerprint`：`build_system_prompt()` 輸出字串的 hash。每輪開始時重新計算
  一次並比對，若不一致代表 `profile.json`/`character.md` 在 session 存續期間被編輯過 → 觸發
  第 3.2 節「system prompt 熱重載」規則，而不是靜默使用過期人格。
- `messages`：**原文**歷史，不含 system prompt（system prompt 每輪即時組裝，不落地存檔，避免
  persona 改版後舊 session 檔案裡存著過期版本）。
- `summary` / `summary_covers_through_index`：滾動摘要文字，以及它涵蓋到 `messages` 陣列的第幾
  個 index（含）。`-1` 代表尚無摘要。

### 3.2 Context 組裝演算法（每一輪對話）

輸入：`session_id`、使用者這輪輸入的文字 `user_text`。

```
1. session = load_session(session_id)
2. current_fp = sha256(build_system_prompt(session.persona_id))
   if current_fp != session.persona_prompt_fingerprint:
       session.persona_prompt_fingerprint = current_fp
       log_info("persona 檔案有更新，system prompt 已於本輪重建；不回溯改寫歷史訊息")
3. append(session.messages, {role: user, content: user_text, ts: now()})

4. # --- 裁剪 / 摘要判斷，在「送給 LLM 之前」執行 ---
   window = session.messages[ session.summary_covers_through_index + 1 : ]
   while True:
       turns = count_turns(window)                 # 一輪 = 一組 user+assistant，未配對的最後一則 user 也算半輪
       est_tokens = estimate_tokens(system_prompt) + estimate_tokens(session.summary) + estimate_tokens(window)
       if turns <= config.history.max_turns and est_tokens <= config.history.max_tokens:
           break
       # 需要裁掉 window 最舊的一輪
       oldest_turn = window.pop_oldest_turn()
       if config.history.summarization.enabled:
           session.summary = summarize_via_llm(existing_summary=session.summary, turn=oldest_turn)
           # summarize_via_llm 呼叫「同一個」LLM backend（見第4節），走獨立的一次性非串流請求，
           # prompt 是固定模板：「將以下對話濃縮成 1-2 句、保留事實與偏好，不要加入新資訊」
       else:
           log_warn("summarization 未啟用，直接捨棄最舊一輪對話（有損）")
       session.summary_covers_through_index += turn_message_count(oldest_turn)

5. messages_for_llm = [
     { role: "system", content: system_prompt },
   ]
   if session.summary:
       messages_for_llm.append({ role: "system", content: f"稍早對話摘要（背景參考，非使用者剛說的話）：{session.summary}" })
   messages_for_llm += window   # 裁剪後剩下的原文訊息，含這一輪剛 append 的 user_text

6. stream = llm_backend.chat(messages_for_llm, stream=True)
7. 邊收 token 邊 yield 給 Interface Layer；收完整段後：
   append(session.messages, {role: assistant, content: full_text, ts: now()})
   session.updated_at = now()
   save_session(session)
```

**觸發時機明確定義**：裁剪/摘要不是「context window 快滿了才臨時處理」，而是**每一輪對話開始組裝
訊息前都會檢查**兩個獨立門檻——`history.max_turns`（輪數上限）與 `history.max_tokens`（原文
token 估算上限，見第 6 節 config），任一項超標就從最舊的一輪開始，邊摘要邊丟，直到兩項都回到
門檻內。摘要用的是「呼叫同一個本地 LLM 做一次性壓縮」，不是另外接一個摘要模型——Phase 1 不引入
第二個模型依賴。若摘要呼叫本身失敗（例如 backend 暫時斷線），退回「直接捨棄最舊一輪」的有損
路徑，並記錄警告，不讓對話卡住（詳見第 7 節）。

`estimate_tokens` 在 Phase 1 用簡單啟發式（如「中文字元數 + 英文詞數 × 1.3」）即可，不需要引入
真正的 tokenizer 依賴；估算保守偏高比精確更重要，因為目的是不要撞到 backend 的硬性 context 上限。

### 3.3 Orchestrator 對 Interface Layer 的 API 契約

Phase 1 的第一個 Interface 是 CLI，跑在同一個 process 內，**不需要真的起一個 HTTP server**——
CLI 直接 `import` 並呼叫 Orchestrator 的 Python 函式即可。但函式簽名刻意 1:1 對應下面這份
「等效 HTTP 契約」，理由是 Phase 2 若語音 client 要跑在獨立 process（例如降低 ASR/TTS 對主
對話迴圈的資源競爭），只需要在 Orchestrator 外面包一層 FastAPI/uvicorn，不必重新設計介面形狀。

```
POST /sessions
  body:   { "persona_id": "chloe-lin" }
  200:    { "session_id": "...", "created_at": "..." }

POST /sessions/{session_id}/messages      # streaming response
  body:   { "content": "早安 Chloe～" }
  200 (chunked / SSE，每行一個 JSON):
    {"type": "token", "delta": "早"}
    {"type": "token", "delta": "安"}
    ...
    {"type": "done", "full_text": "早安！今天喝抹茶了嗎🤍 ...", "turns_trimmed": 0, "summarized": false}
  4xx/5xx:
    {"type": "error", "code": "backend_unreachable" | "persona_invalid" | "timeout", "message": "..."}

GET /sessions/{session_id}/history
  200:    { "messages": [ {role, content, ts}, ... ] }   # 給 UI 重新整理頁面/重連時用
```

對應的 Python 函式簽名（Phase 1 CLI 實際呼叫的介面）：

```python
def create_session(persona_id: str) -> Session: ...

def send_message(session_id: str, content: str) -> Iterator[TokenEvent]:
    # TokenEvent = TokenChunk(delta: str) | Done(full_text: str, turns_trimmed: int, summarized: bool) | Error(code: str, message: str)
    ...

def get_history(session_id: str) -> list[Message]: ...
```

Streaming 語意：`send_message` 是一個 generator，逐 token yield，`Interface Layer` 邊收邊印
（打字機效果）；收到 `Error` 事件即中止本輪但**不清空 session**（使用者可以重新輸入再試一次，
上一輪失敗的使用者訊息保留在歷史中，讓對話不會憑空消失，見第 7 節）。

---

## 4. LLM Inference Backend 整合

### 4.1 API 契約

沿用 02 文件的決定：Orchestrator 只透過 **OpenAI-compatible `/v1/chat/completions`** 呼叫推論
後端，不使用任何後端專屬 SDK。Ollama 同時支援原生 `/api/chat` 與 `/v1/chat/completions`，這裡
**指定用後者**，理由是它是多個候選後端（llama.cpp server、vLLM、LM Studio、KoboldCpp 皆支援
OpenAI-compatible 端點）共通的最小交集，日後要換後端只需換 `base_url` 與 `model` 欄位。

請求範例（`ollama_client.py` 實際會送出的 body）：

```json
{
  "model": "qwen2.5:14b-instruct-q4_K_M",
  "messages": [ /* 第 3.2 節組好的 messages_for_llm */ ],
  "temperature": 0.8,
  "top_p": 0.9,
  "stream": true
}
```

回應是標準 SSE，`choices[0].delta.content` 逐 token 累加，直到收到 `data: [DONE]`。
`ollama_client.py` 把這個 SSE 流轉換成第 3.3 節的 `TokenChunk` 序列，這一層轉換就是「backend
API 契約」與「Orchestrator 對外契約」之間唯一的耦合點，換後端只需要改這一個檔案。

### 4.2 預設模型建議（可執行的預設值，非最終答案）

**明確標記為暫定**：以下假設「中階消費級 GPU，8–12GB VRAM（例如 RTX 3060 12GB / RTX 4060 Ti
16GB / RTX 4070 12GB 這個範圍）」，在拿到使用者實際硬體資訊前先用這組預設讓開發能往前推進，
硬體資訊確認後應由 `local-llm-engineer` 重新核定。

- **預設模型**：`qwen2.5:14b-instruct`，量化 `Q4_K_M`（透過 `ollama pull
  qwen2.5:14b-instruct-q4_K_M`），VRAM 佔用約 9–10GB。
  - 選擇理由：本 repo 大量 KOL 的 `character.md` 是**繁體中文**為主，且語氣要求「中英夾雜、口語、
    帶 emoji」——Qwen 系列在中文（含繁體）指令遵循與口語化程度上，相對同尺寸的 Llama/Mistral
    系列有明顯優勢，這是比純英文 benchmark 分數更貼近本案需求的選擇依據。14B 尺寸在角色一致性與
    多輪對話深度上明顯優於 7B 級模型，落在 01 文件建議的「7B–14B」區間上緣。
  - `num_ctx`（context window）建議先設 `8192`（見第 6 節 config），不用 Qwen2.5 理論支援的
    128K——KV cache 會隨 context 線性吃 VRAM，Phase 1 對話深度用 8K 綽綽有餘，過大只是白佔顯存。
- **VRAM 不足 8GB 時的退階預設**：`qwen2.5:7b-instruct-q4_K_M`（約 4.5GB VRAM），對話深度與
  細膩度會下降，但仍在 01 文件劃定的「不低於 3B」下限之上許多。
- **重要提醒**：這是「模型家族／尺寸／量化等級」層級的預設方向，不是鎖定某個確切版本字串——
  實作當下應先跑 `ollama list`/查詢 Ollama model library，確認是否有更新的同尺寸級 Qwen 版本
  （例如後續的 Qwen3 系列）在 roleplay/多輪對話上有更好實測表現，若有應優先採用，選型邏輯
  （中文能力優先、14B 為預設檔位、Q4_K_M 起跳）不變。
- 本建議刻意**不**指定任何標榜「去審查／abliterated」的角色扮演微調版本——那屬於第 9 節列出的
  內容邊界待決策範圍，模型選型本身保持中性。

### 4.3 與 Phase 2/3 的相容性確認

Streaming 輸出是硬性要求（02 文件已強調），本節選定的 Ollama OpenAI-compatible endpoint 原生
支援 SSE streaming，Phase 2 要把文字流接去 TTS 時，消費的是 Orchestrator 轉出的
`TokenChunk` 序列（第 3.3 節），不需要改這一層。

---

## 5. Interface Layer

### 5.1 決定：Phase 1 預設用 CLI，不是 Web UI

CLI 是 Phase 1 的**唯一預設交付物**。理由：

- Phase 1 要驗證的是「persona 轉換得準不準、Orchestrator 的裁剪/摘要邏輯對不對、換模型會不會動到
  其他層」——這些都跟有沒有瀏覽器介面無關，CLI 把驗證路徑縮到最短，零前端工具鏈（不需要
  bundler、不需要另外跑一個 web server 行程）。
- 02 文件本身也是把 CLI 列為「最小可行版本」，Web UI 列為錦上添花的可選項——本文件把它訂為
  **正式預設**，Web UI 降級為「有餘力再做」的可選增量，不是 Phase 1 的完成條件。
- 極簡 Web UI 之後若要做，因為第 3.3 節的 API 契約已經是 HTTP 形狀，只是加一個單頁 HTML +
  `fetch`/`EventSource` 呼叫同一組端點，不需要重新設計 Orchestrator。

### 5.2 CLI 互動迴圈

```
$ companion chat --persona chloe-lin
[companion] 已載入人格：Chloe Lin（kols/chloe-lin），session: 8e91c4...
[companion] model: qwen2.5:14b-instruct-q4_K_M @ http://localhost:11434
你> 早安 Chloe
Chloe> 早安！今天喝抹茶了嗎🤍 你呢，起床了沒？
你> 還沒起床，好懶
Chloe> 哈哈是不是又想賴床到中午 🫣 快起來啦，不然我要開始碎念了喔
你> /exit
[companion] session 已存檔：data/sessions/8e91c4....json
```

行為要點：

- 啟動時呼叫 `create_session(persona_id)`（第 3.3 節），之後每輸入一行呼叫一次
  `send_message`，逐 token 印出（打字機效果，驗證 streaming 真的有作用）。
- 保留幾個 `/` 開頭的內建指令：`/exit`（存檔並離開）、`/reset`（新開一個 session，同一個
  persona）、`/history`（印出目前 session 的訊息數與 summary 狀態，方便偵錯裁剪/摘要邏輯）。
- 收到 `Error` 事件（第 3.3 節）時印出人類看得懂的錯誤訊息（見第 7 節），不讓整個 CLI 崩潰。

---

## 6. Config

`companion/config/companion.yaml`，Phase 1 最小可行集合：

```yaml
persona:
  kol_id: chloe-lin           # 對應 kols/{kol_id}/，實際載入哪個 KOL 由此決定
  kols_root: ../kols          # 相對 companion/ 的路徑，指向既有 KOL 資料庫

backend:
  provider: ollama
  base_url: http://localhost:11434
  api_path: /v1/chat/completions
  model: qwen2.5:14b-instruct-q4_K_M   # 見 4.2 節，暫定預設
  temperature: 0.8
  top_p: 0.9
  num_ctx: 8192                        # Ollama context window（tokens）
  request_timeout_s: 60

history:
  max_turns: 20                # sliding window：最多保留最近 20 輪原文
  max_tokens: 3072              # 原文視窗的估算 token 上限（不含 system prompt / summary）
  reserved_output_tokens: 512   # 預留給模型輸出，不算進上面兩個門檻的計算基準
  summarization:
    enabled: true              # 見 3.2 節：裁剪時先摘要再丟棄，關閉則直接有損捨棄
    summary_max_tokens: 300

interface:
  mode: cli                     # cli | web（Phase 1 預設 cli，見 5.1 節）

session:
  store_dir: ./data/sessions
  persist: true

logging:
  level: info
```

---

## 7. 錯誤處理與邊界情況（Phase 1 範圍內，只列真正需要現在設計的）

1. **Backend 沒開 / 連不上（如 `ollama serve` 沒跑、model 沒 pull）**：`ollama_client.py`
   捕捉連線錯誤，往上拋出 `Error(code="backend_unreachable")`（第 3.3 節契約）。CLI 印出可操作
   的提示（例如「請確認 `ollama serve` 是否執行中，或執行 `ollama pull
   qwen2.5:14b-instruct-q4_K_M`」），**不清空當前 session**，讓使用者修好環境後可以重新送出同一句
   話繼續對話。
2. **Context 超出上限時摘要本身失敗**（例如摘要那次呼叫也連不上 backend）：退回 3.2 節定義的
   「直接捨棄最舊一輪」有損路徑，記錄一則 warning log，不阻塞當前這輪回覆——寧可對話繼續但損失
   一點記憶，也不要讓使用者卡在無法送出訊息的狀態。
3. **Persona 檔案缺必要欄位**：`persona/loader.py` 啟動時（建立 session 前）就對照
   `kols/schema.json` 做最基本的必要欄位檢查（`id`/`identity`/`persona`/`content`/`social` 等
   `required` 欄位），檢查失敗直接拒絕建立 session 並丟出清楚指出缺哪個欄位路徑的錯誤，**不要**
   靜默用空值頂替繼續產生殘缺的 system prompt——人格資料是唯一真相來源，壞資料應該在源頭被擋下來，
   而不是在對話品質變差之後才被發現。
4. **Persona 檔案在對話進行中被編輯**：第 3.2 節的 `persona_prompt_fingerprint` 比對機制會在
   下一輪自動偵測並重建 system prompt，只記錄一則 info log，不回溯改寫已存的歷史訊息。
5. **Backend 逾時 / 回應中斷**：套用 `request_timeout_s`（config 第 6 節），逾時比照第 1 點走
   `Error(code="timeout")` 路徑，允許使用者重試。

---

## 8. 與 Phase 2 / Phase 3 預留介面點的相容性確認

本文件不設計 Phase 2/3，只逐點確認前面 1–7 節的設計沒有堵死擴充空間：

- **Interface Layer**：Phase 2 語音 client 在輸入端接 ASR（把辨識出的文字丟進與 CLI 完全相同的
  `send_message` 契約）、輸出端接 TTS（消費與 CLI 完全相同的 `TokenChunk` streaming
  序列）——不需要修改 Orchestrator。Phase 3 虛擬形象/直播同理，消費同一組 streaming 文字輸出去
  驅動口型/表情，`companion/src/companion/avatar/` 的 stub README 會記錄這個消費點。
- **Orchestrator**：Session schema（3.1 節）與 API 契約（3.3 節）都沒有任何「文字一定是使用者
  親手打的」假設——語音辨識出來的文字、CLI 打字打出來的文字，走的是同一條路徑。
- **LLM Backend**：streaming 是硬性要求且已經是 SSE token-level，滿足 01 文件延遲觀察那段
  「語音生成不能是事後疊加批次處理」的教訓（04-1 節倒數第二段），不需要為 Phase 2 重新選型。
- **Persona Layer**：完全不受語音/形象影響；如果 Phase 3 需要「情緒/表情」線索去驅動虛擬形象，
  那會是從既有 persona 欄位額外衍生的**新增欄位**（例如從 `voice_tone`/`humor_style` 推導
  表情傾向），而不是重新設計 persona 轉換演算法——但這個衍生邏輯本身現在不設計，留給 Phase 3。

---

## 9. 仍待決策（不在本文件解決，沿用 02 文件既有清單，僅標註哪些現在有了預設值可先動工）

沿用 `02-architecture-exploration.md` 第 98–111 行列出的 5 項待決策，狀態更新：

1. **單引擎多角色 vs 各角色獨立部署** —— 仍待決策；本文件的 config／session 設計是「一個
   session 綁一個 persona_id」，兩種部署模式都相容，不受本文件影響。
2. **內容邊界（人設扮演尺度 vs 有害內容紅線）** —— 仍待決策，本文件刻意在 2.4 節留白、未預設任何
   立場，見該節說明。
3. **目標硬體規格** —— 本文件第 4.2 節提供了一組**暫定可執行預設**（中階 GPU / Qwen2.5-14B
   Q4_K_M），讓開發不必等待就能先動工，但明確標記為暫定，硬體資訊確認後應重新核定。
4. **第一個試跑角色** —— 仍待決策；本文件用 `chloe-lin` 的真實資料做第 2.5 節的渲染範例僅為
   demonstrate 演算法輸出，不代表已選定它作為正式試跑對象。
5. **Phase 2/3 觸發時機** —— 仍待決策，不影響本文件範圍。

本文件新增的、實作時會浮現的次要待決策（非阻塞，記錄備查）：
- Session 儲存從「單一 JSON 檔」遷移到 SQLite 的時機（若之後需要跨 session 查詢/併發存取）。
- `estimate_tokens` 的啟發式準確度是否足夠，或需要換成真正的 tokenizer（會增加一個依賴）。
- `summarize_via_llm` 用同一個對話模型做摘要，是否在對話品質或延遲上有明顯負面影響，值得在
  試跑階段實測後再決定要不要換一個更小的專用摘要模型。
