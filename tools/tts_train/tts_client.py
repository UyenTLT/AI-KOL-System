#!/usr/bin/env python3
"""
Client for a fine-tuned GPT-SoVITS voice, served by GPT-SoVITS `api_v2.py`.
Drop-in replacement for macOS `say` in the vlog / talking-web apps.

speak(kol_id, text, lang, out_wav):
  - reads kols/<id>/profile.json -> ai_assets.voice  (weights, reference audio+text, api)
  - sets the KOL's fine-tuned weights, synthesizes with the reference prompt, saves out_wav
  - falls back to macOS `say` if the API is unreachable (so callers never hard-fail)

Env: TTS_API overrides the api URL (default from profile, else http://127.0.0.1:9880).
CLI:  python tools/tts_train/tts_client.py <kol_id> "text" [lang=zh] [out.wav]
NOTE: needs the GPT-SoVITS API server running on a CUDA box; untested on Mac.
"""
import os, sys, json, urllib.request, urllib.parse, subprocess

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

def _voice_cfg(kol_id):
    prof = json.load(open(f"{ROOT}/kols/{kol_id}/profile.json"))
    return prof.get("ai_assets", {}).get("voice", {}) or {}

def _get(api, path, params):
    url = api.rstrip("/") + path + "?" + urllib.parse.urlencode(params)
    return urllib.request.urlopen(url, timeout=60).read()

def _say_fallback(text, lang, out_wav, cfg):
    voice = "Meijia" if lang == "zh" else "Samantha"
    subprocess.run(["say", "-v", voice, "--file-format=WAVE",
                    "--data-format=LEI16@22050", "-o", out_wav, text or "."],
                   capture_output=True, text=True)
    return os.path.exists(out_wav)

def speak(kol_id, text, lang="zh", out_wav="out.wav"):
    cfg = _voice_cfg(kol_id)
    api = os.environ.get("TTS_API") or cfg.get("api") or "http://127.0.0.1:9880"
    # abs-ify weight/reference paths relative to repo root
    def p(x): return x if not x or os.path.isabs(x) else os.path.join(ROOT, x)
    try:
        if cfg.get("engine") != "gpt-sovits" or not cfg.get("sovits_weights"):
            raise RuntimeError("voice not configured for gpt-sovits")
        # 1) select this KOL's fine-tuned weights
        _get(api, "/set_gpt_weights", {"weights_path": p(cfg["gpt_weights"])})
        _get(api, "/set_sovits_weights", {"weights_path": p(cfg["sovits_weights"])})
        # 2) synthesize
        body = json.dumps({
            "text": text, "text_lang": lang,
            "ref_audio_path": p(cfg["reference_audio"]),
            "prompt_text": cfg.get("reference_text", ""),
            "prompt_lang": cfg.get("reference_lang", "zh"),
            "media_type": "wav", "streaming_mode": False,
        }).encode()
        req = urllib.request.Request(api.rstrip("/") + "/tts", data=body,
                                     headers={"Content-Type": "application/json"})
        audio = urllib.request.urlopen(req, timeout=120).read()
        open(out_wav, "wb").write(audio)
        return os.path.exists(out_wav) and os.path.getsize(out_wav) > 1000
    except Exception as e:
        print(f"[tts_client] GPT-SoVITS unavailable ({e}); falling back to `say`.")
        return _say_fallback(text, lang, out_wav, cfg)

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: tts_client.py <kol_id> \"text\" [lang=zh] [out.wav]"); sys.exit(1)
    kol, text = sys.argv[1], sys.argv[2]
    lang = sys.argv[3] if len(sys.argv) > 3 else "zh"
    out = sys.argv[4] if len(sys.argv) > 4 else "out.wav"
    ok = speak(kol, text, lang, out)
    print(("OK -> " + out) if ok else "FAILED")
