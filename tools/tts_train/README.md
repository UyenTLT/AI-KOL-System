# tts_train — Per-KOL voice fine-tuning (GPT-SoVITS, CUDA)

Production-grade natural voice for each KOL by **fine-tuning GPT-SoVITS v3** on the character's
voice, then serving it over an HTTP API that the vlog app / talking-web app call instead of
macOS `say`. This is the "strongest" path from `reports/` and
`research/local-ai-companion/10-local-voice-stack.md`.

> ⚠️ **Runs on an NVIDIA / CUDA machine only** — NOT on Apple Silicon. The code here was written
> on a Mac and is **untested locally**; run + verify on the GPU box. GPT-SoVITS also has a great
> WebUI that does slicing/ASR/training — this folder just wraps data prep + inference + integration.

Why GPT-SoVITS v3: highest speaker similarity when fine-tuned with little data (~5-30 min),
native ZH + EN (+ JP), one reference voice speaks both languages. For realtime streaming later
(live digital-human), swap the engine for **CosyVoice2** — same client shape.

---

## 0. Requirements (GPU box)

- NVIDIA GPU, CUDA (>= 8-12 GB VRAM; 16-24 GB comfortable), Python 3.10, ffmpeg.
- GPT-SoVITS: `git clone https://github.com/RVC-Boss/GPT-SoVITS` and install per its README
  (download the pretrained base models it lists).
- Optional for data prep here: `pip install faster-whisper` (auto-transcribe reference audio).

## 1. Get ~5-30 min of clean speech per KOL

Two options:
- **Record / collect** real clean voice-over (best).
- **Bootstrap** (no real voice): generate ~20-30 min with a zero-shot model (CosyVoice2 / XTTS)
  from a chosen reference timbre, then fine-tune GPT-SoVITS on it to *lock* that voice. (See the
  PDF report, section 4.)

Put raw files in `kols/<id>/voice/raw/`.

## 2. Prepare data

```bash
python tools/tts_train/data_prep.py <kol_id>       # resample 32k mono; auto-transcribe if faster-whisper is installed
# -> kols/<id>/voice/dataset/*.wav  +  kols/<id>/voice/dataset/<kol>.list  (GPT-SoVITS format)
```
The `.list` format is `wav_path|speaker|lang|text`. If faster-whisper is not installed, use the
GPT-SoVITS **WebUI** to slice + ASR instead (it produces the same `.list`).

## 3. Fine-tune (GPT-SoVITS WebUI)

In the GPT-SoVITS WebUI: load the `.list` + dataset -> train **SoVITS** then **GPT**. Outputs:
- SoVITS weights: `SoVITS_weights_v3/<name>.pth`
- GPT weights:    `GPT_weights_v3/<name>.ckpt`

Pick a ~5-10 s clean **reference clip** + its exact transcript (used as the prompt at inference).

## 4. Record the voice in the KOL profile

Fill `kols/<id>/profile.json -> ai_assets.voice`:
```json
"voice": {
  "engine": "gpt-sovits",
  "voice_id": "<kol_id>-v1",
  "gpt_weights":   "GPT_weights_v3/<name>.ckpt",
  "sovits_weights":"SoVITS_weights_v3/<name>.pth",
  "reference_audio":"kols/<id>/voice/ref.wav",
  "reference_text": "<exact transcript of ref.wav>",
  "reference_lang": "zh",
  "api": "http://127.0.0.1:9880"
}
```

## 5. Serve inference API

```bash
# in the GPT-SoVITS repo
python api_v2.py -a 127.0.0.1 -p 9880 -c GPT_SoVITS/configs/tts_infer.yaml
```

## 6. Use it

```bash
python tools/tts_train/tts_client.py <kol_id> "大家好，今天分享一個好物。Hi everyone!" zh out.wav
```
`tts_client.speak()` reads `ai_assets.voice`, sets the KOL's weights, synthesizes with the
reference prompt, and saves a wav. If the API is unreachable it **falls back to `say`** so nothing
breaks.

## 7. Wire into the apps (replace `say`)

In `tools/vlog_app.py` and `tools/talking_web/server.py`, swap the `say` call for:
```python
from tools.tts_train.tts_client import speak
speak(kol_id, text, lang, wav_path)   # GPT-SoVITS if TTS_API reachable, else say fallback
```
Set `TTS_API=http://127.0.0.1:9880` in the environment on the GPU box.

## Evaluation

- Speaker similarity (SIM) vs the reference, WER via ASR on the output, and a quick listen (MOS).
- Iterate: more/cleaner data -> higher similarity. Keep the reference clip clean and consistent.
