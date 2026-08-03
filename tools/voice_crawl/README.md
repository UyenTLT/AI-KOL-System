# voice_crawl — voice data → natural cloned voice → realtime lip-sync

Turns audio (crawled from podcasts/videos, or synthesized) into a **GPT-SoVITS training
set**, fine-tunes a per-KOL voice, and drives a **realtime lip-synced avatar**.

```
 bootstrap_timbre.py ──┐
 (synthetic voice)     ├─→ kols/<id>/voice/dataset/*.wav + <id>.list
 crawl.py ─────────────┘            │
 (podcast / video / files)          ↓
                          GPT-SoVITS fine-tune  →  api_v2 :9880
                                    │
                                    ↓
                          LiveTalking  →  lip-synced avatar → OBS / RTMP
```

---

## Why not the older scripts

`crawl.py` replaces the fixed-duration chunking in `tools/tts_train/podcast_to_trainset.py`
and the root-level `download_*.py` one-offs. Fixed-time cuts slice words in half, keep
background music, and blend every speaker in the recording into one "voice" — GPT-SoVITS
then learns an averaged, smeared timbre. This slices on **sentence and pause boundaries**
from word-level ASR timestamps, and gates every clip through measured QC.

---

## 1. Get voice data

### Option A — synthetic bootstrap (no real person; the default here)

Follows `CUDA_SETUP.md` §I ("Original identities only — never clone a real person's face or
voice without permission"). Synthesize a consistent timbre, then let GPT-SoVITS lock it, and
the KOL owns a voice that never belonged to anyone.

```bash
# see what's available (EN/ZH only)
python tools/voice_crawl/bootstrap_timbre.py <kol_id> --list-voices

# a bilingual KOL needs ONE timbre that speaks both languages -> use a Multilingual voice
python tools/voice_crawl/bootstrap_timbre.py lena-chen \
    --voice en-US-AvaMultilingualNeural --lang zh,en
```

Because the text is known up front there is **no ASR step**, so transcripts are exact —
strictly cleaner than anything crawled. It also auto-selects `voice/ref.wav` + `ref.txt`
(the 3–10 s prompt clip GPT-SoVITS needs at inference).

The built-in seed bank is 40 lines ≈ 3 min: enough to prove the pipeline, **not** enough to
fine-tune. Generate a real corpus with `corpus_builder.py`:

```bash
python tools/voice_crawl/corpus_builder.py --minutes 30 -o kols/lena-chen/voice/corpus.txt
python tools/voice_crawl/bootstrap_timbre.py lena-chen \
    --voice en-US-AvaMultilingualNeural --text-file kols/lena-chen/voice/corpus.txt
```

`corpus_builder.py` expands slot-filled templates into a few hundred unique utterances,
deliberately mixing **in-domain** lines in the KOL's register (review / haul / GRWM / CTA) with
**phonetically-spread** general sentences, so the voice learns the right prosody without
overfitting to one cadence. It deduplicates: with deterministic TTS, a repeated line
synthesizes to identical audio, which is a wasted clip that just overweights its phonemes.

Synthesis runs 8 requests in parallel (`--concurrency`); sequentially a 300-line corpus takes
about an hour, concurrently a few minutes.

> Backends: `edge` (default — no GPU, very natural, wide ZH/EN choice; check Microsoft's
> terms for your use case) or `piper` (fully local, MIT, flatter prosody — fine here since
> GPT-SoVITS re-learns the timbre anyway).

### Option B — crawl real audio you have rights to

```bash
python tools/voice_crawl/crawl.py <kol_id> --url "<podcast or video URL>"
python tools/voice_crawl/crawl.py <kol_id> --file ./audio_folder/ --lang en
```

Useful flags:

| flag | why |
|---|---|
| `--separate` | strip music/BGM with demucs first (needs torch + `pip install demucs`) |
| `--lang auto\|zh\|en` | force a language instead of per-file detection |
| `--whisper-model` | `large-v3` (default, best) → `medium`/`tiny` to trade accuracy for speed |
| `--device cuda\|cpu` | falls back to CPU automatically if cuDNN is missing |
| `--target-minutes 30` | stop once enough audio is accepted |
| `--min-snr`, `--min-conf` | tighten/loosen the QC gate |
| `--keep-existing` | append to the dataset instead of clearing it |

⚠️ **Multi-speaker sources.** Diarization is not wired in, so a two-host podcast yields a
dataset containing *both* voices and the fine-tune will blend them. Use single-speaker
audio, or pre-split by speaker, until diarization lands.

### QC gate

Every clip is measured and either accepted or rejected with a recorded reason:

| metric | default | rejects |
|---|---|---|
| duration | 3–10 s | fragments / run-ons |
| `rms_dbfs` | ≥ −38 | near-inaudible takes |
| `clip_ratio` | ≤ 0.5 % | digital clipping |
| `snr_db` | ≥ 12 | noisy rooms, heavy BGM |
| `silence_ratio` | ≤ 0.55 | clips that are mostly dead air |
| `asr_conf` | ≥ 0.55 | garbled speech → wrong transcript |

`dataset/manifest.json` records the numbers for **every** clip including rejects, so a low
yield is diagnosable (`rejected_by_reason`) instead of mysterious.

> `silence_ratio` is measured against the clip's own **speech** level (−30 dB), not its noise
> floor. A noise-relative threshold scores 1.00 on continuous full-level speech — it rejects
> perfect audio. Verified against synthetic controls before it was trusted.

### Output

```
kols/<id>/voice/
  raw/        downloaded / source audio (gitignored)
  work/       normalized 32k mono intermediates (gitignored)
  dataset/
    *.wav             accepted clips, 32 kHz mono PCM_16
    <id>.list         GPT-SoVITS manifest: wav|speaker|LANG|text
    manifest.json     full QC report
  ref.wav / ref.txt   inference prompt clip + exact transcript
```

Sanity-check before training: `wc -l` the `.list` and confirm accepted minutes ≥ 5
(20–30 min is comfortable).

---

## 2. Fine-tune GPT-SoVITS

> **Use a separate venv.** GPT-SoVITS pins `numpy<2.0` and `librosa==0.10.2`; the repo
> `.venv` runs numpy 2.x. Installing them together breaks the crawl tooling. They talk over
> HTTP, so they never need to share an environment — which is exactly what
> `tools/tts_train/tts_client.py` already assumes.

### One-time setup (this box: Windows, RTX 5070, no MSVC toolchain)

`GPT-SoVITS/install.ps1` needs conda (only for `ffmpeg cmake`) and builds two C extensions
that require the full Visual Studio toolchain. This repo takes a lighter path instead:

```powershell
# 1) venv + CUDA 12.8 torch (CU128 is REQUIRED for RTX 50-series / Blackwell sm_120)
py -3.10 -m venv GPT-SoVITS\.venv
GPT-SoVITS\.venv\Scripts\python.exe -m pip install torch torchaudio `
    --index-url https://download.pytorch.org/whl/cu128

# 2) deps, minus the two packages that cannot build without MSVC
GPT-SoVITS\.venv\Scripts\python.exe -m pip install -r GPT-SoVITS\requirements-win-zhen.txt

# 3) shim jieba_fast -> jieba (chinese2.py imports it unconditionally)
GPT-SoVITS\.venv\Scripts\python.exe tools\voice_crawl\install_jieba_fast_shim.py

# 4) pretrained models (~4.2 GB + 608 MB G2PW; resumable)
.\tools\voice_crawl\fetch_gptsovits_models.ps1 -Source HF
```

What was dropped and why it is safe:

| Dropped | Why | Impact |
|---|---|---|
| `pyopenjtalk` | Japanese-only C ext, needs cmake + MSVC | none — `cleaner.py` imports language modules lazily, so ZH/EN never touch it |
| `jieba_fast` | C-optimised `jieba`, needs MSVC — but imported *unconditionally* by `chinese2.py` | replaced by a shim re-exporting `jieba`; only word segmentation is slower |
| `--no-binary=opencc` | forces a source build needing MSVC | the opencc wheel works fine |

Verified working: ZH gets Traditional→Simplified normalization + toned pinyin, EN gets ARPAbet,
`word2ph` sums match phone counts. Only the `ja` path is unavailable.

### Three more local patches are required on Windows

`train_gptsovits.py` sets the env/config flags, but three edits inside GPT-SoVITS itself
are needed. All are marked `LOCAL PATCH` and all preserve upstream behaviour by default:

| File | Patch | Why |
|---|---|---|
| `GPT_SoVITS/s2_train.py` | skip the DDP wrapper on 1 GPU (`GSV_NO_DDP=0` restores it) | **This was the blocker.** DDP's reducer hooks into backward; with 1 process on the Windows `gloo` backend it segfaults (`0xC0000005`) on the first iteration. A `_SingleGPUWrap` keeps `.module` and the `module.` state_dict prefix, so checkpoints stay WebUI-compatible. |
| `GPT_SoVITS/s1_train.py` | `"auto"` strategy on 1 GPU **+ init a 1-process group** | Same crash. The group is still required because `AR/data/bucket_sampler.py` calls `dist.get_world_size()`/`get_rank()` unconditionally. |
| `GPT_SoVITS/AR/data/data_module.py` | only pass `persistent_workers`/`prefetch_factor` when `num_workers > 0` | Those kwargs are illegal at `num_workers=0`, which Windows requires (spawned loader workers re-init CUDA inside the training process and crash). |

### Train

```powershell
GPT-SoVITS\.venv\Scripts\python.exe tools\voice_crawl\train_gptsovits.py lena-chen
```

Runs all six steps headlessly (the WebUI hides them behind Gradio callbacks):
text→BERT → HuBERT → speaker-verification embeddings → semantic tokens → SoVITS → GPT.
Defaults to **v2Pro** (the repo's own default; best similarity for its size) and auto-picks
batch size from free VRAM. On success it writes the weight paths straight into
`kols/<id>/profile.json → ai_assets.voice`.

Each prepare step is checked for real output (`expect_outputs`) because the upstream
scripts wrap per-clip work in a bare `except:` and exit 0 with empty directories on a
systemic failure — so the exit code alone cannot be trusted.

Useful flags: `--steps prepare|sovits|gpt` to run one stage (handy for resuming after a
partial success), `--fp32`, `--batch-size`, `--save-every`.

> Keep epoch counts a **multiple of `--save-every`** (default 4). Weights are only written
> on those multiples, so `--gpt-epochs 15 --save-every 4` keeps epoch 12 and discards 3
> epochs of compute. The trainer now warns about this.

If a run trains fully but dies on the final save (`FileNotFoundError:
SoVITS_weights_.../<exp>_e<N>_s<S>.pth`), the work is recoverable — the checkpoint is in
`logs/<exp>/logs_s2_<ver>/G_*.pth`:

```powershell
GPT-SoVITS\.venv\Scripts\python.exe tools\voice_crawl\recover_sovits_weight.py <kol_id>
```

```powershell
# serve
cd GPT-SoVITS; .\.venv\Scripts\python.exe api_v2.py -a 127.0.0.1 -p 9880 -c GPT_SoVITS/configs/tts_infer.yaml
```

Loading a fine-tuned SoVITS weight logs `_IncompatibleKeys(missing_keys=['enc_q...'])` —
this is **expected**. `enc_q` is the posterior encoder used only in training; `savee()`
strips it (135 MB vs 951 MB). `unexpected_keys=[]` is the part that matters.

Verify it is the real voice and not the fallback:

```bash
python tools/tts_train/tts_client.py <kol_id> "大家好，今天分享一個好物。" zh out_zh.wav
python tools/tts_train/tts_client.py <kol_id> "Honestly, this is my favourite." en out_en.wav
```

`tts_client` falls back to edge-tts (cross-platform) when the API is unreachable, so it
**never hard-fails** — a bare `OK -> ...` means the real API served it; a
`[tts_client] GPT-SoVITS unavailable (...)` line means you got the fallback. Always read
that line before trusting the output.

Best objective check: ASR the result back and compare to the input text. Duration and level
alone will happily pass on garbled audio. Verified for `lena-chen` (v2Pro, 28.7 min corpus,
SoVITS e8 + GPT e12) — one timbre, both languages:

| | asked | Whisper heard |
|---|---|---|
| ZH | 大家好，今天分享一個好物，這罐精華我用了三週。 | 大家好,今天分享一個好物這罐精華我用了三周 |
| EN | Honestly, this is my favourite thing I have tried all month. | Honestly, this is my favorite thing I have tried all month. |

---

## Measured cost of adding a KOL

From the second KOL built (`sofia-vargas`), end to end:

| Stage | Time | Attended? |
|---|---|---|
| Corpus generation (320 utterances) | ~4 min | no |
| Bootstrap synthesis + QC (320 clips, 30.2 min of audio) | ~12 min | no |
| Data prep + SoVITS 8 epochs + GPT 16 epochs | **7.8 min** | no |
| Avatar build from a video | ~1 min | no |
| Choosing the timbre, reviewing output, wiring the profile | ~30 min | **yes** |

So roughly **25 min of compute and about half an hour of attention** per KOL — the limit is
review, not hardware. The first one took days because of the environment problems now
documented here.

Two gotchas the second KOL exposed, both fixed:

- **BERT features are produced only for Chinese rows.** An English-only dataset legitimately
  yields zero `.pt` files, so the step-1 check now derives its expectation from the actual ZH
  row count instead of demanding at least one.
- **Language support is a text-frontend limit, not a model or licence limit.** GPT-SoVITS ships
  g2p frontends for zh/en/ja/ko/yue only. A Spanish-native KOL therefore gets an English voice
  today; the options (and why English was chosen for now) are recorded in her
  `profile.json → ai_assets.voice.language_decision`.

## 3. Realtime lip-synced avatar (LiveTalking)

Working — see [`tools/livetalking/README.md`](../livetalking/README.md).

```powershell
.\tools\livetalking\run_livetalking.ps1 lena-chen     # needs api_v2 already serving
```

**Measured VRAM:** api_v2 + LiveTalking (wav2lip, batch 4) co-resident use **5,287 MiB of
12,227**, leaving 6,657 MiB. They fit together; no staging required. Leave `api_v2` running —
LiveTalking calls it per utterance, so it *is* the cloned voice.

Caveat: the avatar is still LiveTalking's stock demo face. Using the KOL's own face needs a
custom avatar built from a **video**, and the KOLs currently only have stills.

---

## Requirements

Core crawl path needs **no torch** — faster-whisper (CTranslate2) does both VAD and ASR:

```bash
pip install yt-dlp soundfile librosa onnxruntime faster-whisper edge-tts
```

Optional: `pip install demucs` (+ torch) for `--separate`.

ffmpeg is resolved via PATH with fallbacks to the winget/scoop/choco install roots, so a
shell started *before* `winget install Gyan.FFmpeg` still works. Override with `FFMPEG_BIN`.
