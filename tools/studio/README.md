# studio — Voice Studio

Text-to-speech, voice cloning and character creation, at **http://127.0.0.1:8770/studio**
(served by the dashboard) or from the CLI.

Everything runs through the local GPT-SoVITS `api_v2` server. Nothing is sent to a third
party, and there is no per-character API cost.

## 1. Text to speech

Five characters — **3 English, 2 Taiwan Mandarin** — on **two engines** since 2026-08-04:

| Character | Language | Engine | Voice source |
|---|---|---|---|
| **Sofia Vargas** | English | **CosyVoice 2, instruct** | zero-shot from the owner's own recording |
| Lena Chen 陳語彤 | Taiwan Mandarin | GPT-SoVITS, fine-tuned | 28.7 min · en-US-AvaMultilingual |
| Chloe (EN, warm) | English | GPT-SoVITS, fine-tuned | 28.0 min · en-US-EmmaMultilingual |
| Ava (EN, bright) | English | GPT-SoVITS, fine-tuned | 31.2 min · en-US-Aria |
| Hsiao-Yu 小雨 | Taiwan Mandarin | GPT-SoVITS, fine-tuned | 35.9 min · zh-TW-HsiaoYu |

**Sofia moved off the fine-tuned voice on 2026-08-04**, chosen by ear from a side-by-side and
confirmed by measurement. The fine-tuned voice was flat because the corpus was: all 320 clips
came from one edge-tts voice at one fixed rate and pitch, so they varied by wording and
nothing else — 0.47 semitones of delivery variation across the whole set. A model cannot
produce range it was never shown.

Measured across nine sentence types (short, question, exclamation, long, numbers, brand name,
hesitant, list, emotional): mean pitch **198.0 Hz**, mean pitch range **14.48 st**, mean ASR
round-trip **98%**. The real human clip sits at 14.10 st; the old fine-tuned voice at 10.43.
Her established register was 202.9 Hz, so the identity holds.

Requires `tools/voice_eval/cosy_server.py` on `:9881`. If it is down, `voice_studio` warns and
falls back to her old GPT-SoVITS voice, which is kept under `voice.gpt_sovits_previous` — read
it with `gsv_block()`, never the top-level voice block, or `is_finetuned()` reports False and
synthesis quietly drops to the *base* checkpoint. Audio still comes out; it is just not her.

Verified after fine-tuning — all five are distinct speakers, and all five transcribe back
accurately (ERes2NetV2 speaker verification, against a same-speaker baseline of 0.919):

| | similarity |
|---|---|
| same character, different line (baseline) | 0.919 |
| cross-character mean | 0.691 |
| **closest pair** — lena-chen vs preset-zhtw | **0.852** |

⚠️ **The two Taiwan Mandarin voices are the closest pair** (0.852 against a 0.919 baseline —
distinguishable, but much closer than any other pair). Both are young female zh-TW timbres, so
this is expected rather than a bug. If a script needs two *clearly* different Mandarin voices
in the same video, rebuild one from a more contrasting timbre:

```powershell
.venv\Scripts\python.exe tools\voice_crawl\build_voice.py preset-zhtw-alt `
    --edge-voice zh-TW-YunJheNeural --lang zh      # male, maximal contrast
```

Controls: **speed** 0.6–1.5× (`speed_factor`), **volume** −12…+9 dB, **language**
(auto / English / Taiwan Mandarin), and a **script** box.

*Auto* language is worth using: GPT-SoVITS detects language per segment, which is what makes
a mixed sentence like 「這個好物 real talk」 pronounce correctly.

```bash
python tools/studio/voice_studio.py list
python tools/studio/voice_studio.py say lena-chen "大家好" --speed 1.0 --volume-db 0 -o out.wav
```

### Scenario → script

Describe a situation and the character writes the script in her own voice, then speaks it.
For the two fine-tuned KOLs the prompt is built from their real `profile.json` persona, so it
sounds like them rather than like generic ad copy — and it inherits the same rules (no
invented prices, no emoji, numbers spelled out for speech).

```bash
python tools/studio/voice_studio.py script sofia-vargas "unboxing a new sunscreen" --seconds 18 --say
```

## 2. Voice clone

Upload 5–15 s of clean single-speaker audio → speak any text in that voice. **Zero-shot, no
training.** The reference transcript is filled in automatically by ASR, because GPT-SoVITS
needs it to match the audio and hand-typing it is the most common cause of a bad clone.

```bash
python tools/studio/voice_studio.py clone ref.wav "Hello there" -o out.wav
```

> Only clone a voice you have the right to use. A **fine-tuned** voice sounds markedly better
> than zero-shot, which is why every studio character is fine-tuned.

### Upgrading a voice from zero-shot to fine-tuned

One command does corpus → bootstrap → fine-tune, invoking each stage with the correct
interpreter (the corpus/bootstrap stages need the repo venv for edge-tts; training needs the
GPT-SoVITS venv for `numpy<2` — mixing them up is the easiest way to waste half an hour):

```powershell
.venv\Scripts\python.exe tools\voice_crawl\build_voice.py preset-en-warm `
    --edge-voice en-US-EmmaMultilingualNeural --lang en --minutes 30
```

It creates a minimal `profile.json` if the id is new, so a plain voice preset does not need a
whole KOL persona invented for it. Presets are deliberately **not** added to
`kols/index.json`, so they work with every tool while staying out of the KOL roster.

The studio then **detects** the new weights on disk — `is_finetuned()` checks the profile and
the files, so a character upgrades from zero-shot to fine-tuned with no edit here and no risk
of a hardcoded label drifting out of step with reality.

## 3. Character

Describe a KOL in free text → a character sheet in the same shape as the existing profiles
(persona, voice_tone, quirks, content pillars, a suggested Edge voice matching the language,
and an image prompt). Save it as `kols/<id>/profile.json` and it flows straight into the
existing voice and avatar pipeline.

```bash
python tools/studio/voice_studio.py character "A 26-year-old Taiwanese fitness KOL..." --save-as mia-lin
```

Generated characters land as `status: draft` with `comment_policy_mode: suggest` — review
before use.

## Notes from building this

**"Taiwanese" means Taiwan Mandarin (國語, zh-TW) here, not Hokkien (台語).** GPT-SoVITS ships
g2p frontends for zh/en/ja/ko/yue only; there is no Hokkien frontend and no Hokkien Edge
voice, so Hokkien would need a separate model and dataset.

**`api_v2` is stateful about weights.** Whatever was last loaded stays active, so a zero-shot
character must switch back to the base checkpoints or it inherits the previously synthesised
KOL's voice. `set_weights()` handles this and skips redundant loads.

**Verifying "different voices" needs the right metric.** Pitch said the fine-tuned and
zero-shot zh voices were 5 Hz apart ("too similar"); MFCC cosine saturated above 0.997 and
separated same-from-different by 0.001. Both were useless. GPT-SoVITS's own ERes2NetV2
speaker-verification model — already on disk for v2Pro — gave a clear answer against a
same-speaker baseline:

| | similarity |
|---|---|
| same character, different text (baseline) | 0.944 |
| different characters | 0.780 |
| **separation** | **+0.165** |

Speed control verified as inversely proportional: 0.8× → 4.76 s, 1.0× → 3.74 s, 1.3× → 2.80 s
on the same sentence.
