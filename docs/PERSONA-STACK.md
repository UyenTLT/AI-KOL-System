# Persona stack — how a comment becomes a reply

Handover answer for "what framework, what prompt, what parameters". Written 2026-08-20 against
the code, not from memory. The exact assembled prompt for each register is in
`docs/persona-prompts.txt`, regenerate it with:

    python tools/livestream/dump_prompt.py --all > docs/persona-prompts.txt

Three of the questions assume a stack this project does not have. Those are answered as "no, and
here is what is there instead" rather than mapped onto the nearest equivalent, because the
difference changes what persona tuning can and cannot do.

---

## 1. Framework & architecture

**No framework.** No LangChain, no LlamaIndex, no Flowise. Custom Python calling an
OpenAI-compatible HTTP endpoint through the `openai` SDK, pointed at a **local Ollama** on
`http://127.0.0.1:11434/v1`. Everything runs on one machine; nothing leaves it.

| file | job |
|---|---|
| `tools/livetalking/persona_brain.py` | builds the persona prompt from `profile.json`, calls the model, enforces the hard rules (`check_reply`), retries once |
| `tools/livestream/stage.py` | picks the register (`classify`), assembles the prompt, streams the reply sentence by sentence, drives the voice |
| `tools/livestream/server.py` | comment queue, one worker, clip rendering and publishing |

### Is the flow 1-step or 2-step?

**1-step at inference.** Retrieval and generation happen in the same call. There is no
rewrite/stylize pass on the way out.

There *is* a 2-step, but it runs **offline**: `tools/llm_train/build_dataset.py` generates k
candidates per prompt, an LLM judge picks the best, and the winners become fine-tuning data
(`tools/llm_train/train_lora.py`). So the "stylize" step exists — it was moved out of the request
path and into the weights. That was deliberate: keeping it at inference would pay for it on every
comment, and the wait is already the main complaint.

---

## 2. RAG

**There is no RAG in the retrieval sense.** No embeddings, no vector store, no chunking, no
similarity search. Nothing is indexed.

What occupies that slot is `stage.life_threads()`, and it is worth understanding because it is
where "interesting" comes from:

- Source is a hand-written file, `kols/<kol_id>/life.json` — her ongoing threads, things that
  happened to her, opinions, the people in her life, what she did this week.
- Selection is **keyword overlap** between the incoming comment and each line, with randomness
  only to break ties. Not semantic. A question about Taiwan surfaces the Taiwan lines because
  they share words with the question.
- `LIFE_MIX` fixes the shape: 2 threads, 1 story, 1 opinion, 1 this_week, 1 person, 3 biography,
  2 knows. `LIFE_ON_TOPIC = {"biography", "knows"}` are carried **only** when the message reaches
  for them, because reference material nobody asked for is pure cost.

Why a file and not a vector store: the hard rules forbid her from improvising a biography, since
an improvised one contradicts itself by the next turn. That only works if there is a real one to
draw on, and it is small enough to hand-write. It costs ~2100 characters per request.

---

## 3. System prompt

**Two variants, and production uses the short one.** `build_system_prompt(kol_id, tuned)`:

- `tuned=True` — **1963 chars**. Name, languages, and 12 hard rules. This is what runs, because
  `RUN-TUNED.ps1` sets `KOL_LLM_TUNED=1`. The character sheet is dropped on purpose: with a
  fine-tuned adapter the personality is in the weights, and restating it measured *worse* (92%
  on a 129-char prompt against 83% for the base model on the full 3645-char one).
- `tuned=False` — the full character sheet, ~3645 chars, built from `profile.json`
  `identity` / `persona` / `content`. Used only when serving the untuned base model.

The rules stay in both cases. They were never the part the model struggled to imitate; they are
the part with consequences.

On top of that, per request:

| block | chars | varies? |
|---|---|---|
| persona + hard rules | 1963 | no |
| register block (`MODES[mode]["system"]`) | 2881 comment / 5113 banter / 2934 heart | per register |
| life block | ~2100 | **per message** |
| asker line | ~110 | per commenter |
| language directive | ~200 | per message |
| history | **0** | the live path sends none |

≈ **7000 characters per comment**. Full text in `docs/persona-prompts.txt`.

### History

The live path sends **no conversation history** (`server.answer_worker`). On a stream each
comment is a fresh question, usually from a different person, and feeding back the previous
exchange made her answer a conversation the commenter was never in. `history_for()` still exists
and is still correct for the 1:1 chat, which is one thread with one person.

---

## 4. Few-shot examples

**Yes, but only in one register, and they are stale.**

`HUMOUR` and `PLAYFUL_EXAMPLES` are defined in `tools/chat/server.py` and read by
`stage._humour_block()` — by AST-parsing that file rather than importing it, because there are two
files called `server.py` in this repo and importing by name silently returned the wrong one. That
exact failure is why generation once measured 0.0% playful.

- `MODES["banter"]` — **has** the examples (5113 chars).
- `MODES["comment"]` — the default register, **no examples** (2881 chars).
- `MODES["heart"]` — no examples, deliberately.

⚠️ **The examples are written for the previous character.** They reference an abuela, a neighbour
called Marco with drums, a cousin called Dani, and one pasta dish — the Colombian Sofia Vargas
canon, from before the 2026-08-14 recast. Anyone tuning the persona voice should read them first.

**The real carrier of the voice is the fine-tune, not the prompt.** 1270 training pairs / 109
validation. `datasets/sofia-hsu-chat-train.jsonl`.

---

## 5. Parameters

**Model:** `Qwen2.5-7B-Instruct` + QLoRA adapter (rank 16, 3 epochs, lr 1e-4, bf16 adapters over
nf4 base), merged and quantised to **q4_K_M**, registered with Ollama as `sofia-hsu-tuned`.
Not GPT-4o, not Claude, not Gemini. It is a 7B open-weight model on a single RTX 5070, and
model choice is not a knob here — the whole point of the local stack is that it runs on this box.

| call site | temperature | max_tokens |
|---|---|---|
| live, streamed (`stage.respond_streamed`) | **0.6** | **64** (`LIVE_MAX_TOKENS`) |
| live, fallback (`stage.respond` → `persona_brain.chat`) | 0.6, then **0.3** on retry | 64 |
| 1:1 chat (`tools/chat/server.py`) | 0.6 / 0.3 | caller-set cap |
| song (`stage.write_song`) | 0.85, then 0.5 on retry | 180 |
| offline candidate generation (`build_dataset.candidates`) | 0.7 + 0.15·i per candidate | 150 |

**`top_p`, `frequency_penalty`, `presence_penalty` are not set anywhere in this codebase.** They
fall through to Ollama's defaults (`top_p` 0.9, `top_k` 40, `repeat_penalty` 1.1). The Modelfile
sets only the chat template and two stop tokens — no sampling parameters. If you want to tune
sampling, that is a genuinely unexplored dimension here.

Two parameters that matter more than temperature on this stack:

- `LIVE_MAX_TOKENS = 64` is a cap, not a request. The comment register asks for two short
  sentences and the model writes four or five anyway. It also keeps replies under
  `speech_chunks`' 340-char threshold so the answer renders as **one clip** — every clip boundary
  is a seam you can hear.
- `PACE = 1.00` — ffmpeg `atempo` on the rendered audio, pitch-preserving.

---

## 6. The RAG context integration template

Verbatim from `stage.respond_streamed` (`stage.respond` is identical):

```python
sysmsg = MODES[mode]["system"]
life = life_threads(kol_id, message=message)
if life:
    sysmsg += "\n\n" + life
if asker:
    sysmsg += (f"\n\nThis comment is from {asker}. Talk to them, and use their name when "
               f"it fits naturally.")

msgs = [{"role": "system", "content": build_system_prompt(kol_id, tuned=tuned)},
        {"role": "system", "content": sysmsg},
        {"role": "system", "content": language_directive(message, trad)}]
msgs += list(history or [])          # empty on the live path
msgs.append({"role": "user", "content": message})
```

`life_threads` formats each block with its own one-line header (`_LIFE_INTRO`), e.g.
`Ongoing in your life right now:`, `Something that actually happened to you:`. There are no
citations, no source ids, no scores — the lines are presented as things she knows, because a
character who quotes a retrieved document is not a character.

---

## Before you tune the persona: four things that are currently broken or misleading

1. **`sofia-hsu-tuned` is not the model you think it is.** It shares a digest
   (`f5cadf631691`) with `sofia-vargas-tuned` — it is a re-tag of the older export, so the
   1270-row retrain is **not being served**. `tools/llm_train/export_gguf.py` is what promotes
   the current adapter.

2. **`profile.json` is half-renamed.** `identity.name` is "Sofia Hsu"; `handle`, `age`,
   `ethnicity`, `origin`, `current_location` and `languages` are still the Colombian character.
   Because the tuned prompt sends only *name and languages*, production is literally telling the
   model: `You are Sofia Hsu. Languages: Spanish (native), English (fluent), Portuguese`.
   `wants_traditional` and `speaks_cjk` are therefore both `False`, so she cannot answer in
   Chinese at all. See `kols/sofia-hsu/character.md` §十一 items 1–2.

3. **`life.json` is still the Colombian life** — Medellín, Miami, the abuela. Whatever the prompt
   says, the anecdotes come from here.

4. **Prompt-level humour tuning is the one approach with the most evidence against it.** Seven
   prompt variants were measured against the same detector and none moved it (0.0–1.2% against
   the 5–6% real people score). Rejection sampling then lifted story, opinion and deflection
   while leaving humour at 2.5% either way. A validated LLM judge does separate funny from
   neutral human speech (+0.65 mean, 23.8% vs 5.0% rated 4+) where regex does not — so if the
   goal is a funnier persona, the judge is the instrument and the training data is the lever.
   Rewriting the system prompt to ask for more personality has been tried and measured.
