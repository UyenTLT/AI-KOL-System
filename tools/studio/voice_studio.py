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
import re
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


def gsv_block(cid: str) -> dict:
    """The GPT-SoVITS half of a character's voice config.

    Usually that is the voice block itself. When a character has moved to another engine —
    sofia-vargas to CosyVoice 2 — the GPT-SoVITS setup is kept under `gpt_sovits_previous`,
    and everything that speaks api_v2 (the fine-tuned check, the weight lookup, LiveTalking)
    has to read it from there.

    Getting this wrong is silent rather than loud: without it `is_finetuned` returned False,
    the character was treated as zero-shot, and synthesis fell back to the *base* checkpoint
    with a generic edge-tts reference. Audio still came out. It just was not her.
    """
    p = REPO / "kols" / cid / "profile.json"
    if not p.is_file():
        return {}
    try:
        v = (json.loads(p.read_text(encoding="utf-8")).get("ai_assets") or {}).get("voice") or {}
    except Exception:
        return {}
    if v.get("engine") and v["engine"] != "gpt-sovits" and v.get("gpt_sovits_previous"):
        return v["gpt_sovits_previous"]
    return v


def is_finetuned(cid: str) -> bool:
    """True when this character has usable fine-tuned weights on disk.

    Derived rather than hardcoded, so a preset upgrades from zero-shot to fine-tuned the
    moment `build_voice.py` finishes — no edit to this file, and no risk of the declared
    `kind` drifting out of step with reality.
    """
    v = gsv_block(cid)
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
        v = gsv_block(cid)      # not the raw voice block — see gsv_block's docstring
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


COSY_API = os.getenv("COSYVOICE_API", "http://127.0.0.1:9881")


def _cosyvoice_config(cid: str) -> dict | None:
    """The CosyVoice block from a profile, or None if this character does not use it.

    Returns None rather than raising when the server is down, so the character falls back to
    the GPT-SoVITS voice kept in `voice.gpt_sovits_previous` instead of failing outright. A
    slightly different voice beats no voice when something downstream is mid-render.
    """
    try:
        prof = json.loads((REPO / "kols" / cid / "profile.json").read_text(encoding="utf-8"))
    except Exception:
        return None
    v = (prof.get("ai_assets") or {}).get("voice") or {}
    if v.get("engine") != "cosyvoice2":
        return None
    try:
        urllib.request.urlopen(f"{v.get('api', COSY_API)}/health", timeout=2)
    except Exception:
        print(f"  [warn] {cid} is configured for CosyVoice 2 but {v.get('api', COSY_API)} is "
              f"not answering — falling back to the previous GPT-SoVITS voice. Start it with:\n"
              f"         CosyVoice\\.venv\\Scripts\\python.exe tools\\voice_eval\\cosy_server.py")
        return None
    return v


def _cosy_alive(api: str | None = None) -> bool:
    try:
        urllib.request.urlopen(f"{api or COSY_API}/health", timeout=2)
        return True
    except Exception:
        return False


def _clone_cosyvoice(text: str, ref_audio: str, ref_text: str, *, speed: float = 1.0,
                     volume_db: float = 0.0, out: Path | None = None,
                     target_lufs: float | None = -16.0) -> Path:
    """Speak `text` in the voice of an arbitrary reference clip, zero-shot.

    The transcript is not optional in the way it looks. CosyVoice matches the prompt audio
    against the prompt *text*, so a wrong or empty one is the usual cause of a clone that
    sounds nothing like the source — which is why the caller auto-transcribes when none is
    given rather than leaving it blank.
    """
    if not ref_text.strip():
        raise ValueError("cloning needs the reference transcript — pass ref_text, or let the "
                         "caller fill it in with transcribe()")
    body = {"text": text, "mode": "zero_shot", "ref": ref_audio, "ref_text": ref_text}
    req = urllib.request.Request(f"{COSY_API}/say", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            audio = r.read()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"cosy_server rejected the clone: {exc.read().decode()[:300]}") from exc

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = out or (OUT_DIR / f"clone_{int(time.time())}.wav")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(audio)
    if out.stat().st_size < 1000:
        raise RuntimeError("cosy_server returned no usable audio")
    if abs(speed - 1.0) > 0.01:
        _retime(out, speed)
    if target_lufs is not None:
        _normalise_loudness(out, float(target_lufs))
    apply_volume(out, volume_db)
    return out


def _synthesize_cosyvoice(cid: str, text: str, v: dict, *, speed: float = 1.0,
                          volume_db: float = 0.0, out: Path | None = None,
                          instruct: str | None = None) -> Path:
    ref = v.get("reference_audio")
    ref_abs = _abs(ref) if ref else None
    if not ref_abs or not Path(ref_abs).is_file():
        raise RuntimeError(f"{cid}: reference clip missing ({ref})")

    mode = v.get("mode", "zero_shot")
    body = {"text": text, "mode": mode, "ref": ref_abs}
    if mode == "instruct":
        # A caller may override the profile's standing instruction for one line. The instruction
        # is a real delivery control, not a label: measured on this voice, the profile's
        # conversational wording gives 17.50 semitones of pitch range, while "softly and
        # tenderly, almost whispering" gives 8.17 over 5.1 s instead of 3.8. That is the
        # difference between answering a comment and confiding something.
        chosen = instruct or v.get("instruct") or "Speak naturally."
        # A long instruction gets spoken. Measured: at 219 characters the model read most of the
        # instruction aloud inside the answer, and the transcript of the audio matched the text
        # it was given by 0.409 instead of 1.000. At 74 and 87 characters it matched perfectly.
        # The cap is a warning rather than a truncation because silently cutting an instruction
        # would change the delivery without saying so — this makes the cause visible in the log
        # the first time it happens, instead of after transcribing the output to find out.
        if len(chosen) > 120:
            print(f"  warning: instruct is {len(chosen)} characters. Past roughly 120 CosyVoice "
                  f"starts speaking the instruction aloud — keep it under one short sentence.",
                  flush=True)
        body["instruct"] = chosen
    else:
        body["ref_text"] = v.get("reference_text", "")

    req = urllib.request.Request(f"{v.get('api', COSY_API)}/say",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            audio = r.read()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"cosy_server rejected the request: {exc.read().decode()[:300]}") from exc

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = out or (OUT_DIR / f"{cid}_{int(time.time())}.wav")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(audio)
    if out.stat().st_size < 1000:
        raise RuntimeError("cosy_server returned no usable audio")
    # Timbre first: see _timbre_pass. Off unless the character configures it.
    tp = v.get("timbre_pass")
    if tp:
        cfg = {"api": tp} if isinstance(tp, str) else dict(tp)
        if cfg.get("api"):
            _timbre_pass(out, cfg["api"], float(cfg.get("timeout", 30.0)))
    # Softening runs before loudness so the level is set on what actually gets heard: cutting
    # 4 dB out of the busiest band afterwards would leave every line quieter than it asked to be.
    soft = v.get("soften")
    if soft is not False:
        s = soft if isinstance(soft, dict) else {}
        _soften(out, float(s.get("hz", 3200.0)), float(s.get("gain_db", -4.0)))
    # CosyVoice has no speed parameter; resample the timeline rather than pretend it does.
    if abs(speed - 1.0) > 0.01:
        _retime(out, speed)
    if v.get("target_lufs") is not None:
        _normalise_loudness(out, float(v["target_lufs"]))
    # Off unless the character asks for it: the other four voices have not been measured
    # for this and a bed under a voice that does not need one is just added noise.
    rt = v.get("room_tone")
    if rt:
        cfg = {"file": rt} if isinstance(rt, str) else dict(rt)
        if cfg.get("file"):
            _room_tone(out, Path(_abs(cfg["file"])), float(cfg.get("range_db", 18.0)))
    apply_volume(out, volume_db)
    return out


def _room_tone(path: Path, tone: Path, target_range_db: float = 18.0) -> None:
    """Lay a bed of real room tone under a rendered line, in place.

    Measured speech-to-floor distance, 90th percentile of frame energy against the 2nd:

        Sofia as rendered                49.8 dB   (n=4, sd 2.7)
        the owner's raw phone recording  18.1 dB
        ref_human.wav.orig, untouched    16.8 dB
        ref_human.wav, after denoising   54.2 dB

    The reference she is cloned from was denoised, which took the room out of it, and the clone
    reproduces exactly that: gaps between phrases at digital silence. No microphone has ever
    produced 50 dB of range in a room with a person in it, and the ear reads the sound switching
    on and off rather than somebody talking. Pitch range, duration, pause length and declination
    all matched the human reference already -- this is what did not.

    The tone is cut from the owner's own recording rather than generated, so it carries that
    microphone's self-noise and that room. Applied after loudness normalisation so the ratio is
    set against the final speech level, and before `apply_volume`, which scales both together
    and therefore leaves the ratio alone.
    """
    import subprocess
    if not tone.is_file():
        return
    tmp = path.with_suffix(".tone.wav")

    def _level(f: Path, pct: float) -> float | None:
        """A percentile of per-frame RMS. Feeds the file with -i rather than naming it inside a
        lavfi filtergraph: on Windows the drive colon is a filter-argument separator and the
        path gets mangled before ffmpeg ever opens it. reset=1 matters too -- the default
        reports the running cumulative level, so every frame comes back near the file average
        and a bed sized from it lands about 13 dB too quiet."""
        try:
            r = subprocess.run(
                ["ffmpeg", "-v", "error", "-i", str(f), "-af",
                 "astats=metadata=1:reset=1,ametadata=print:"
                 "key=lavfi.astats.Overall.RMS_level:file=-", "-f", "null", "-"],
                capture_output=True, text=True, timeout=90)
            vals = []
            for line in (r.stdout or "").splitlines():
                if "RMS_level=" in line:
                    try:
                        v = float(line.rsplit("=", 1)[1])
                    except ValueError:
                        continue
                    if v > -200:            # digital silence carries no level to speak of
                        vals.append(v)
            if not vals:
                return None
            vals.sort()
            return vals[min(int(pct * len(vals)), len(vals) - 1)]
        except Exception:
            return None

    # Speech level of this line, so the bed sits a fixed distance under it rather than at a
    # fixed absolute level -- a quiet line with a loud bed would sound like a bad connection.
    speech_db = _level(path, 0.90)
    tone_db = _level(tone, 0.50)
    if speech_db is None or tone_db is None:
        return                              # no reliable level: leave the line alone
    bed_db = speech_db - target_range_db
    gain = bed_db - tone_db
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(path),
           "-stream_loop", "-1", "-i", str(tone),
           "-filter_complex",
           f"[1:a]volume={gain:.1f}dB[bed];[0:a][bed]amix=inputs=2:duration=first:"
           f"dropout_transition=0:normalize=0[out]",
           "-map", "[out]", str(tmp)]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=120)
        tmp.replace(path)
    except Exception:
        tmp.unlink(missing_ok=True)


def _timbre_pass(path: Path, api: str, timeout: float = 30.0) -> bool:
    """Replace the timbre of a rendered line with the trained voice, in place.

    Her speaking voice is a zero-shot clone from a 6.5 second reference; the RVC model is
    trained on 98.5 minutes of the same person. Identity against her real reference, level
    matched, five lines:

        CosyVoice alone     0.4790
        CosyVoice + RVC     0.8664

    The clone was roughly half-way to her voice. Prosody is not disturbed -- pitch range
    12.82 -> 11.46 semitones over four clips against a pooled spread of 2.54, duration
    unchanged to two decimal places -- which is the split this needs: CosyVoice performs the
    line, RVC decides whose voice performs it.

    Runs FIRST, before softening and loudness. Those were measured on the CosyVoice timbre and
    the bed of room tone is laid last of all; converting after either would put RVC to work on
    an EQ curve and a noise floor rather than on a voice.

    Returns False and leaves the audio untouched if the server is not up, because a line in the
    wrong timbre is better than no line at all on a live stream.
    """
    import urllib.request
    body = json.dumps({"input": str(path.resolve()), "output": str(path.resolve())}).encode()
    req = urllib.request.Request(f"{api}/convert", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout):
            return True
    except Exception as exc:
        print(f"  warning: timbre pass skipped ({type(exc).__name__}). Start it with:\n"
              f"    RVC\\.venv\\Scripts\\python.exe tools\\voice_eval\\rvc_server.py",
              flush=True)
        return False


def _soften(path: Path, hz: float = 3200.0, gain_db: float = -4.0) -> None:
    """Take the edge off a rendered line, in place.

    2-5 kHz is where a voice reads as harsh, and a 4 dB dip at 3.2 kHz measurably lowers it:
    13.6% of the band's energy before against 10.7% after, over four runs each with standard
    deviations of 0.3 and 0.7. Speaker similarity is unchanged within noise (0.657 to 0.645).

    Two things that were tried for the same goal and are NOT here, because the measurements did
    not support them:

    * **Raising the pitch by resampling.** +2 semitones reached 217 Hz, which is more centrally
      in the female range, and cost harshness (13.8% to 18.3%) and identity (0.633 to 0.534).
      Formants move with the pitch and the result is a smaller voice, not a softer one.
    * **Rewording the delivery instruction.** A warmer wording looked like it raised her register
      by 13 Hz over three runs and by -14 Hz over the next four. The run-to-run spread is ±5.3 Hz
      and the effect is not real.
    """
    import subprocess
    tmp = path.with_suffix(".soft.wav")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(path),
                    "-af", f"equalizer=f={hz}:width_type=o:width=1.4:g={gain_db}", str(tmp)],
                   check=True, capture_output=True, text=True,
                   encoding="utf-8", errors="replace")
    tmp.replace(path)


def _normalise_loudness(path: Path, lufs: float, true_peak: float = -1.5) -> None:
    """Bring a render to a fixed loudness with headroom to spare.

    Two separate reasons, and only the first is obvious. The recordings this project clones from
    sit around -34 LUFS where speech is normally -16, so output was simply quiet. Less obvious:
    once the reference was cleaned and levelled, renders started landing at a -0.1 dB peak,
    which survives as a wav and clips the moment anything encodes it. A true-peak ceiling of
    -1.5 dBTP costs nothing audible and removes that.

    Driven by `voice.target_lufs` in the profile rather than applied to everyone, so the four
    GPT-SoVITS voices keep their existing levels until someone decides otherwise.
    """
    import subprocess

    # Limit first, as its own pass. Peaks reach the true-peak ceiling before the integrated
    # loudness gets near target, so loudnorm correctly refuses to push further and the clip
    # lands 3-4 dB quiet; shaving the peaks buys about 1.5 dB at no cost to pitch range
    # (measured 100%, against 99% for compression at 2:1 or 3:1).
    #
    # Two details, both learned the hard way. `level=false` stops alimiter applying its own
    # auto-normalisation. And the loudness has to be measured *after* limiting, not before —
    # chaining `alimiter,loudnorm` while feeding loudnorm statistics taken from the unlimited
    # signal describes an input it never sees, and it over-corrects: one voice came out at
    # -12.7 LUFS against a -16 target, clipping at 0.0 dB peak.
    limited = path.with_suffix(".lim.wav")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(path),
                    "-af", "alimiter=limit=0.7:level=false",
                    "-ar", "32000", "-ac", "1", str(limited)], check=True)

    stats = _loudnorm_stats(limited, lufs, true_peak)
    af = (f"loudnorm=I={lufs}:TP={true_peak}:LRA=11:measured_I={stats['input_i']}"
          f":measured_TP={stats['input_tp']}:measured_LRA={stats['input_lra']}"
          f":measured_thresh={stats['input_thresh']}:offset={stats['target_offset']}:linear=true"
          if len(stats) == 5 else f"loudnorm=I={lufs}:TP={true_peak}:LRA=11")
    tmp = path.with_suffix(".norm.wav")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(limited), "-af", af,
                    "-ar", "32000", "-ac", "1", str(tmp)], check=True)
    limited.unlink(missing_ok=True)
    tmp.replace(path)


def _loudnorm_stats(path: Path, lufs: float, true_peak: float) -> dict:
    """loudnorm's own measurement pass, parsed. Missing or infinite values are dropped so the
    caller falls back to single-pass rather than building a filter string with holes in it."""
    import re
    import subprocess
    probe = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
         "-af", f"loudnorm=I={lufs}:TP={true_peak}:LRA=11:print_format=json", "-f", "null", "-"],
        capture_output=True, text=True)
    stats = {}
    for key in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset"):
        m = re.search(rf'"{key}"\s*:\s*"(-?[\d.]+|-?inf)"', probe.stderr)
        if m and "inf" not in m.group(1):
            stats[key] = m.group(1)
    return stats


def _retime(path: Path, speed: float) -> None:
    """Change tempo without changing pitch, via ffmpeg's atempo."""
    import subprocess
    import ffmpeg_util
    tmp = path.with_suffix(".retimed.wav")
    # atempo is only valid over 0.5-2.0; chain it for anything outside that.
    factors, remaining = [], speed
    while remaining > 2.0:
        factors.append(2.0); remaining /= 2.0
    while remaining < 0.5:
        factors.append(0.5); remaining *= 2.0
    factors.append(remaining)
    chain = ",".join(f"atempo={f:.4f}" for f in factors)
    exe = getattr(ffmpeg_util, "FFMPEG", None) or "ffmpeg"
    subprocess.run([str(exe), "-y", "-v", "error", "-i", str(path), "-filter:a", chain,
                    str(tmp)], check=True)
    tmp.replace(path)


def synthesize(cid: str, text: str, *, speed: float = 1.0, volume_db: float = 0.0,
               lang: str | None = None, out: Path | None = None,
               ref_audio: str | None = None, ref_text: str | None = None,
               ref_lang: str | None = None, instruct: str | None = None) -> Path:
    """Speak `text` as character `cid` (or with an explicit reference clip for cloning).

    `instruct` overrides the character's standing delivery instruction for this line only, and
    applies to instruction-controlled engines. Ignored elsewhere, since GPT-SoVITS has no
    equivalent control — a caller that depends on it should check the engine first.
    """
    # A profile can name a different engine. sofia-vargas moved to CosyVoice 2 in
    # instruction-controlled mode on 2026-08-04, chosen by ear and backed by measurement
    # (see her profile's voice.chosen_because). An ad-hoc clone still goes to GPT-SoVITS,
    # because that path is about a caller-supplied reference rather than the character's own.
    if not ref_audio:
        cosy = _cosyvoice_config(cid)
        if cosy:
            return _synthesize_cosyvoice(cid, text, cosy, speed=speed, volume_db=volume_db,
                                         out=out, instruct=instruct)
    if ref_audio and _cosy_alive():
        # Clone through CosyVoice when it is up. Its zero-shot mode is markedly more expressive
        # than GPT-SoVITS on the base checkpoint — measured 16.84 semitones of pitch range
        # against 8.20 on the same reference. The reason that mode was NOT chosen for Sofia was
        # register drift, 39 Hz off the voice she had already established. Cloning an arbitrary
        # clip has no established register to drift from: sounding like the uploaded audio is
        # the entire point, so the drawback there is the goal here.
        return _clone_cosyvoice(text, _abs(ref_audio), ref_text or "", speed=speed,
                                volume_db=volume_db, out=out)

    # Ordering matters, and it was wrong: this guard sat FIRST, so a caller passing a
    # reference clip was told "GPT-SoVITS is not reachable" even with CosyVoice up and
    # ready to serve it. Cloning does not involve GPT-SoVITS unless CosyVoice is down.
    # It stays, just after the branch that no longer needs it.

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
    # Level this path too, or the voices drift apart. Measured before adding it: sofia-vargas
    # (levelled) sat at -15.7 LUFS while the four GPT-SoVITS voices ran -21.6 to -23.9 — an
    # 8.2 dB spread, plainly audible the moment two of them appear in the same video. An
    # ad-hoc clone has no profile to read, so it keeps whatever level it was given.
    if not ref_audio:
        target = gsv_block(cid).get("target_lufs")
        if target is None:
            try:
                prof = json.loads((REPO / "kols" / cid / "profile.json").read_text(encoding="utf-8"))
                target = ((prof.get("ai_assets") or {}).get("voice") or {}).get("target_lufs")
            except Exception:
                target = None
        if target is not None:
            _normalise_loudness(out, float(target))
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

# Bracketed forms are unambiguous. Bare ones are not, so they are only removed when they stand
# alone between sentences — "? looks down Wow." is a direction, "She looks down the list" is
# prose, and the first version of this cut both, leaving "She the list of features".
_STAGE_BRACKET = re.compile(r"[\(\[\*]\s*[^)\]\*\n]{1,60}?\s*[\)\]\*]")
_STAGE_BARE = re.compile(
    r"(?:(?<=[.!?…])|(?<=^)|(?<=\n))\s*"
    r"(?:looks?|glances?|smiles?|laughs?|winks?|nods?|shrugs?|pauses?|sighs?|gestures?|turns?)"
    r"\s+(?:down|up|away|at camera|to camera|around|off|slowly)\s*"
    r"(?=[A-ZÀ-ỹ]|$)",
    re.IGNORECASE)


def _strip_stage_directions(text: str) -> str:
    """Remove the bits a script writer adds for a human performer.

    The rules already say "no stage directions" and one still arrived — "looks down" in the
    middle of a sentence, with no brackets to give it away. A voice model does not perform a
    direction, it reads it, so the phrase is spoken aloud to the viewer. Bracketed forms are
    easy; the bare ones need naming, which is why the verb list is explicit rather than clever.
    """
    cleaned = _STAGE_BARE.sub(" ", _STAGE_BRACKET.sub(" ", text))
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return re.sub(r"\s+([,.!?…])", r"\1", cleaned).strip()


def _fit_length(text: str, target_words: int, tolerance: float = 1.4) -> str:
    """Trim a script back to roughly its target, at a sentence boundary.

    The prompt asks for "about N words" and is treated as a suggestion. Measured against a
    15-second brief, the demo angle returned 160 words — around 64 seconds of speech, four
    times what was asked for. That is not a stylistic quibble: the length is what makes a
    clip usable as a hook or an ad slot at all.

    Trimming rather than regenerating, because the opening of an overlong script is usually
    fine and it is the tail that wanders. Cuts only at a sentence end, so the result never
    stops mid-thought, and leaves the text alone entirely when it is close enough.
    """
    import re as _re
    words = text.split()
    if len(words) <= target_words * tolerance:
        return text
    sentences = _re.split(r"(?<=[.!?…])\s+|(?<=[。！？])\s*", text.strip())
    kept: list[str] = []
    count = 0
    for s in sentences:
        n = len(s.split())
        if kept and count + n > target_words * tolerance:
            break
        kept.append(s)
        count += n
    return " ".join(kept) if kept else text


def load_product(cid: str, product_id: str | None) -> dict | None:
    """One entry from a KOL's products.json — the source of truth for price and link.

    The catalogue exists precisely so a script never has to guess a number: without it the
    guard treats every price as invented, which is correct, and a selling script then cannot
    state one at all.
    """
    if not product_id:
        return None
    p = REPO / "kols" / cid / "products.json"
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    for item in data.get("products", []):
        if item.get("id") == product_id:
            return item
    return None


def _product_brief(prod: dict) -> str:
    """The catalogue entry as instructions, with an explicit fence around what may be claimed."""
    # The persona prompt tells her "never invent a price — prices come from your product list".
    # Without saying that this block *is* that list, the model takes the cautious branch and
    # offers to go and check a price it was handed, which defeats the point of supplying it.
    lines = [f"YOUR PRODUCT LIST — this is the verified catalogue entry your persona rules refer",
             f"to. Every detail below is confirmed. State the price and link as written; do not",
             f"offer to look them up. These are also the ONLY product details you may state:",
             f"  name: {prod.get('name')}"]
    if prod.get("category"):
        lines.append(f"  category: {prod['category']}")
    price = prod.get("price") or {}
    have = {k: v for k, v in price.items() if v not in (None, "")} if isinstance(price, dict) else {}
    if have:
        lines.append("  price: " + ", ".join(f"{k} {v}" for k, v in have.items()))
    else:
        lines.append("  price: NOT KNOWN — do not state a price. Say you will check.")
    links = {k: v for k, v in (prod.get("buy_links") or {}).items() if v}
    lines.append("  link: " + (", ".join(links.values()) if links
                               else "NOT KNOWN — do not claim a link exists."))
    if prod.get("usp"):
        lines.append(f"  selling point: {prod['usp']}")
    if prod.get("honest_notes"):
        lines.append(f"  honest pros and cons, including the downside: {prod['honest_notes']}")
    if prod.get("self_bought_or_sponsored"):
        lines.append(f"  relationship: {prod['self_bought_or_sponsored']} "
                     f"(disclose this if it is sponsored)")
    lines += [
        "",
        "Anything not listed above is unknown to you. Do not invent a price, a discount, a link,",
        "a statistic, a guarantee, or a claim about results, earnings or returns. If the script",
        "needs a fact you were not given, say you will check rather than filling it in.",
    ]
    return "\n".join(lines)


def write_script(cid: str, scenario: str, *, seconds: int = 20,
                 model: str | None = None, product: dict | str | None = None) -> str:
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

    prod = load_product(cid, product) if isinstance(product, str) else product
    brief = f"\n\n{_product_brief(prod)}" if prod else ""

    if prod:
        # The persona rule reads "Prices come from your product list — if you are not certain,
        # say you will check and follow up." With a catalogue supplied, the model still took the
        # cautious branch every time (0 of 3 runs stated a price it had been handed), because
        # nothing told it the uncertainty had been resolved. Rewriting that one clause for this
        # call is narrower than loosening the rule: without a catalogue it stays exactly as it
        # was, and the guard still rejects any number that is not in the entry.
        persona = persona.replace(
            "Prices come from your product list — if you are not certain, say you will check "
            "and follow up.",
            "Prices come from your product list. The catalogue entry in this brief IS that list "
            "and is verified, so state its price and link plainly. Only say you will check when "
            "a detail is genuinely absent from it.")

    rules = (
        f"Write a spoken script for this scenario: {scenario}{brief}\n\n"
        f"Rules:\n"
        f"- Language: {lang_name} only.\n"
        f"- About {words} words, roughly {seconds} seconds when read aloud.\n"
        f"- It will be SPOKEN by a voice model. Output ONLY the words to say — no headings, "
        f"no stage directions, no speaker labels, no emoji, no markdown, no bullet points.\n"
        f"- Write numbers and prices as spoken words.\n"
        + ("- State the price and the link exactly as the product facts give them, or not at "
           "all. Never round, adjust or 'improve' a number.\n" if prod else
           "- Do not invent a specific price, discount, or link.\n")
        + "- Never claim guaranteed returns, profit, earnings, or that anything is risk-free.\n"
        f"- Natural spoken rhythm: short sentences, contractions, one idea per sentence.\n"
        f"- End on a question or a light call to action."
    )
    client = OpenAI(base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1"),
                    api_key="ollama")
    from persona_brain import check_reply, sanitize_for_speech, wants_traditional
    trad = c["lang"] == "zh" and (c.get("kind") != "finetuned" or wants_traditional(cid))

    # Generate, then rule-check — the same treatment a DM reply gets. This path had none,
    # which was backwards: a script becomes a published video, a reply reaches one follower.
    #
    # The rules above already say "Do not invent a specific price, discount, or link", and the
    # model wrote "Price was two hundred and ninety-nine dollars" anyway. That is the whole
    # reason the guards live in code: prompting is not a control.
    messages = [{"role": "system", "content": persona},
                {"role": "system", "content": rules},
                {"role": "user", "content": scenario}]
    last_text, last_bad = "", []
    for attempt in range(2):
        r = client.chat.completions.create(
            model=model or os.getenv("KOL_LLM_MODEL", "qwen2.5:7b"),
            messages=messages, temperature=0.7, max_tokens=600)
        text = sanitize_for_speech((r.choices[0].message.content or "").strip(), trad)
        text = _fit_length(_strip_stage_directions(text), words)
        bad = check_reply(scenario, text, facts=prod)
        if not bad:
            return text
        last_text, last_bad = text, bad
        messages.append({"role": "system", "content":
                         f"That draft broke these hard rules: {', '.join(bad)}. Rewrite it "
                         f"with no invented price, no claimed link, no medical claim, and no "
                         f"offer to negotiate. Say you will check rather than state a number."})

    # Deliberately raised rather than silently returned. A DM reply falls back to a safe
    # canned line because someone is waiting; a script has a human author who can rewrite,
    # and quietly handing back copy that names a made-up price is the worse failure.
    raise ValueError(
        f"script still broke {', '.join(last_bad)} after a retry — rewrite the scenario or "
        f"the line by hand. Offending draft: {last_text[:200]}")


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
