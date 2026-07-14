#!/usr/bin/env python3
"""
Prepare a KOL's raw voice into a GPT-SoVITS training set.
  input : kols/<id>/voice/raw/*.{wav,mp3,m4a}
  output: kols/<id>/voice/dataset/*.wav (32k mono)  +  <id>.list  (wav|speaker|lang|text)

Auto-transcribes with faster-whisper IF installed; otherwise writes the wavs and tells you to
run ASR in the GPT-SoVITS WebUI. Resampling uses ffmpeg.

Run on the CUDA box:  python tools/tts_train/data_prep.py <kol_id> [lang=zh]
NOTE: written on a Mac, not runnable end-to-end without faster-whisper/ffmpeg on the GPU box.
"""
import os, sys, glob, subprocess

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

def resample(src, dst):
    subprocess.run(["ffmpeg", "-y", "-i", src, "-ac", "1", "-ar", "32000", dst],
                   capture_output=True, text=True)

def main():
    if len(sys.argv) < 2:
        print("usage: data_prep.py <kol_id> [lang=zh]"); return
    kol = sys.argv[1]; lang = sys.argv[2] if len(sys.argv) > 2 else "zh"
    raw_dir = f"{ROOT}/kols/{kol}/voice/raw"
    out_dir = f"{ROOT}/kols/{kol}/voice/dataset"
    os.makedirs(out_dir, exist_ok=True)
    raws = []
    for ext in ("wav", "mp3", "m4a", "flac"):
        raws += glob.glob(f"{raw_dir}/*.{ext}")
    if not raws:
        print(f"No raw audio in {raw_dir}. Put clean speech there first."); return

    wavs = []
    for i, src in enumerate(sorted(raws)):
        dst = f"{out_dir}/{kol}_{i:03d}.wav"
        resample(src, dst)
        if os.path.exists(dst):
            wavs.append(dst)
    print(f"Resampled {len(wavs)} file(s) -> {out_dir}")

    # Try auto-ASR with faster-whisper (optional dependency)
    try:
        from faster_whisper import WhisperModel
    except Exception:
        print("faster-whisper not installed -> skip ASR. Run slicing+ASR in the GPT-SoVITS WebUI "
              "to produce the .list, or `pip install faster-whisper` and re-run.")
        return

    model = WhisperModel("large-v3", device="cuda", compute_type="float16")
    lines = []
    wlang = {"zh": "zh", "en": "en"}.get(lang, "zh")
    for w in wavs:
        segments, _ = model.transcribe(w, language=wlang)
        text = "".join(s.text for s in segments).strip()
        if text:
            lines.append(f"{w}|{kol}|{wlang.upper()}|{text}")
    listf = f"{out_dir}/{kol}.list"
    open(listf, "w").write("\n".join(lines))
    print(f"Wrote {len(lines)} transcribed lines -> {listf}")
    print("Next: load this .list in the GPT-SoVITS WebUI and fine-tune SoVITS + GPT.")

if __name__ == "__main__":
    main()
