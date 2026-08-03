# studio — Voice Studio

Text-to-speech, voice cloning and character creation, at **http://127.0.0.1:8770/studio**
(served by the dashboard) or from the CLI.

Everything runs through the local GPT-SoVITS `api_v2` server. Nothing is sent to a third
party, and there is no per-character API cost.

## 1. Text to speech

Five characters — **3 English, 2 Taiwan Mandarin**:

| Character | Language | Voice |
|---|---|---|
| Sofia Vargas | English | **fine-tuned** (30.2 min corpus) |
| Lena Chen 陳語彤 | Taiwan Mandarin | **fine-tuned** (28.7 min corpus) |
| Chloe (EN, warm) | English | zero-shot |
| Ava (EN, bright) | English | zero-shot |
| Hsiao-Yu 小雨 | Taiwan Mandarin | zero-shot |

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

> Only clone a voice you have the right to use. A **fine-tuned** voice (20–30 min of audio,
> ~25 min of compute — see `tools/voice_crawl`) sounds markedly better than zero-shot, which
> is why the two flagship characters use it.

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
