# Decision memo — dynamic singing synthesis (Option C)

**Question:** can we build live singing for Sofia Hsu — LLM extracts a song request, a pitch
service supplies F0, an SVC checkpoint sings it, a mixer lays it over the backing track?

**Assessment: the GPU is the least of the problems.** VRAM is tight and solvable. The two things
that block this build are **the training data does not exist** and **the specified design
reproduces copyrighted songs at scale**, which this codebase currently prevents structurally and
on purpose.

A narrower PoC — same architecture, original material — is buildable and worth doing.

Not legal advice. This memo exists so legal is asked a narrow question rather than an open one,
the same way `DECISION-lipsync-licensing.md` was written.

---

## 1. What already exists, and should not be rebuilt

There is already a singing path. `stage.song_for()` answers a request one of two ways:

| outcome | what it is |
|---|---|
| `library` | a real sung recording **already converted into her voice** by RVC, remixed over the untouched backing |
| `recite` | original lines she speaks in a sustained register — she does not sing |

`songs.json` carries per-song `mood` and `keywords` for matching, the lyrics, a `pitch_shift`,
`stems: mix` (separate the vocal, convert only that, remix), and — importantly — a mandatory
`rights` field of `internal_only` or `commercial`, with this note already written in the file:

> "after conversion the two are indistinguishable files, so the moment of import is the only
> time the answer is known"

Three songs are live: *Taking My Sweet Time*, *Set It Down*, *Nothing Solved Tonight*. Original
titles, original lyrics, 8.65 minutes rendered.

**This static path delivers most of the product value of "Sofia sings" at none of the legal
risk.** The dynamic build should extend it, not replace it.

---

## 2. The data blocker — this is the one that stops the build

The spec asks for 30–45 minutes of clean Sofia singing to fine-tune `sofia-singing.pth`.

Total Sofia audio in the repository, measured:

| location | files | minutes | what it actually is |
|---|---|---|---|
| `songs/raw` | 4 | 12.07 | **source vocals — somebody else's performances**, the input to RVC |
| `songs/sofia` | 3 | 8.65 | **RVC output**, not her singing |
| `voice/candidates` | 11 | 1.59 | licensed synthetic voices, a rebrand shortlist |
| `voice/*`, `voice/raw`, `rvc_corpus_human` | 6 | 2.98 | **speech**, and the human-voice reference is ~50 s |
| **total** | **26** | **25.29** | |

**Genuine, rights-clean, Sofia singing: approximately zero minutes.**

The shortfall is not "19.7 minutes". Every category above fails for a different reason:

- `songs/raw` is other people's singing. Training on it produces their performance, not hers,
  and imports their rights.
- `songs/sofia` is RVC output. Fine-tuning an SVC model on the output of another voice model is
  a copy of a copy: it accumulates the converter's artefacts and teaches the new model to
  reproduce them. It also cannot add pitch information the source did not have.
- The speech corpus cannot teach singing. This project has already measured that the speech
  engine has no pitch control at all — asked to sing, CosyVoice 2 *narrows* its pitch range from
  17.50 semitones to 10.06. Singing moves in wide deliberate intervals; this moves in fewer.

**And the consent policy constrains how the gap can be closed.** The standing rule is synthetic
bootstrap by default, with Sofia the single exception because her source is the project owner's
own voice. So 30–45 minutes of clean singing means **the owner records 30–45 minutes of singing**,
dry, no backing track, pitch-stable. That is a real session — realistically several — and it is
the critical path for the entire feature. Nothing else can start it.

---

## 3. The rights blocker — and why it is not a footnote

The spec's JSON is:

```json
{ "song_title": "<Tên bài hát>", "lyrics_segment": "<Đoạn lời cần hát 10-15s>" }
```

plus §4, mixing the vocal with "Instrumental Track (Beat nhạc nền tương ứng)".

Read together that is: **reproduce a named song's lyrics, in a synthetic celebrity-adjacent
voice, over that song's instrumental, broadcast live, on demand, at scale.** Each of the three —
the composition, the recording, and the voice — is a separate rights holder.

This codebase currently prevents exactly that, deliberately. From `stage.py`:

> "Lyrics are always original. A request naming a real song is answered with her own short piece
> on the same feeling, never with that song's words. **This is structural rather than a policy
> sentence in a prompt: there is no path in this module that asks the model to reproduce existing
> lyrics**, so the failure mode of quoting a copyrighted song at scale does not have a route to
> happen."

The directive is a request to build that route. That should be an explicit, documented decision
by whoever owns the legal exposure — not a side effect of a feature ticket. It is also the third
component in this layer to hit a licence wall, after the wav2lip weights and the LiveTalking
watermark, which is the systemic pattern that memo already flagged: **budget one licence question
per component, and ask it before adopting.**

Add to that the engine licences, which have not been checked yet and must be before either is
installed: **so-vits-svc** and **Diff-SVC** both carry usage terms aimed squarely at
unauthorised voice cloning, and both need reading against commercial use.

---

## 4. GPU and VRAM — tight, and the smallest problem here

Hardware: **RTX 5070, 12227 MiB**. Current steady state with the stack up:

```
11697 / 12227 MiB used     Ollama sofia-hsu-tuned  4.7 GB, resident, 100% GPU
                           CosyVoice 2             ~4 GB
                           RVC                     ~4 GB
```

**There is no headroom for a fourth model.** An SVC checkpoint at inference wants roughly 2–4 GB;
training wants more than the card has free while anything else is up.

This is workable but not free:

- **Training** the checkpoint means taking the voice stack and Ollama down, exactly as the LoRA
  retrain did — a ~25 minute outage per run, and SVC training runs are longer than that.
- **Serving** means either unloading the LLM on demand (Ollama already expires it after ~4
  minutes idle; a song request could force it) or moving Ollama to CPU, which costs think time.
- There is an unresolved instability already on record: measured this week, render time spikes
  from RTF 0.9 to **RTF 4–7** immediately after the LLM finishes decoding, and the RVC call has
  been observed timing out at its 30 s limit and silently skipping the timbre pass. Adding a
  fourth GPU consumer to a card that already does this will make it worse, and that instability
  should be understood before anything else is added.

**On the latency target.** `< 2.5 s for a 10 s segment` is **RTF 0.25**. Measured on this box
today: CosyVoice RTF 0.83–1.05, RVC 0.8–1.1 s per clip. Diff-SVC is a diffusion model and is
slower than either. RTF 0.25 is not a realistic target on this hardware with the current stack
resident; so-vits-svc (non-diffusion) is the more plausible engine if this proceeds, and even
then the number to plan around is closer to RTF 0.8–1.0.

---

## 5. Recommended PoC — same architecture, original material

Everything in the directive works if the *material* changes. Concretely:

**Keep as specified:**
- **§1 intent extraction.** Cheap and useful. One caveat: the persona prompt forbids lists and
  markdown and the output guards run on every reply, so the JSON call must be a **separate
  request outside the persona path**, not a mode of the existing one.
- **§2 pitch service.** `librosa` for F0 extraction and `mido` for MIDI both work identically on
  material the project owns.
- **§4 mixer.** Gains of −2 dB vocal / −12 dB bed are a sensible starting point. Note the
  existing chain already does loudness and a 3.2 kHz softening pass, so the mixer belongs
  *after* those, and the room-tone bed is laid last of all.

**Change:**
- `song_title` / `lyrics_segment` → **`mood` + original lyrics**, generated by `write_song()`
  which already exists and already produces original lines.
- F0 from an **owned melody bank** — commission or write 10–20 short melodies, store the MIDI —
  rather than from a copyrighted recording.
- Instrumentals from **owned or licensed beds**, carrying the same `rights` field `songs.json`
  already mandates.

**Sequence, with the blocking item first:**

| # | step | needs | blocked by |
|---|---|---|---|
| 1 | Owner records 30–45 min of dry singing | a session, a decent mic | **nothing — start here** |
| 2 | Licence read on so-vits-svc / Diff-SVC | an afternoon | nothing |
| 3 | Original melody bank, 10–20 MIDIs | writing or commissioning | nothing |
| 4 | Train `sofia-singing.pth` | GPU, full stack down | 1, 2 |
| 5 | F0 service + SVC render | — | 3, 4 |
| 6 | Mixer + websocket out | — | 5, and the RTF instability in §4 |

Steps 1–3 are independent of each other and of the GPU. **None of them is blocked on anything
this memo raises, and step 1 is on the critical path for everything else.**

---

## 6. The one-line answer

The GPU can host a PoC with scheduling compromises and a latency target around RTF 1.0 rather
than 0.25. It cannot host the *specified* build, because that build needs a checkpoint that
needs 30–45 minutes of singing that does not exist and can only come from the owner's own voice —
and because singing named songs over their backing tracks is a legal decision, not a technical
one, and this repo currently makes that failure impossible by design.
