# voice_eval — measuring whether a voice sounds human

The complaint that started this was "it still sounds like a robot". That is not directly
measurable, so this directory holds the proxies that are, chosen because they are the ones
that actually differed when the current voice was compared against real human speech.

## What was measured, and what it showed

48 seconds of real human speech (`kols/sofia-vargas/voice/raw/`) cut into utterance-sized
chunks, against a 45-clip sample of the synthetic training corpus:

| | Synthetic corpus | Real human | Gap |
|---|---|---|---|
| Pauses per 10 s | 2.09 | 6.79 | **3.2x** |
| Clip-to-clip pitch spread | 0.47 st | 1.71 st | **3.6x** |
| Pitch range within a clip | 9.08 st | 14.01 st | 1.5x |
| Median pitch | 199.9 Hz | 200.3 Hz | matches |

**Timbre is not the problem.** The median pitch already matches within half a hertz. What is
missing is breathing and variation — the voice speaks in an unbroken, uniform stream.

The cause is upstream of the model. `bootstrap_timbre.py` passes one `rate` and one `pitch`
to edge-tts for every clip in the corpus, so all 320 clips carry the same delivery and differ
only in wording. 0.47 semitones of clip-to-clip spread is one reading repeated 320 times.
GPT-SoVITS re-learns the timbre, as its docstring says — but it also learns the prosody
distribution it is shown, and there is almost none to learn.

## The pitfall this code exists to avoid

The first version of this measurement ran `pyin` with a 70 Hz floor. Both the human clip and
one synthesised output have strong low-frequency energy (vocal fry, plus room rumble in a
phone recording), so the tracker locked an octave low on many frames. Every pitch statistic
derived from it was wrong, and a fabricated "12.6x delivery variety" figure made it into a
written conclusion before the error was caught.

`prosody.py` therefore high-passes at 80 Hz, sets the `pyin` floor to 110 Hz so a female
voice cannot be tracked an octave down, and discards frames pinned to the floor as
unreliable rather than averaging them in.

This is the same failure mode the project has hit repeatedly: a hand-rolled proxy metric
that is easy to compute, plausible to read, and measuring the wrong thing. Whole-frame pixel
difference for facial motion, a blink detector sampling the forehead, MFCC cosine for
speaker identity — and now an octave-confused pitch tracker.

## Why swapping the reference clip does not fix it

GPT-SoVITS is prompt-based: `ref.wav` sets the delivery for every utterance. Substituting the
real human clip while keeping Sofia's fine-tuned weights made things **worse**, not better:

| | Duration | Median pitch | Pitch range | Pauses/10 s |
|---|---|---|---|---|
| Current setup | 8.0 s | 202.9 Hz | 10.43 st | 3.75 |
| Human reference | 11.5 s | 152.0 Hz | 8.20 st | 5.24 |
| Human original | 6.5 s | 182.9 Hz | 14.10 st | 4.62 |

The register drops 51 Hz, expressiveness *falls*, and the same sentence stretches 44%. Weights
fine-tuned on one speaker fight a reference from another. The cheap lever is not available.

## The lab — listening, not just measuring

Every number above is a proxy. "Sounds like a person" is a judgement your ear makes, so
`lab.py` puts the candidates side by side with the real human clip pinned at the top as the
thing to beat.

```bash
# engine servers first (each in its own venv — they pin incompatible stacks)
GPT-SoVITS/.venv/Scripts/python.exe GPT-SoVITS/api_v2.py -a 127.0.0.1 -p 9880 -c GPT_SoVITS/configs/tts_infer.yaml
CosyVoice/.venv/Scripts/python.exe tools/voice_eval/cosy_server.py          # :9881
# then the lab
.venv/Scripts/python.exe tools/voice_eval/lab.py                            # :8773
```

Type a line, render it through every engine, listen, *then* press Measure. That order matters:
numbers seen first tell your ear what to hear.

**Blind mode** (`?blind=1`) shuffles the rows and hides the engine names until you reveal them.
Knowing which row is "the promising new engine" is worth a surprising amount of imagined
improvement, and this evaluation has already been wrong once from exactly that kind of bias.

Rows are the five fine-tuned GPT-SoVITS voices in use today, plus three CosyVoice 2 conditions
that separate the engine from the reference clip: zero-shot off the synthetic reference,
zero-shot off the human reference, and instruction-controlled.

⚠️ **Pause rate needs a long enough clip.** On a two-second render it reads 0.0 because there is
no room for a pause, not because the delivery is flat. Keep the test line at least a sentence or
two — the default one is sized for this.

## Setting up CosyVoice 2 on this box

Four things cost time here. All four are captured in
`patches/cosyvoice-requirements-win-cu128.txt` or below, so nobody pays for them twice.

**1 · The torch pin does not run on this GPU.** Upstream pins `torch==2.3.1` on a cu121 index.
A 50-series card is `sm_120`; cu121 wheels carry no kernels for it. Same pin, same fix, third
time in this repo. Install torch from the cu128 index *first*, then the requirements — several
packages declare a torch dependency and will happily pull a CPU build over the top.

**2 · `openai-whisper` breaks the whole install.** Its `setup.py` imports `pkg_resources`,
removed in setuptools 81+, so its isolated build fails and pip aborts the entire resolve —
nothing installs, not just whisper. It cannot be dropped: `cosyvoice/cli/frontend.py` imports
`whisper` on the inference path. Install it out of isolation first:

```powershell
.venv\Scripts\python.exe -m pip install "setuptools<81" wheel
.venv\Scripts\python.exe -m pip install --no-build-isolation openai-whisper==20231117
```

**3 · `spk2info.pt` does not exist in this repo, and a naive download creates a poisoned one.**
Fetching it returns an HTTP error body — the literal bytes `Entry not found` — which a
downloader without a size or hash check will happily save as a 15-byte `.pt`. The file is
*optional* (`frontend.py` loads it only `if os.path.exists`), so absent is fine and only used
for the `spk_id` path this project does not take. But a present-and-corrupt file makes
`torch.load` throw at startup. **Delete it rather than keep it.** The general lesson: checking
that a file exists is easy and wrong; checking that its contents are right is the actual test.

**4 · onnxruntime is CPU-only on Windows.** Upstream marks `onnxruntime-gpu` as linux-only, so
the speech tokenizer and campplus speaker encoder run on CPU here and the reported RTF reflects
that. If CosyVoice is adopted, this is the first optimisation to look at — not a blocker, but
do not benchmark it against a Linux number and call it slow.

On first run it also downloads ~30 MB of `wetext` text-normalisation FSTs from ModelScope at a
few hundred kB/s. One-off; cached afterwards under `~/.cache/modelscope`.

## Driving the avatar with CosyVoice

LiveTalking ships its own `tts/cosyvoice` plugin, so the avatar needs **no patch** to speak in
Sofia's new voice — `run_livetalking.ps1` reads her profile, sees `engine: cosyvoice2`, and
passes `--tts cosyvoice --TTS_SERVER http://127.0.0.1:9881`.

One gap had to be closed. That plugin only knows `inference_zero_shot`: it posts a prompt wav
and a transcript, with **no field for a delivery instruction**. Zero-shot is the condition that
drifted 39 Hz off her register, so using it would have given the avatar a different voice from
the studio. Rather than patch a gitignored engine, `cosy_server` resolves the character *from
the reference clip it was handed* and applies whatever mode that profile declares.

Two details of that endpoint must match exactly, and both fail quietly:

- The plugin reads the body with `np.frombuffer(chunk, dtype=np.int16)`, so it must receive
  **raw PCM with no WAV header**. A 44-byte header arrives as a burst of noise at the start.
- It resamples from **24 kHz**, which is CosyVoice 2's native rate.

```powershell
CosyVoice\.venv\Scripts\python.exe tools\voice_eval\cosy_server.py     # :9881
.\tools\livetalking\run_livetalking.ps1 sofia-vargas -AvatarId sofia-vargas_v1
```

The launcher prints which plugin it chose. If it says `gpt-sovits` for a character whose
profile names another engine, it fell back — check that `:9881` is up.

## Files

- `prosody.py` — octave-safe prosody measurement; import `feats()` and `load_any()` from it
  rather than re-deriving the thresholds. Also runs standalone on a list of wavs.
- `lab.py` — the side-by-side listening page described above.
- `cosy_server.py` — CosyVoice 2 behind a small HTTP API on :9881, so it can be compared live.
  It runs **in the CosyVoice venv**; nothing in `tools/` can import CosyVoice directly, and
  loading the model takes tens of seconds, so a per-utterance subprocess would be unusable.
  Same shape as GPT-SoVITS on :9880 — load once, serve many.
- `bench_cosyvoice.py` — the same three conditions as a one-shot batch, for when you want files
  on disk rather than a page.

```bash
# generate
CosyVoice/.venv/Scripts/python.exe tools/voice_eval/bench_cosyvoice.py --out <dir>
# then measure with the repo venv, which has faster-whisper
.venv/Scripts/python.exe tools/voice_eval/prosody.py <dir>/*.wav
```

Two interpreters because the engines pin incompatible stacks; see
`patches/cosyvoice-requirements-win-cu128.txt`.

## Reading the numbers honestly

The human side is 7 chunks from a single 50-second recording by one speaker. The direction is
clear and consistent across three independent metrics, but this is a thin sample, and none of
it substitutes for listening. Treat these as a screen that says *where* to listen, not as a
verdict.
