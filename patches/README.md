# patches — required edits to the third-party engines

`GPT-SoVITS/` and `LiveTalking/` are cloned into this repo and **gitignored** (multi-GB with
model weights). That means edits made inside them are not version-controlled — on a fresh
clone the system would silently break in ways that took a long time to diagnose the first
time. These patches capture those edits so they can be re-applied.

## Apply

```powershell
.\patches\apply.ps1              # applies everything, skips what is already applied
.\patches\apply.ps1 -Check       # report only, change nothing
```

Or by hand:

```powershell
cd GPT-SoVITS ; git apply ..\patches\gpt-sovits-windows-single-gpu.patch
cd ..\LiveTalking ; git apply ..\patches\livetalking-persona-and-bilingual.patch
copy patches\gpt-sovits-requirements-win-zhen.txt GPT-SoVITS\requirements-win-zhen.txt
```

## What each one does

### `gpt-sovits-windows-single-gpu.patch`

| File | Change | Why |
|---|---|---|
| `s2_train.py` | skip the DDP wrapper on 1 GPU (`GSV_NO_DDP=0` restores it) | **Without this, training does not run at all.** DDP's reducer hooks into the backward pass; with one process on Windows' `gloo` backend it segfaults (`0xC0000005`) on the first iteration. A `_SingleGPUWrap` keeps `.module` and the `module.` state_dict prefix so checkpoints stay WebUI-compatible. |
| `s2_train.py` | `GSV_NUM_WORKERS` env var for DataLoader workers | Windows spawns loader workers *inside* the already-spawned training process; each re-initialises CUDA and crashes. |
| `s1_train.py` | Lightning `"auto"` strategy on 1 GPU **+** an explicit 1-process group | Same DDP crash. The process group is still required because `AR/data/bucket_sampler.py` calls `dist.get_world_size()`/`get_rank()` unconditionally. |
| `AR/data/data_module.py` | only pass `persistent_workers`/`prefetch_factor` when `num_workers > 0` | Those kwargs are illegal at `num_workers=0`, which Windows requires. |

### `livetalking-persona-and-bilingual.patch`

| File | Change | Why |
|---|---|---|
| `tts/sovits.py` | `language="zh"` → `"auto"`, and `prompt_lang` split out | Upstream hardcoded Chinese, so English text was sent to GPT-SoVITS labelled as Chinese. `auto` detects language per segment — this is what makes a mixed sentence like "…一個好物 real talk" render correctly. |
| `llm.py` | local Ollama + persona prompt + safety guards instead of the hardcoded Alibaba DashScope cloud call | Upstream needs a paid API key and used a generic "you are a knowledge assistant" prompt. Replies now come from `tools/livetalking/persona_brain.py`, are rule-checked, and never leave the machine. `KOL_LLM_CLOUD=1` restores the original path. |

### `gpt-sovits-requirements-win-zhen.txt`

`requirements.txt` minus the packages that cannot build here (no MSVC toolchain):
`pyopenjtalk` (Japanese-only), `jieba_fast` (replaced by the shim in
`tools/voice_crawl/install_jieba_fast_shim.py`), and the `--no-binary=opencc` line. `numba` is
pinned `<0.62` because 0.66's DLL is blocked by Windows Smart App Control.

## Regenerating these

Both engines are git clones, so after further edits:

```powershell
cd GPT-SoVITS  ; git diff -- GPT_SoVITS/AR/data/data_module.py GPT_SoVITS/s1_train.py GPT_SoVITS/s2_train.py > ..\patches\gpt-sovits-windows-single-gpu.patch
cd ..\LiveTalking ; git diff -- llm.py tts/sovits.py > ..\patches\livetalking-persona-and-bilingual.patch
```

Every change is marked `LOCAL PATCH` in the source with the reasoning, and each is a no-op
under its documented escape hatch — nothing here silently changes upstream behaviour.
