#!/usr/bin/env python3
"""Voice Studio engine — TTS, voice cloning, scenario scripting, character creation.

Backs the /studio pages. Everything routes through the GPT-SoVITS `api_v2` server, which
already provides the two things this feature needs:

  * `ref_audio_path`  -> zero-shot cloning from ANY reference clip, no training required
  * `speed_factor`    -> natural pace control

Volume is applied here rather than by the server, which has no volume parameter.

Three capabilities:
  characters  five presets (2 fine-tuned KOL voices + 3 zero-shot), EN and zh-TW
  clone       upload a reference clip and speak arbitrary text in that voice
  script      turn a scenario description into a script in a character's own voice

    python tools/studio/voice_studio.py list
    python tools/studio/voice_studio.py say lena-chen "大家好" --speed 1.0 -o out.wav
    python tools/studio/voice_studio.py clone ref.wav "Hello there" -o out.wav
    python tools/studio/voice_studio.py script sofia-vargas "unboxing a new sunscreen"
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools" / "voice_crawl"))
sys.path.insert(0, str(REPO / "tools" / "livetalking"))

TTS_API = os.getenv("TTS_API", "http://127.0.0.1:9880")
STUDIO_DIR = REPO / "kols" / "_studio"          # presets + uploads + renders live here
PRESET_DIR = STUDIO_DIR / "presets"
OUT_DIR = STUDIO_DIR / "out"
UPLOAD_DIR = STUDIO_DIR / "uploads"

# Base (non-fine-tuned) weights, used for every zero-shot voice.
# Note the two similarly-named directories: "GPT-SoVITS" (the engine checkout, hyphen) and
# "GPT_SoVITS" (the python package inside it, underscore). These paths are repo-relative and
# need BOTH, which is easy to get wrong — omitting the outer one yields an opaque HTTP 400
# from api_v2 rather than a missing-file error.
BASE_SOVITS = ("GPT-SoVITS/GPT_SoVITS/pretrained_models/gsv-v2final-pretrained/"
               "s2G2333k.pth")
BASE_GPT = ("GPT-SoVITS/GPT_SoVITS/pretrained_models/gsv-v2final-pretrained/"
            "s1bert25hz-5kh-longer-epoch=12-step=369668.ckpt")

# The five characters: 3 English, 2 Taiwan Mandarin. All five are fine-tuned on ~30 min of
# audio, which sounds markedly more natural than zero-shot. `kind` is NOT stored here — it is
# derived from what is on disk by is_finetuned(), so a voice cannot be mislabelled.
# `edge_voice` is the timbre each was bootstrapped from, and is also the zero-shot fallback
# if its weights are ever missing.
CHARACTERS = [
    {"id": "sofia-vargas", "name": "Sofia Vargas", "lang": "en",
     "edge_voice": "es-MX-DaliaNeural",
     "blurb": "Warm Latin-American host, honest-review energy",
     "sample": "Honestly, this is my favourite thing I have tried all month."},
    {"id": "lena-chen", "name": "Lena Chen 陳語彤", "lang": "zh",
     "edge_voice": "en-US-AvaMultilingualNeural",
     "blurb": "甜妹賣貨 KOC — 台灣國語，甜亮語調",
     "sample": "大家好，今天分享一個好物，我自己真的用過才敢說。"},
    {"id": "preset-en-warm", "name": "Chloe (EN, warm)", "lang": "en",
     "edge_voice": "en-US-EmmaMultilingualNeural",
     "blurb": "Calm, friendly English narrator — good for explainers",
     "sample": "Let me walk you through what is actually inside the box."},
    {"id": "preset-en-bright", "name": "Ava (EN, bright)", "lang": "en",
     "edge_voice": "en-US-AriaNeural",
     "blurb": "Upbeat English presenter — good for hooks",
     "sample": "Okay, this one genuinely surprised me — and I did not expect that."},
    {"id": "preset-zhtw", "name": "Hsiao-Yu 小雨 (zh-TW)", "lang": "zh",
     "edge_voice": "zh-TW-HsiaoYuNeural",
     "blurb": "台灣國語女聲，自然口語 — 適合日常口播",
     "sample": "這款我用了三週，質地清爽，夏天也不會悶。"},
]

# Reference text spoken when building each preset's reference clip. GPT-SoVITS needs the
# reference audio AND its exact transcript, so both are generated together.
PRESET_REF_TEXT = {
    "en": "I have been using this for about three weeks now, and honestly it works well.",
    "zh": "我自己真的用過才敢說，這個東西的質地很清爽，用起來很舒服。",
}

LANGS = {"en": "English", "zh": "Chinese (Taiwan Mandarin)"}


def is_finetuned(cid: str) -> bool:
    """True when this character has usable fine-tuned weights on disk.

    Derived rather than hardcoded, so a preset upgrades from zero-shot to fine-tuned the
    moment `build_voice.py` finishes — no edit to this file, and no risk of the declared
    `kind` drifting out of step with reality.
    """
    p = REPO / "kols" / cid / "profile.json"
    if not p.is_file():
        return False
    try:
        v = (json.loads(p.read_text(encoding="utf-8")).get("ai_assets") or {}).get("voice") or {}
    except Exception:
        return False
    sov, gpt = v.get("sovits_weights"), v.get("gpt_weights")
    return bool(sov and gpt and (REPO / sov).is_file() and (REPO / gpt).is_file())


def char_by_id(cid: str) -> dict | None:
    c = next((c for c in CHARACTERS if c["id"] == cid), None)
    if c is not None:
        c = dict(c)
        c["kind"] = "finetuned" if is_finetuned(cid) else "zeroshot"
    return c


def characters() -> list[dict]:
    """The character list with `kind` resolved against what is actually on disk."""
    return [char_by_id(c["id"]) for c in CHARACTERS]


# ------------------------------------------------------------------ api_v2 glue

_loaded = {"sovits": None, "gpt": None}


def _get(path: str, params: dict, timeout: float = 60) -> bytes:
    url = f"{TTS_API}{path}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read()


def api_alive() -> bool:
    try:
        urllib.request.urlopen(f"{TTS_API}/docs", timeout=3)
        return True
    except Exception:
        return False


def set_weights(sovits: str, gpt: str) -> None:
    """Switch api_v2's loaded weights, skipping the call when already loaded.

    api_v2 is stateful: whatever weights were last set stay active for every later
    request. Zero-shot voices therefore have to switch back to the base checkpoints, or
    they would inherit whichever KOL was synthesised previously.
    """
    # Check locally first: api_v2 answers a missing path with a bare HTTP 400, which is
    # far harder to diagnose than naming the file that is absent.
    for label, path in (("sovits", sovits), ("gpt", gpt)):
        if not Path(path).is_file():
            raise FileNotFoundError(f"{label} weights not found: {path}")
    if _loaded["sovits"] != sovits:
        _get("/set_sovits_weights", {"weights_path": sovits}, timeout=180)
        _loaded["sovits"] = sovits
    if _loaded["gpt"] != gpt:
        _get("/set_gpt_weights", {"weights_path": gpt}, timeout=180)
        _loaded["gpt"] = gpt


def _abs(p: str) -> str:
    q = Path(p)
    return str(q if q.is_absolute() else (REPO / q))


def voice_config(cid: str) -> dict:
    """Resolve a character to the weights + reference clip needed to speak as them."""
    c = char_by_id(cid)
    if not c:
        raise KeyError(f"unknown character {cid}")
    if c["kind"] == "finetuned":
        prof = json.loads((REPO / "kols" / cid / "profile.json").read_text(encoding="utf-8"))
        v = (prof.get("ai_assets") or {}).get("voice") or {}
        # A fine-tuned voice speaks best from its OWN reference clip; fall back to the
        # preset clip if the profile somehow lacks one.
        ref = v.get("reference_audio")
        if ref and (REPO / ref).is_file():
            ref_audio, ref_text = _abs(ref), v.get("reference_text", "")
        else:
            w, t = ensure_preset(cid)
            ref_audio, ref_text = str(w), t
        return {"sovits": _abs(v["sovits_weights"]), "gpt": _abs(v["gpt_weights"]),
                "ref_audio": ref_audio, "ref_text": ref_text,
                "ref_lang": v.get("reference_lang", c["lang"])}
    ref_wav, ref_txt = ensure_preset(cid)
    return {"sovits": _abs(BASE_SOVITS), "gpt": _abs(BASE_GPT),
            "ref_audio": str(ref_wav), "ref_text": ref_txt, "ref_lang": c["lang"]}


def ensure_preset(cid: str) -> tuple[Path, str]:
    """Create a zero-shot preset's reference clip on first use, then cache it."""
    import asyncio

    c = char_by_id(cid)
    PRESET_DIR.mkdir(parents=True, exist_ok=True)
    wav = PRESET_DIR / f"{cid}.wav"
    txt = PRESET_DIR / f"{cid}.txt"
    if wav.is_file() and txt.is_file():
        return wav, txt.read_text(encoding="utf-8").strip()

    import edge_tts
    import ffmpeg_util

    text = PRESET_REF_TEXT[c["lang"]]
    mp3 = PRESET_DIR / f"{cid}.mp3"
    asyncio.run(edge_tts.Communicate(text, c["edge_voice"]).save(str(mp3)))
    ffmpeg_util.to_mono_wav(mp3, wav, 32000, loudnorm=True)
    mp3.unlink(missing_ok=True)
    txt.write_text(text, encoding="utf-8")
    return wav, text


def apply_volume(wav_path: Path, gain_db: float) -> None:
    """Scale amplitude in place. api_v2 has no volume parameter, so do it here — and clamp
    to avoid clipping, which sounds far worse than a slightly quiet clip."""
    if abs(gain_db) < 0.01:
        return
    import numpy as np
    import soundfile as sf

    data, sr = sf.read(str(wav_path), dtype="float32", always_2d=False)
    scaled = data * (10 ** (gain_db / 20.0))
    peak = float(abs(scaled).max()) if scaled.size else 0.0
    if peak > 0.99:
        scaled = scaled * (0.99 / peak)
    sf.write(str(wav_path), scaled, sr, subtype="PCM_16")


def synthesize(cid: str, text: str, *, speed: float = 1.0, volume_db: float = 0.0,
               lang: str | None = None, out: Path | None = None,
               ref_audio: str | None = None, ref_text: str | None = None,
               ref_lang: str | None = None) -> Path:
    """Speak `text` as character `cid` (or with an explicit reference clip for cloning)."""
    if not api_alive():
        raise RuntimeError(
            f"GPT-SoVITS api_v2 is not reachable at {TTS_API}. Start it with:\n"
            "  cd GPT-SoVITS; .\\.venv\\Scripts\\python.exe api_v2.py -a 127.0.0.1 -p 9880 "
            "-c GPT_SoVITS/configs/tts_infer.yaml")

    if ref_audio:      # ad-hoc clone: base weights + the caller's reference
        cfg = {"sovits": _abs(BASE_SOVITS), "gpt": _abs(BASE_GPT),
               "ref_audio": _abs(ref_audio), "ref_text": ref_text or "",
               "ref_lang": ref_lang or "en"}
    else:
        cfg = voice_config(cid)

    set_weights(cfg["sovits"], cfg["gpt"])
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = out or (OUT_DIR / f"{cid}_{int(time.time())}.wav")

    body = json.dumps({
        "text": text,
        # "auto" lets GPT-SoVITS detect language per segment, which is what makes a mixed
        # sentence like "這個好物 real talk" pronounce correctly.
        "text_lang": lang or "auto",
        "ref_audio_path": cfg["ref_audio"],
        "prompt_text": cfg["ref_text"],
        "prompt_lang": cfg["ref_lang"],
        "speed_factor": float(speed),
        "media_type": "wav",
        "streaming_mode": False,
        # Defaults tuned for naturalness rather than novelty; the product needs a voice
        # that sounds like a person reading their own script, not a performance.
        "top_k": 15, "top_p": 1.0, "temperature": 1.0,
        "text_split_method": "cut5",
    }).encode()
    req = urllib.request.Request(f"{TTS_API}/tts", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            audio = r.read()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"api_v2 rejected the request: {exc.read().decode()[:300]}") from exc

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(audio)
    if not out.is_file() or out.stat().st_size < 1000:
        raise RuntimeError("api_v2 returned no usable audio")
    apply_volume(out, volume_db)
    return out


def transcribe(path: Path, lang: str | None = None) -> str:
    """Auto-transcribe an uploaded reference clip.

    GPT-SoVITS needs the reference transcript to match the audio; making a user type it by
    hand is both tedious and the most common way to get a bad clone.
    """
    from faster_whisper import WhisperModel
    model = WhisperModel("small", device="cpu", compute_type="int8")
    segs, info = model.transcribe(str(path), language=lang, vad_filter=True)
    return "".join(s.text for s in segs).strip(), (info.language or lang or "en")


# ------------------------------------------------------------- scenario -> script

def write_script(cid: str, scenario: str, *, seconds: int = 20,
                 model: str | None = None) -> str:
    """Turn a scenario description into a spoken script in the character's own voice."""
    from openai import OpenAI

    c = char_by_id(cid) or {"lang": "en", "name": cid}
    lang_name = LANGS.get(c["lang"], "English")
    words = max(30, int(seconds * (2.6 if c["lang"] == "en" else 3.6)))

    # Fine-tuned characters are real KOLs with a persona on file — use it, so the script
    # sounds like them rather than like generic ad copy.
    persona = ""
    if c.get("kind") == "finetuned":
        try:
            from persona_brain import build_system_prompt
            persona = build_system_prompt(cid)
        except Exception:
            persona = ""
    if not persona:
        persona = (f"You are {c['name']}, a friendly virtual influencer who reviews products "
                   f"honestly and speaks in {lang_name}.")

    rules = (
        f"Write a spoken script for this scenario: {scenario}\n\n"
        f"Rules:\n"
        f"- Language: {lang_name} only.\n"
        f"- About {words} words, roughly {seconds} seconds when read aloud.\n"
        f"- It will be SPOKEN by a voice model. Output ONLY the words to say — no headings, "
        f"no stage directions, no speaker labels, no emoji, no markdown, no bullet points.\n"
        f"- Write numbers and prices as spoken words.\n"
        f"- Do not invent a specific price, discount, or link.\n"
        f"- Natural spoken rhythm: short sentences, contractions, one idea per sentence.\n"
        f"- End on a question or a light call to action."
    )
    client = OpenAI(base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1"),
                    api_key="ollama")
    r = client.chat.completions.create(
        model=model or os.getenv("KOL_LLM_MODEL", "qwen2.5:7b"),
        messages=[{"role": "system", "content": persona},
                  {"role": "system", "content": rules},
                  {"role": "user", "content": scenario}],
        temperature=0.7, max_tokens=600)
    text = (r.choices[0].message.content or "").strip()

    from persona_brain import sanitize_for_speech, wants_traditional
    trad = c["lang"] == "zh" and (c.get("kind") != "finetuned" or wants_traditional(cid))
    return sanitize_for_speech(text, trad)


# --------------------------------------------------------------- character maker

CHARACTER_SCHEMA_HINT = """Return ONLY valid JSON, no prose, with exactly these keys:
{"name": str, "name_local": str or null, "age": int, "ethnicity": str,
 "archetype": str, "personality_traits": [str, str, str, str],
 "values": [str, str, str], "voice_tone": str, "humor_style": str,
 "quirks": [str, str, str], "content_pillars": [str, str, str],
 "primary_language": "en" or "zh", "suggested_edge_voice": str,
 "appearance_prompt": str}"""


def create_character(prompt: str, *, model: str | None = None) -> dict:
    """Generate a character sheet from a free-text prompt.

    Returns the same shape the KOL profiles use, so it can be saved as a real persona and
    then flow through the existing voice/avatar pipeline unchanged.
    """
    from openai import OpenAI

    client = OpenAI(base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1"),
                    api_key="ollama")
    sysmsg = ("You design virtual influencer (KOL) characters for a shopping-focused brand. "
              "Characters must be adults, tasteful and never explicit. "
              "suggested_edge_voice must be a Microsoft Edge TTS short name such as "
              "en-US-AvaMultilingualNeural or zh-TW-HsiaoChenNeural, matching "
              "primary_language. appearance_prompt is a single image-generation prompt "
              "describing a photoreal portrait.\n\n" + CHARACTER_SCHEMA_HINT)
    r = client.chat.completions.create(
        model=model or os.getenv("KOL_LLM_MODEL", "qwen2.5:7b"),
        messages=[{"role": "system", "content": sysmsg},
                  {"role": "user", "content": prompt}],
        temperature=0.85, max_tokens=900,
        response_format={"type": "json_object"})
    raw = (r.choices[0].message.content or "").strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        s, e = raw.find("{"), raw.rfind("}")
        if s < 0 or e < 0:
            raise RuntimeError(f"model did not return JSON: {raw[:200]}")
        data = json.loads(raw[s:e + 1])
    data.setdefault("primary_language", "en")
    # The model returns Simplified Chinese even for a Taiwanese character (26岁 rather than
    # 26歲). Convert the free-text fields for consistency with the zh-TW personas.
    if data.get("primary_language") == "zh":
        try:
            from persona_brain import sanitize_for_speech
            for k, v in list(data.items()):
                if isinstance(v, str):
                    data[k] = sanitize_for_speech(v, True)
                elif isinstance(v, list):
                    data[k] = [sanitize_for_speech(x, True) if isinstance(x, str) else x
                               for x in v]
        except Exception:
            pass
    return data


def save_character(data: dict, kol_id: str) -> Path:
    """Persist a generated character as a real profile.json the pipeline can consume."""
    d = REPO / "kols" / kol_id
    if (d / "profile.json").exists():
        raise FileExistsError(f"{kol_id} already exists — pick another id")
    d.mkdir(parents=True, exist_ok=True)
    lang = data.get("primary_language", "en")
    prof = {
        "id": kol_id,
        "meta": {"created_at": time.strftime("%Y-%m-%d"), "status": "draft",
                 "category": "lifestyle", "generated_by": "voice_studio",
                 "design_note": "Generated from a prompt in the Voice Studio; review before use."},
        "identity": {
            "name": data.get("name") or kol_id,
            "name_zh": data.get("name_local"),
            "age": data.get("age", 24),
            "ethnicity": data.get("ethnicity", ""),
            "languages": (["Mandarin / Traditional Chinese (native)", "English (fluent)"]
                          if lang == "zh" else ["English (native)"]),
        },
        "persona": {
            "archetype": data.get("archetype", ""),
            "personality_traits": data.get("personality_traits", []),
            "values": data.get("values", []),
            "voice_tone": data.get("voice_tone", ""),
            "humor_style": data.get("humor_style", ""),
            "quirks": data.get("quirks", []),
        },
        "content": {"pillars": [{"name": p} for p in data.get("content_pillars", [])]},
        "social": {"comment_policy_mode": "suggest"},
        "ai_assets": {
            "voice": {"engine": "gpt-sovits", "source": "synthetic_bootstrap",
                      "bootstrap_timbre": f"edge:{data.get('suggested_edge_voice','')}",
                      "status": "not_started",
                      "reference_lang": lang},
            "image_prompt": data.get("appearance_prompt", ""),
        },
    }
    (d / "profile.json").write_text(json.dumps(prof, ensure_ascii=False, indent=2) + "\n",
                                    encoding="utf-8")
    for sub in ("images", "videos", "voice"):
        (d / sub).mkdir(exist_ok=True)
    return d / "profile.json"


# --------------------------------------------------------------------------- CLI

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="show the five characters")

    s = sub.add_parser("say", help="speak text as a character")
    s.add_argument("character"); s.add_argument("text")
    s.add_argument("--speed", type=float, default=1.0)
    s.add_argument("--volume-db", type=float, default=0.0)
    s.add_argument("--lang", default=None)
    s.add_argument("-o", "--out", default=None)

    c = sub.add_parser("clone", help="speak text using an uploaded reference clip")
    c.add_argument("ref_audio"); c.add_argument("text")
    c.add_argument("--ref-text", default=None, help="default: auto-transcribed")
    c.add_argument("--speed", type=float, default=1.0)
    c.add_argument("--volume-db", type=float, default=0.0)
    c.add_argument("-o", "--out", default=None)

    sc = sub.add_parser("script", help="scenario -> spoken script")
    sc.add_argument("character"); sc.add_argument("scenario")
    sc.add_argument("--seconds", type=int, default=20)
    sc.add_argument("--say", action="store_true", help="also synthesize it")

    ch = sub.add_parser("character", help="generate a character from a prompt")
    ch.add_argument("prompt")
    ch.add_argument("--save-as", default=None, help="kol id to save it under")

    args = ap.parse_args()

    if args.cmd == "list":
        print(f"api_v2: {'UP' if api_alive() else 'DOWN'}  ({TTS_API})\n")
        for c in characters():
            tag = "fine-tuned" if c["kind"] == "finetuned" else "zero-shot"
            print(f"  {c['id']:18s} {LANGS[c['lang']]:26s} {tag:11s} {c['name']}")
            print(f"                     {c['blurb']}")
        return 0

    if args.cmd == "say":
        out = synthesize(args.character, args.text, speed=args.speed,
                         volume_db=args.volume_db, lang=args.lang,
                         out=Path(args.out) if args.out else None)
        print(f"wrote {out}")
        return 0

    if args.cmd == "clone":
        ref = Path(args.ref_audio)
        rt, rl = (args.ref_text, None) if args.ref_text else transcribe(ref)
        print(f"reference transcript: {rt}")
        out = synthesize("_clone", args.text, speed=args.speed, volume_db=args.volume_db,
                         out=Path(args.out) if args.out else None,
                         ref_audio=str(ref), ref_text=rt, ref_lang=rl or "en")
        print(f"wrote {out}")
        return 0

    if args.cmd == "script":
        text = write_script(args.character, args.scenario, seconds=args.seconds)
        print(text)
        if args.say:
            print(f"\nwrote {synthesize(args.character, text)}")
        return 0

    if args.cmd == "character":
        data = create_character(args.prompt)
        print(json.dumps(data, ensure_ascii=False, indent=2))
        if args.save_as:
            print(f"\nsaved -> {save_character(data, args.save_as)}")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
