# Talking KOL — web app (echo-mode MVP)

A local browser UI inspired by [livetalking.top](https://www.livetalking.top): pick a KOL,
type text, click **Nói** → the character "speaks" your text back as a short clip.

100% local, free. **Echo mode** = type -> speak (matches the repo's POC scope in
`research/local-ai-companion/05-poc-execution-plan.md`).

```
text -> TTS (macOS `say`, Meijia zh_TW) -> portrait + caption + Ken Burns (Pillow+ffmpeg) -> clip
```

## Run

```bash
# needs Pillow + ffmpeg; Ollama not required for echo mode
python3 tools/talking_web/server.py         # then open http://localhost:7860
python3 tools/talking_web/server.py --selftest   # generate one clip and exit
```

Reads each KOL's first seed photo from `kols/<id>/images/soul_v1_training/` and their
voice/language from `profile.json`. Generated clips go to `tools/talking_web/_out/` (gitignored).

## Roadmap — toward the real livetalking.top

The `generate()` function is written to be swapped for a lip-sync / streaming backend:

| Stage | Backend | Hardware |
|---|---|---|
| Now | TTS + portrait + Ken Burns (no mouth movement) | ✅ Mac, local |
| Lip-sync (offline) | **Wav2Lip** — mouth moves to the audio | ⚠️ CUDA (or slow on Mac) |
| Realtime + streaming | **LiveTalking** (type -> speak -> RTMP/virtual cam) | ❌ NVIDIA/CUDA required |
| Better voice | replace `say` with CosyVoice2 / GPT-SoVITS (per-KOL `voice_id`) | CUDA for fine-tune |

See `research/local-ai-companion/04, 05, 08` for the LiveTalking integration plan and evidence.
