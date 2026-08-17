# Tools — Local KOL Content Generation

Local-first, free tooling to turn a KOL's static profile + photos into content. See
`research/local-ai-companion/` for the full stack rationale.

| Tool | What it does |
|---|---|
| [`dashboard/`](dashboard/) | **Live pipeline tracker** — one page showing where every KOL stands, plus service + GPU state. Start here. |
| [`selftest/`](selftest/) | **Verification console** — runs every layer's checks live and shows the evidence. `--cli` exits non-zero on failure. |
| [`voice_eval/`](voice_eval/) | **Voice lab** — engines side by side against real human speech, with blind mode and octave-safe prosody metrics. For judging *how human* a voice sounds. |
| [`voice_crawl/`](voice_crawl/) | Voice data → GPT-SoVITS training set → headless fine-tune. Crawl real audio or synthesize a bootstrap timbre. |
| [`livetalking/`](livetalking/) | Realtime lip-synced avatar speaking in the KOL's cloned voice. |
| [`tts_train/`](tts_train/) | `tts_client.py` (the TTS HTTP client used by the apps) + RVC timbre conversion. |
| [`talking_web/`](talking_web/) | Simple type-to-speak web app. |
| `vlog_app.py` | Photo → vertical 9:16 vlog (Ken Burns + captions). |

Quick status check:

```bash
python tools/dashboard/server.py     # http://127.0.0.1:8770  — what state is it in
python tools/selftest/server.py      # http://127.0.0.1:8772  — does it still work
```

## `vlog_app.py` — Photo-vlog generator (MVP)

Turns a KOL's seed photos into a vertical **9:16 TikTok/Reels vlog**:

```
① LLM script (Ollama)  →  ② voiceover (macOS `say`)
→  ③ Ken Burns pan/zoom + burned-in caption (Pillow + ffmpeg)  →  ④ concat
→  kols/<id>/videos/vlog_mvp.mp4
```

100% local, no paid API.

### Requirements

- **ffmpeg** — `brew install ffmpeg`
- **Pillow** — `pip install pillow`
- **Ollama** running with a model — open Ollama.app, then `ollama pull qwen2.5:7b`
- **macOS `say`** — built in (uses the `Meijia` zh_TW voice for Mandarin KOLs)

### Usage

```bash
python3 tools/vlog_app.py <kol_id> "chủ đề / 主題"
# e.g.
python3 tools/vlog_app.py lin-wanqing "雨天的慢生活"
```

Reads photos from `kols/<id>/images/soul_v1_training/*.png` (up to 6, skips empty/black
files) and writes `kols/<id>/videos/vlog_mvp.mp4`. The caption language + voice follow the
KOL's `profile.json` (`identity.languages`).

### Known limits (roadmap)

| Now | Upgrade |
|---|---|
| Motion = Ken Burns (still-image zoom) | Real motion → cloud image-to-video burst |
| Voice = macOS `say` (robotic) | Local XTTS-v2 / F5-TTS for natural cloned voice |
| No background music | Mix a royalty-free track via ffmpeg |
| Face not identity-locked across shots | Train a character LoRA / IP-Adapter (see research/09) |

## Related local scripts (in dev)

Image generation (`RealVisXL` SDXL + MPS) and the comment read-&-reply LLM pipeline were
prototyped during development; ask to promote them into `tools/` as well.
