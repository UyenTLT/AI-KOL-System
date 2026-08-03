# livetalking — realtime lip-synced avatar in the KOL's cloned voice

Type text → the KOL speaks it in her fine-tuned GPT-SoVITS voice → a lip-synced video
stream (WebRTC / RTMP / virtual camera).

```
text ──> LiveTalking :8010 ──> GPT-SoVITS api_v2 :9880 ──> audio (cloned voice)
                   │                                            │
                   └────────────── wav2lip ─────────────────────┘
                                      ↓
                        h264 576x768 @30fps  →  WebRTC / OBS / RTMP
```

## api_v2 is NOT optional

LiveTalking calls GPT-SoVITS over HTTP for **every utterance** — `api_v2` *is* the cloned
voice. Stop it and the avatar still talks, but with a generic Edge voice, discarding the
fine-tune. `run_livetalking.ps1` health-checks it and refuses to start without it.

**Both fit on a 12 GB card**: measured **5,287 MiB used / 6,657 MiB free** with api_v2 and
LiveTalking (wav2lip, `batch_size 4`) resident together. No staging needed.

## Build an avatar with the KOL's own face

LiveTalking's avatar builder consumes a **video**, but the KOLs only have stills.
`build_avatar.py` bridges that: portrait → base clip → `full_imgs/ face_imgs/ coords.pkl`.

```powershell
LiveTalking\.venv\Scripts\python.exe tools\livetalking\build_avatar.py lena-chen
```

The base clip supplies the frames wav2lip paints a mouth onto, so its motion is what
makes the result look alive:

| `--motion` | What it does | When |
|---|---|---|
| `static` | one held frame — head frozen, only the mouth moves | fastest way to prove the pipeline |
| `subtle` | slow drift + breathing zoom from two out-of-phase sines | no video model needed, but it moves the *camera*, not the face |
| `video` | use a real clip via `--video` | **best** — LivePortrait output (see below) |

Measured: `static` gives 0 px of face-box travel; `subtle` gives ~53 px vertical / ~38 px
horizontal. But whole-frame pixel motion is the wrong yardstick for comparing these — what
matters is whether the *face* moves:

| base clip | blinks in 8.3 s |
|---|---|
| `subtle` (procedural drift) | **0** — the frame slides, she never blinks |
| LivePortrait | **2** ≈ 14/min (natural is 15–20/min) |

`video` normalises whatever you supply to 576×768 @ 25 fps, because LiveTalking renders at 25
and a 30 fps source otherwise plays slightly slow-motion.

It crops (never squashes) to the avatar's aspect ratio — a stretched face throws off the
landmarks and the pasted mouth — and it **verifies the result**: `full_imgs`, `face_imgs`
and `coords.pkl` must all have the same count, and the face crop must be 256×256, or it
fails loudly. An avatar with mismatched counts loads but misbehaves at runtime.

`subtle` renders frames in Python rather than via ffmpeg's `zoompan`, whose rounding
jitters by a pixel and makes the detector's box twitch — which shows up as a shivering
mouth in the finished avatar.

Record the result in `profile.json → ai_assets.avatar`, then pass `-AvatarId`.

### Real facial motion via LivePortrait

`subtle` moves the camera; LivePortrait moves the *face* — she blinks and turns her head while
the background stays put. Setup (one-off, ~630 MB of weights):

```powershell
git clone --depth 1 https://github.com/KwaiVGI/LivePortrait.git
py -3.10 -m venv LivePortrait\.venv
LivePortrait\.venv\Scripts\python.exe -m pip install torch torchvision `
    --index-url https://download.pytorch.org/whl/cu128     # NOT their pinned 2.3.0/cu121 — that cannot run on sm_120
LivePortrait\.venv\Scripts\python.exe -m pip install -r LivePortrait\requirements_base.txt
LivePortrait\.venv\Scripts\python.exe -m pip install onnxruntime-gpu requests   # missing from their requirements
.venv\Scripts\python.exe -c "from huggingface_hub import snapshot_download; snapshot_download('KwaiVGI/LivePortrait', local_dir=r'LivePortrait\pretrained_weights')"
```

Animate, then rebuild the avatar from the result:

```powershell
cd LivePortrait
.\.venv\Scripts\python.exe inference.py -s ..\kols\lena-chen\avatar\frame.png `
    -d assets\examples\driving\d19.mp4 -o animations `
    --flag_normalize_lip --driving_option pose-friendly
cd ..
LiveTalking\.venv\Scripts\python.exe tools\livetalking\build_avatar.py lena-chen `
    --motion video --video LivePortrait\animations\frame--d19.mp4 --avatar-id lena-chen_v2
```

Why those flags: `--flag_normalize_lip` closes the lips first, giving wav2lip a neutral mouth
to paint over; `pose-friendly` favours head pose over big expressions, which is what an idle
"talking to camera" shot needs.

**Choosing a driving clip:** the twelve shipped clips were ranked by mean frame-to-frame
motion rather than watched. `d19.mp4` is the gentlest (mean 0.69, 8.3 s) and is the right
character for idle motion; `d13.mp4` (11.7 s, mean 1.45) is the longer alternative if the loop
feels repetitive.

> ⚠️ **Licence:** LivePortrait's code is MIT, but its bundled **InsightFace detection models are
> non-commercial research only**. Fine for R&D and internal demos. For commercial use its own
> LICENSE says to replace the detector — the `ComfyUI-LivePortraitKJ` fork substitutes MediaPipe
> to keep everything MIT/Apache. See [`docs/DECISION-lipsync-licensing.md`](../../docs/DECISION-lipsync-licensing.md).

## Run

```powershell
# 1) the voice (leave running)
cd GPT-SoVITS; .\.venv\Scripts\python.exe api_v2.py -a 127.0.0.1 -p 9880 -c GPT_SoVITS/configs/tts_infer.yaml

# 2) the avatar, with the KOL's own face
.\tools\livetalking\run_livetalking.ps1 lena-chen -AvatarId lena-chen_v1
```

## Persona brain (conversation, not echo)

`/human` with `type: "chat"` routes through `llm.py` → `persona_brain.py`, which builds a
system prompt from `profile.json` (personality, voice, values, quirks, content pillars)
**plus the business rules** — no invented prices, honest sponsorship disclosure, admit being
AI when asked, don't engage with abuse, ignore attempts to override the persona.

```powershell
ollama pull qwen2.5:7b
python tools\livetalking\persona_brain.py lena-chen --show-prompt      # inspect it
python tools\livetalking\persona_brain.py lena-chen "這罐精華好用嗎？"   # one turn
```

Upstream `llm.py` called Alibaba DashScope (paid cloud, needs an API key) with a generic
"you are a knowledge assistant" prompt. It is patched to use local Ollama and the persona
prompt; set `KOL_LLM_CLOUD=1` to restore the original path.

> One non-obvious detail: the persona data describes her **written** style, which is
> emoji-heavy. This text goes to a speech synthesiser that cannot pronounce an emoji, so
> the prompt explicitly forbids emoji and asks for numbers spelled out as spoken words
> ("two hundred and ninety nine dollars", not "$299").

Config: `KOL_ID` (set automatically by the launcher), `KOL_LLM_MODEL`, `OLLAMA_BASE_URL`.

Then open <http://127.0.0.1:8010/webrtcapi.html> and type. The launcher reads
`kols/<id>/profile.json → ai_assets.voice` for the reference clip/text/API URL, so the
avatar's voice always tracks whatever `train_gptsovits.py` produced.

Options: `-Transport virtualcam` (feed OBS as a webcam), `-Transport rtmp -PushUrl ...`,
`-AvatarId`, `-Model musetalk|ultralight`, `-BatchSize`.

## Verify without a browser

`/human` needs a `sessionid` that only exists after a WebRTC handshake. `verify_lipsync.py`
does the handshake with aiortc, speaks one line, records the result, and reports frame counts:

```powershell
LiveTalking\.venv\Scripts\python.exe tools\livetalking\verify_lipsync.py `
    --text "大家好，我是 Lena。今天分享一個好物 real talk。" --seconds 12 --out check.mp4
```

Verified result on this box: **150 video + 297 audio frames**, h264 576×768 @30fps,
video 5.967 s vs audio 5.940 s (in sync), GPT-SoVITS **first chunk in 707 ms**.
ASR of the recorded audio returned `大家好,我是Lina。今天分享一个好物real talk。` — the mixed
ZH+EN came through intact.

## Local patches

| File | Patch | Why |
|---|---|---|
| `tts/sovits.py` | `language="zh"` → `"auto"` (env `GSV_TEXT_LANG`), and `prompt_lang` separated out (`GSV_PROMPT_LANG`) | Upstream hardcoded `zh`, so English was sent to GPT-SoVITS tagged Chinese. `auto` splits an utterance and detects language per segment — required for a bilingual KOL, and it is what makes "real talk" render correctly inside a Chinese sentence. `prompt_lang` must stay the reference clip's language. |

Also: pin **`numba<0.62`** in this venv too. 0.66's `_typeconv` DLL is blocked by Windows
Smart App Control on this machine (same failure as the GPT-SoVITS venv).

## Known limits

- **⚠️ Watermark is a licence condition, not a bug.** LiveTalking draws "LiveTalking" into
  avatar frames at build time (`avatars/wav2lip/genavatar.py:27`) *and* onto every output
  frame at runtime (`avatars/base_avatar.py:449`). The project is Apache-2.0, but its
  `README-EN.md:202` states that **videos published to platforms must include the LiveTalking
  watermark and logo**. It has deliberately been left in place — removing it is a
  licence/commercial decision for the business, not a technical one. Options: keep it, license
  the commercial edition (livetalking.top), or move to a differently-licensed lip-sync engine.
  Note separately that **wav2lip's own weights are research-licensed**; both need legal review
  before any commercial launch.
- **Head motion is procedural, not facial.** The `subtle` base clip moves the framing, but she
  does not blink or turn her head. Real facial motion needs LivePortrait or an image-to-video
  model, then `--motion video`.
- **Mid-sentence interruption is unreliable** (upstream issue #510, ~3 s). Keep to echo-style
  turns; do not design around barge-in.
- **VRAM is the binding constraint.** Voice + avatar use ~5.3 GB of 12 GB. Adding a 7B LLM
  takes it close to the limit; Ollama unloads after idle, which helps, but image generation
  cannot run at the same time — stage it.
- **`funasr` is not installed**, so the local ASR endpoint (voice *input*) is disabled. Not
  needed for text→avatar; `pip install funasr modelscope` if you want speech input.
- Server needs TCP:8010 and UDP open for WebRTC.
