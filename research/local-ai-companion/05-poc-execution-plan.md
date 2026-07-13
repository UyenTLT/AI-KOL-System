> **執行環境提醒**：本文件是要在**你自己有 NVIDIA GPU 的機器**上執行的實驗計畫——目前產出這份文件
> 的雲端工作環境本身沒有 GPU（已用 `nvidia-smi` 確認），所以以下所有指令**尚未在任何機器上實際跑過
> 一遍**，是依 `lipku/LiveTalking` 官方 README / `docs/api.md` / `config.py` 逐條核實的規格整理而成，
> 不是憑空推測。請照 Stage 0 開始，每個 Stage 都有「驗收標準」，跑不過就停下來看對應的疑難排解，
> 不要跳步。完成後請把第 9 節「執行記錄表」填回來，我們會拿真實數據回填 `04` 文件。

# POC 實驗計畫書 — 本地即時真人數位人（文字 → 語音 → 直播）

**對應決策文件**：`04-realtime-avatar-integration.md`（已選定 `lipku/LiveTalking`，可行性評估 ~91%）
**本文件目的**：把那份文件第 6 節的「落地步驟」展開成可以逐字照做的實驗計畫，每一步都有明確指令、
預期結果、驗收判準、失敗時的處置。

---

## 1. 實驗目的與假設

**驗證假設**：在一台配備 NVIDIA GPU 的本地機器上，`lipku/LiveTalking` 可以在**不依賴雲端**的情況下，
把「使用者打字輸入的文案」轉成「真人樣貌數位人開口說話（聲音可為克隆聲）」，並把畫面即時輸出到可
直播的管道（虛擬攝影機 → OBS，或 RTMP）。

**四個驗收條件**（沿用 04 文件第 0 節）：

| # | 條件 | 本計畫對應的驗收 Stage |
|---|---|---|
| A | 全程本地執行 | Stage 0（環境）＋ Stage 2 起全程斷網測試一次 |
| B | 打字 → 講出來 | Stage 2 |
| C | 真人樣貌 + 對嘴 | Stage 1、Stage 2 |
| D | 能推到直播管道 | Stage 3 |

只要 Stage 0–3 全部通過，POC 即宣告成功（可行性從評估的 91% 落實為**實測驗證**）。Stage 4–5 是把
POC 升級成「我們自己的角色」與「有人格會對話」，屬於加分項，不是 POC 過關的必要條件。

---

## 2. 時程總覽（估工時，供排程參考）

| Stage | 內容 | 預估工時 | 是否阻塞後續 |
|---|---|---|---|
| 0 | 環境建置（driver/CUDA/conda/依賴） | 1–3 小時（依網速與是否已裝過 CUDA 而定） | 是 |
| 1 | 跑通官方 demo（echo 模式看得到真人臉） | 0.5–1 小時 | 是 |
| 2 | 文字→語音→對嘴 驗收（含斷網測試） | 0.5 小時 | 是 |
| 3 | 直播輸出驗收（虛擬攝影機→OBS，選配 RTMP） | 1–2 小時 | 是（D 條件） |
| 4 | 換成自訂角色形象＋聲音克隆 | 2–4 小時（含素材準備） | 否（可延後） |
| 5 | 接人格化對話（03 文件 Orchestrator） | 半天以上，另立計畫 | 否（獨立里程碑） |

**POC 核心（Stage 0–3）總計抓 1 個工作天**是合理預期；第一次裝 CUDA 環境若不順可能多花半天排除依賴問題（見第 8 節）。

---

## 3. 前置需求檢查清單（開始前逐項確認）

### 3.1 硬體 — 這是決定路徑的關鍵 Gate

在你的目標機器上執行：

```bash
nvidia-smi
```

- **看得到輸出且是 NVIDIA GPU** → 繼續。記下：GPU 型號、VRAM 容量（`nvidia-smi` 輸出裡的
  `Memory-Usage` 欄，例如 `12288MiB`）。
- **看不到輸出 / command not found** → 這台機器沒有可用的 NVIDIA GPU，**本 POC 的即時路線在這台機器
  上不可行**，請改用 04 文件第 7 節的備援方案（HeyGem 離線出片），或換一台有 GPU 的機器再繼續本文件。

**路徑判斷（依 04 文件第 4 節）**：

| VRAM | 走的路徑 | 本文件後續指令用的 `--model` 值 |
|---|---|---|
| ≥ 8GB（如 RTX 3060/3070/4060 Ti） | Wav2Lip256 | `wav2lip`（也是官方預設） |
| ≥ 12–16GB 且想要更好畫質（如 RTX 3080Ti/3090/4090） | MuseTalk | `musetalk` |
| < 8GB 或非 NVIDIA | 不建議跑即時路線 | — |

本文件下面的指令**以 Wav2Lip 路徑為主線示範**（因為官方權重下載連結明確、VRAM 需求最低、最適合
第一次 POC）；MuseTalk 路徑的模型下載步驟官方 README 未列出明確連結，需要時再另外查證，不在本次
POC 主線內，先用 Wav2Lip 打通 A–D 四條件即可證明可行性。

### 3.2 作業系統與軟體

- **作業系統**：Ubuntu 22.04（官方實測版本）。Windows 使用者建議用 **WSL2 + Ubuntu 22.04**，並確認
  WSL2 能存取 GPU（`nvidia-smi` 在 WSL2 內也要能跑出結果）。
- **NVIDIA Driver**：需支援 CUDA 12.8 的 driver（一般是較新的 driver 版本；用 `nvidia-smi` 輸出右上角
  的 `CUDA Version` 欄確認，需 ≥ 12.8，若較舊需先更新 driver）。
- **必要工具**：`git`、`ffmpeg`、`conda`（Miniconda 即可）。檢查：
  ```bash
  git --version
  ffmpeg -version
  conda --version
  ```
  缺哪個就先裝哪個（Ubuntu: `sudo apt install -y git ffmpeg`；conda 用官方 Miniconda 安裝腳本）。
- **磁碟空間**：預留至少 **15–20GB**（conda 環境 + PyTorch + CUDA 相關套件 + 模型權重 + 之後的錄影
  檔案）。
- **網路**：Stage 0–1 需要網路（clone repo、裝套件、下載模型權重）。之後可以斷網跑，用來驗證條件 A。
- **直播輸出用**：先裝好 **OBS Studio**（用於 Stage 3 的虛擬攝影機驗收）。

### 3.3 合規前置確認（開始前想清楚，不是技術步驟但同樣是前置條件）

依 04 文件第 8 節：
- 若 Stage 4 要用「真人樣貌影片」當形象來源，確認素材**你有權使用**（自己入鏡、或已取得當事人同意，
  或使用本專案自產的 AI 生成人像素材而非真實他人）。
- 若要做聲音克隆，同樣需要**聲音使用權**。
- 若之後真的公開直播，先確認目標平台/地區是否要求揭露「主播為 AI 生成」。

---

## 4. Stage 0 — 環境建置

**目標**：GPU、driver、CUDA、Python 環境全部就緒，`torch.cuda.is_available()` 回傳 `True`。

```bash
# 4.1 取得原始碼
git clone https://github.com/lipku/LiveTalking.git
cd LiveTalking

# 4.2 建立獨立 Python 環境（避免污染系統 Python）
conda create -n livetalking python=3.12 -y
conda activate livetalking

# 4.3 安裝 GPU 版 PyTorch（版本需對應你的 CUDA；下方是官方指定版本，
#     若 nvidia-smi 顯示的 CUDA Version 不是 12.8，先查 PyTorch 官網對應 wheel 再換版本號）
pip install torch==2.9.1 torchvision==0.24.1 torchaudio==2.9.1 \
  --index-url https://download.pytorch.org/whl/cu128

# 4.4 安裝專案相依套件
pip install -r requirements.txt
```

**驗收判準**：

```bash
python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

必須印出 `True` 與你的 GPU 型號名稱。**印出 `False` 就不要往下走**——先解決 CUDA/driver/PyTorch
版本不匹配問題（見第 8 節疑難排解），這是所有後續步驟的地基。

---

## 5. Stage 1 — 跑通官方 Demo（先用官方內建 avatar，不用自己的角色）

**目標**：先證明整條「模型推論 + 對嘴 + 出畫面」的路能通，避免把「環境問題」和「自訂角色問題」混在
一起除錯。

```bash
# 5.1 下載模型權重（連結見官方 README「2.1 下载模型」，Quark 網盤或 Google Drive 擇一）
#     取得 wav2lip256.pth 後：
mkdir -p models
cp /path/to/downloaded/wav2lip256.pth models/wav2lip.pth   # 注意：需重新命名為 wav2lip.pth

#     取得 wav2lip256_avatar1.tar.gz 後：
mkdir -p data/avatars
tar -xzf /path/to/downloaded/wav2lip256_avatar1.tar.gz -C data/avatars/

# 5.2 啟動服務（先用預設 webrtc transport，最簡單驗證用）
python app.py --transport webrtc --model wav2lip --avatar_id wav2lip256_avatar1
```

啟動時終端機應顯示 server 已在 `listenport`（預設 `8010`）啟動、沒有例外堆疊。**若機器有防火牆**，
需開放 `TCP:8010` 與 `UDP:1-65536`（WebRTC 用）。

**驗收判準**：瀏覽器開 `http://<這台機器的IP或localhost>:8010/index.html`，畫面出現內建的示範數位人
（真人樣貌，非卡通），且**沒有錯誤訊息**、視訊有畫面在跑（即使還沒開口說話）。

> 停在這裡先不要做任何自訂——這就是 Stage 1 的完整驗收標準。

---

## 6. Stage 2 — 文字 → 語音 → 對嘴（核心條件 B + C）

**目標**：驗證「你打字，數位人講出來」。

在瀏覽器頁面連線建立後（會拿到一個 `sessionid`，可在頁面或瀏覽器開發工具的網路請求中看到），用另一
個終端機呼叫文字驅動 API：

```bash
curl -X POST http://localhost:8010/human \
  -H "Content-Type: application/json" \
  -d '{
        "sessionid": "<剛剛連線拿到的 sessionid>",
        "text": "大家好，這是一個本地端即時數位人的測試，如果你聽得到我說話，代表整條鏈路打通了。",
        "type": "echo",
        "interrupt": false
      }'
```

`"type": "echo"` 就是條件 B 要的「直接把文字講出來」模式（不需要接 LLM）。預期回應：
`{"code": 0, "msg": "ok"}`。

**驗收判準**（回到瀏覽器畫面觀察）：
1. 數位人**開口說話**，聽得到語音（預設 TTS 是 `edgetts`，免額外設定）。
2. **嘴型與語音同步**（不是聲音在放、嘴巴不動，或嘴動得和字對不上）。
3. 用 `date` 記錄「送出 curl 的時間」與「聽到第一個字的時間」，粗估端到端延遲（供 04 文件回填用）。
4. 觀察終端機 log 或畫面上的 `inferfps` / `finalfps` 數值（官方定義：兩者皆需 **≥ 25** 才算即時），
   記錄下來。

**條件 A（本地）加測**：此步驟通過後，**斷開這台機器的網路**（或用防火牆規則擋掉對外連線），重複
同一個 `curl` 指令，確認**依然正常說話**（EdgeTTS 若走雲端 API 則斷網會失敗——這點需要現場驗證：若
EdgeTTS 依賴微軟雲端服務而斷網失敗，記錄下來，並改用需要本地部署的 TTS（如 GPT-SoVITS，見 Stage 4）
才能完全滿足條件 A；這是本計畫刻意設計的一個「假設驗證點」，不預先假設結果）。

---

## 7. Stage 3 — 直播輸出驗收（核心條件 D）

**目標**：畫面能被推到可直播的地方。分兩條路，**建議先做虛擬攝影機**（最簡單、最快驗證）。

### 7.1 路線一：虛擬攝影機 → OBS（建議先做這個）

```bash
# 停掉 Stage 1 的 webrtc 服務，改用 virtualcam transport 重新啟動
python app.py --transport virtualcam --model wav2lip --avatar_id wav2lip256_avatar1
```

- 開啟 **OBS Studio** → 新增來源 → 「視訊擷取裝置」→ 選擇 LiveTalking 產生的虛擬攝影機裝置。
- 重複 Stage 2 的 `curl` 指令送一句文字。

**驗收判準**：OBS 預覽畫面裡看到數位人開口說話、嘴型同步。此時 OBS 已經可以「開始直播」推到任何
你有帳號的平台（YouTube/Twitch/…）——**建議先用平台的「私人／未公開」直播模式測試**，不要一開始就
公開播出。

### 7.2 路線二：RTMP 直推（進階、選配）

```bash
python app.py --transport rtmp --model wav2lip --avatar_id wav2lip256_avatar1 \
  --push_url "rtmp://<你的推流位址>/live/<streamkey>"
```

> **注意**：`--push_url` 的預設值是本地 WHIP 端點（`http://localhost:1985/rtc/v1/whip/...`），代表
> 官方設計上 RTMP 這條路可能需要搭配一個 WHIP↔RTMP 轉換服務（例如 SRS）才能直接對接一般直播平台的
> RTMP 位址；若直接填平台的 RTMP 位址不通，屬於預期中的「進階選配」問題，**不影響 POC 主線**（路線
> 一虛擬攝影機已經滿足條件 D），有餘力再深入研究 SRS 搭建。

**驗收判準（路線二成立時）**：目標直播平台的「私人測試串流」看得到畫面與聲音，且與路線一的口型/
聲音同步表現一致。

---

## 8. 疑難排解對照表（依社群回報與官方文件整理，先查這裡再自行 google）

| 症狀 | 可能原因 | 處置 |
|---|---|---|
| `torch.cuda.is_available()` 回傳 `False` | Driver 版本與 CUDA 12.8 不匹配 | 用 `nvidia-smi` 確認 `CUDA Version` 欄，更新 driver；或改裝對應該 CUDA 版本的 PyTorch wheel |
| 安裝依賴時大量版本衝突 / 找不到套件 | 系統 Python 與專案要求的 3.12 混用 | 務必用獨立 conda 環境（Stage 0 已這樣做），不要用系統 Python |
| 啟動後 CUDA out of memory (OOM) | VRAM 不足以跑選定模型/batch size | 降低 `--batch_size`（預設 16，可調小）；改走 Wav2Lip 而非 MuseTalk；確認沒有其他程式占用 VRAM（`nvidia-smi` 看 `Processes`） |
| 連線建立、TTS 顯示成功，但畫面卡住/黑屏 | 常見於社群回報的「連線狀態失敗」類問題 | 檢查 `UDP:1-65536` 是否真的開放（NAT/防火牆常見肇因）；先在同一台機器用 `localhost` 測試排除網路因素 |
| Docker 啟動報 `could not select device driver "" with capabilities: [[gpu]]` | 沒裝 NVIDIA Container Toolkit，Docker 看不到 GPU | 安裝 `nvidia-container-toolkit` 並依官方文件設定 Docker runtime；或不用 Docker，走本文件的原生安裝路徑 |
| `inferfps`/`finalfps` 明顯低於 25 | GPU 效能不足、batch size 過大、或同機還跑其他吃 GPU 的程式 | 降 batch size；確認沒有同時跑本地 LLM/其他推論；必要時換路徑（Wav2Lip 比 MuseTalk 省資源） |
| 斷網後 TTS 失效 | 使用的 TTS 引擎（如 EdgeTTS）本身依賴雲端服務 | 這是條件 A 的真實限制，記錄下來；若要 100% 離線，改走 Stage 4 的 GPT-SoVITS（本地部署的 TTS） |

若以上都排不掉，查官方 GitHub Issues（`https://github.com/lipku/LiveTalking/issues`）搜尋錯誤訊息
關鍵字，這個 repo 目前有數百個已回報 issue，多數常見問題已有人問過。

---

## 9. 執行記錄表（跑完請填回來，我們拿這份數據回填 04 文件）

```
日期：__________
機器規格：GPU 型號 __________ / VRAM __________ / OS __________ / Driver CUDA 版本 __________
路徑：Wav2Lip / MuseTalk（圈選）

Stage 0（環境）：通過 / 不通過，卡在哪一步：__________
Stage 1（demo 跑通）：通過 / 不通過
Stage 2（文字→語音→對嘴）：
  - 端到端延遲（送出到聽到第一個字）：______ 秒
  - inferfps：______  finalfps：______（是否 ≥25：是/否）
  - 斷網測試（條件 A）結果：EdgeTTS 斷網後 正常/失敗
Stage 3（直播輸出）：
  - 虛擬攝影機→OBS：通過 / 不通過
  - RTMP 直推（選配）：通過 / 不通過 / 未測試
整體 POC 結論：四條件（A/B/C/D）是否全通過：是 / 否，未通過項目與原因：__________
```

---

## 10. POC 完成後的下一步

1. **Stage 0–3 全過**：POC 成立，可行性從「評估」升級為「實測驗證」。回填第 9 節數據到
   `04-realtime-avatar-integration.md`，並開始 Stage 4（換成本專案某個 KOL 的形象與聲音）。
2. **Stage 0–3 部分卡關**：記錄卡在哪個 Stage、什麼錯誤，這本身就是有價值的產出——代表可行性評估
   需要下修或補上前置條件（例如「需要更高階 GPU」），回報回來由 `livestream-tech-specialist` 重新
   評估。
3. **Stage 4（自訂角色）**：素材需求——一段你要用的「真人樣貌」影片（自己入鏡、已授權素材，或本
   repo 未來產出的 AI 生成人像影片皆可，見 3.3 節合規確認），透過 `/avatar.html` 上傳生成形象；聲音
   克隆需另外部署 GPT-SoVITS 或 CosyVoice 作為 `--tts` 引擎並設定 `--REF_FILE`/`--REF_TEXT`/
   `--TTS_SERVER`（這部分官方 README 未給完整步驟，需要時另立一份專門的聲音克隆設定文件）。
4. **Stage 5（接人格化對話）**：把 `03-phase1-detailed-design.md` 的 Orchestrator 輸出接到 `/human`
   的 `type: "chat"` 模式或持續用 `echo` 模式餵送，屬於獨立里程碑，建議等 Stage 0–4 都穩定後再排。
