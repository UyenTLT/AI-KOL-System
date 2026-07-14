# CUDA Runbook — full setup to run the AI-KOL system on an NVIDIA machine

One-file, end-to-end guide to bring the whole pipeline up on a CUDA box: photoreal image +
face-lock, natural per-KOL **voice** (GPT-SoVITS), **talking-head / realtime avatar** (LiveTalking),
the **LLM brain** (persona + comment classify), and wiring it all into the repo's apps.

> ⚠️ Written without a GPU to test on — **verify each command against the upstream repo** (this field
> moves fast). Apple Silicon cannot run the CUDA-only parts (lip-sync, LoRA training, realtime avatar);
> that is the whole reason this box is needed.

Maps to the research docs: image `research/local-ai-companion/09`, voice `10`, comment loop `11`,
architecture/avatar `03/04/05/08`, growth `12`; and to `tools/` (vlog_app, talking_web, tts_train).

---

## 0. Hardware & OS requirements

| Component | Min VRAM | Comfortable | Notes |
|---|---|---|---|
| Image gen (Flux + LoRA/PuLID) | 8-12 GB | 24 GB | 24 GB to **train** character LoRA locally |
| Voice fine-tune (GPT-SoVITS) | 6-8 GB | 12 GB | training + `api_v2` inference |
| Lip-sync / LiveTalking (Wav2Lip/MuseTalk) | ~4-8 GB | 12 GB | Issue #525: T4/A30 ~4 GB reported OK |
| LLM brain (qwen2.5 14B q4 / 3B) | 8-12 GB | 16-24 GB | or run via Ollama with CPU offload |
| **Running several at once** | — | **24 GB (RTX 4090 / 5090)** | VRAM is shared; stage or use 2 GPUs |

- OS: Ubuntu 22.04 recommended (Windows works but LiveTalking is smoother on Linux).
- Base: NVIDIA driver + **CUDA 12.x**, `git`, `ffmpeg`, `python 3.10`, `conda` (or venv), ~100 GB disk.

```bash
sudo apt update && sudo apt install -y git ffmpeg build-essential
nvidia-smi          # confirm driver + CUDA visible
git clone git@github.com:UyenTLT/AI-KOL-System.git && cd AI-KOL-System
```

---

## A. Image generation — photoreal + face-locked KOL images (research/09)

Goal: same face across every post. Options: **ComfyUI** (flexible) with Flux + a **character LoRA**
(strongest consistency) or **PuLID/InstantID** (no-train) + **ReActor** face-swap.

```bash
# ComfyUI
git clone https://github.com/comfyanonymous/ComfyUI && cd ComfyUI
python -m venv venv && . venv/bin/activate
pip install -r requirements.txt
# models -> models/checkpoints (Flux.1-dev or a photoreal SDXL e.g. RealVisXL), + realism/skin LoRAs
# custom nodes: PuLID-Flux, InstantID, ReActor, face-detailer
python main.py --listen   # http://<box>:8188
```

**Train a character LoRA (locks the face, needs ~24 GB):**
```bash
git clone https://github.com/ostris/ai-toolkit   # or kohya-ss/sd-scripts
# dataset = 15-25 approved seed images of one KOL (see kols/<id>/images/soul_v1_training/)
# train -> a .safetensors LoRA; record it in kols/<id>/profile.json -> ai_assets
```
Anti "AI-look" (from research/09): realism/skin LoRA + low CFG (2.5-3.5), phone-camera/imperfection
prompts, film grain + face-detailer post, everyday candid motion.

---

## B. Voice — natural per-KOL voice via GPT-SoVITS (tools/tts_train, research/10)

Full detail already in `tools/tts_train/README.md`. Summary:

```bash
git clone https://github.com/RVC-Boss/GPT-SoVITS && cd GPT-SoVITS
# install per its README + download pretrained base models
# 1) data: put 5-30 min clean speech in kols/<id>/voice/raw/ then:
python ../AI-KOL-System/tools/tts_train/data_prep.py <kol_id>       # resample + Whisper -> .list
# 2) fine-tune in the GPT-SoVITS WebUI  -> SoVITS .pth + GPT .ckpt
# 3) fill kols/<id>/profile.json -> ai_assets.voice (weights, reference_audio, reference_text, api)
# 4) serve inference:
python api_v2.py -a 127.0.0.1 -p 9880 -c GPT_SoVITS/configs/tts_infer.yaml
```
Verify: `python tools/tts_train/tts_client.py <kol_id> "大家好 Hi" zh /tmp/v.wav`.
One reference voice speaks both **ZH + EN**. (Realtime streaming later -> CosyVoice2, same client shape.)

---

## C. Talking-head + realtime avatar — LiveTalking (research/04/05/08)

Goal: **type -> the KOL speaks with lip-sync -> RTMP / virtual camera** (the livetalking.top capability).

```bash
git clone https://github.com/lipku/LiveTalking && cd LiveTalking
conda create -n livetalking python=3.10 && conda activate livetalking
# install torch (CUDA build) + requirements per its README; download model weights
# POC main model = Wav2Lip (see research/08); MuseTalk/ER-NeRF are heavier/higher quality
python app.py --model wav2lip --avatar_id <kol_avatar> --tts gpt-sovits   # flags per its docs
```
- **Echo mode first** (POC): text in -> voice out -> lip-synced video/stream. This is the scope in
  `research/05`; do NOT rely on mid-sentence interruption (Issue #510, ~3 s, unresolved).
- Voice source = the GPT-SoVITS API from step B (or CosyVoice2, which is native to LiveTalking).
- Output to OBS via virtual camera / RTMP for streaming.

---

## D. LLM brain — persona replies + comment classification (research/03/11)

```bash
# simplest: Ollama on GPU
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5:7b      # persona replies (14b if VRAM allows)
ollama pull qwen2.5:3b      # cheap comment classifier (research/11)
# (higher throughput: run via vLLM instead of Ollama)
```
- Persona brain: builds the system prompt from `kols/<id>/profile.json` (research/03).
- Comment loop: rule prefilter -> 3B classify (JSON) -> policy -> persona reply, using
  `kols/<id>/products.json` for prices/links (research/11). Keep `comment_policy_mode: suggest`.

---

## E. (Optional) Real-motion video — image-to-video (research/09)

For true motion shots (vs the local Ken-Burns vlog): **Wan2.x** or **LTX-Video** in ComfyUI.
Generate face-locked keyframes (step A) -> I2V -> assemble. Heaviest VRAM; run when others are idle.

---

## F. Wire it into the repo apps

```bash
export TTS_API=http://127.0.0.1:9880        # GPT-SoVITS from step B

# Vlog app: swap `say` for the real voice (tools/vlog_app.py -> use tts_train.tts_client.speak)
python3 tools/vlog_app.py lin-wanqing "雨天的慢生活"

# Talking-web app: same swap; with LiveTalking (step C) it becomes real lip-sync + streaming
python3 tools/talking_web/server.py         # http://<box>:7860
```
`tts_client.speak()` uses GPT-SoVITS when `TTS_API` is reachable, else falls back to `say` — so
apps never hard-fail during setup.

---

## G. Recommended bring-up order

1. `nvidia-smi` + base deps + clone repo.
2. **D. LLM** (fast win, verifies GPU) -> **B. Voice** -> **A. Images/LoRA**.
3. **C. LiveTalking** echo mode -> connect the step-B voice.
4. Wire apps (F). Then optional **E. motion video**.

## H. VRAM coexistence

On a single 24 GB card, don't run image-training + LiveTalking + 14B LLM at once — stage them, use
a smaller LLM (7B/3B) while lip-sync runs, or add a second GPU. Log which component owns the card.

## I. Compliance & safety (do not skip)

- **AI disclosure**: label the avatar/replies as AI where required (CN 2026/06 rules, EU AI Act).
- **Platform ToS** (research/11): IG/YouTube APIs OK; **TikTok has no official comment/live-chat
  API** -> keep auto off there. Read comments only on the KOL's own (first-party) content.
- Human-in-the-loop for money/links/blocks until metrics justify `auto`.
- Original identities only — never clone a real person's face or voice without permission.

## J. Per-component verification checklist

- [ ] A: ComfyUI renders a face-locked KOL image; LoRA trained + recorded in `ai_assets`.
- [ ] B: `tts_client.py` returns a natural wav from the GPT-SoVITS API (not the `say` fallback).
- [ ] C: typing text makes the avatar speak with lip-sync; output reaches OBS/RTMP.
- [ ] D: `ollama run qwen2.5:7b` replies in persona; 3B returns valid classification JSON.
- [ ] F: `vlog_app` / `talking_web` use the real voice (TTS_API set), not `say`.
