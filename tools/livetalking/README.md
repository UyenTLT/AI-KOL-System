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

## Run

```powershell
# 1) the voice (leave running)
cd GPT-SoVITS; .\.venv\Scripts\python.exe api_v2.py -a 127.0.0.1 -p 9880 -c GPT_SoVITS/configs/tts_infer.yaml

# 2) the avatar
.\tools\livetalking\run_livetalking.ps1 lena-chen
```

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

- **The avatar is not the KOL's face yet.** `wav2lip256_avatar1` is LiveTalking's stock demo
  avatar (it even carries a "LiveTalking" watermark). Lena's face needs a custom avatar, and
  avatar generation consumes a **video** — `POST /api/avatar/task` with `video_file`/`video_path`
  produces `full_imgs/ face_imgs/ coords.pkl` under `data/avatars/<avatar_id>/`, after which
  `-AvatarId <id>` just works. The KOLs currently only have stills, so a short idle-motion clip
  has to be generated first (image→video, `CUDA_SETUP.md` §E) before this is possible.
- **Mid-sentence interruption is unreliable** (upstream issue #510, ~3 s). Keep to echo-style
  turns; do not design around barge-in.
- **`funasr` is not installed**, so the local ASR endpoint (voice *input*) is disabled. Not
  needed for text→avatar; `pip install funasr modelscope` if you want speech input.
- Server needs TCP:8010 and UDP open for WebRTC.
