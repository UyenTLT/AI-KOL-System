#!/usr/bin/env python3
"""Clean the room noise out of a voice reference clip without losing the speaker.

CosyVoice clones everything it hears in the prompt, background included. Sofia's reference is
a real recording at ~16 dB SNR, so every line she speaks carries that room with it. The fix
belongs on the reference, not on the output: clean the prompt once and every future render is
clean, rather than denoising each clip afterwards and smearing the speech.

The risk is the obvious one — denoise too hard and the voice goes hollow and metallic, which is
worse than the hiss. So this does not pick a setting by ear or by default; it renders several
strengths and scores each on three axes that pull against each other:

  * **noise floor** — how much of the hiss actually went
  * **speaker similarity** — ERes2NetV2 (already on disk for GPT-SoVITS v2Pro) against the
    original, so identity loss is measured rather than assumed
  * **intelligibility** — an ASR round-trip, because artefacts show up as wrong words before
    they show up in any spectral number

A setting only wins if it clears the noise *and* keeps similarity high. The strongest denoise
is rarely the best one.

    .venv\\Scripts\\python.exe tools\\voice_eval\\denoise_ref.py kols/sofia-hsu/voice/ref_human.wav
    .venv\\Scripts\\python.exe tools\\voice_eval\\denoise_ref.py <in.wav> --apply --out <out.wav>
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools" / "studio"))

# Candidates are built around what the noise on THIS recording actually is, which took a
# measurement to find out. In the quietest frames of the reference, 0-200 Hz sits ~39 dB above
# 8-16 kHz: the problem is low-frequency rumble — room, air conditioning, handling — not the
# broadband hiss that spectral denoisers like `afftdn` are built for. Tuning afftdn against it
# moved the noise by 0.2 dB.
#
# A female speaker's fundamental is around 180-220 Hz, so everything below ~100 Hz can go
# without touching the voice. That is what these mostly do; afftdn is kept only as a light
# second stage for whatever broadband component remains.
CANDIDATES = [
    ("hpf70",     "highpass=f=70:poles=2"),
    ("hpf85",     "highpass=f=85:poles=2"),
    ("hpf100",    "highpass=f=100:poles=2"),
    ("hpf100x4",  "highpass=f=100:poles=2,highpass=f=100:poles=2"),
    ("hpf120",    "highpass=f=120:poles=2"),
    ("hpf100+dn", "highpass=f=100:poles=2,highpass=f=100:poles=2,afftdn=nr=8:nf=-40:tn=1"),
    ("hpf85+dn",  "highpass=f=85:poles=2,highpass=f=85:poles=2,afftdn=nr=6:nf=-40:tn=1"),
]


def snr_db(path: Path) -> tuple[float, float]:
    """Rumble level and voice level, as energy in two frequency bands.

    The obvious approach — take the quietest frames as the noise floor — does not work on this
    material. Measured on the reference: **zero** of its 325 frames fall below -55 dB, because
    it is continuous speech with no true silence anywhere. The 5th percentile was therefore
    reporting the quietest *speech*, and a filter that removed real hiss barely moved it.

    Bands instead, over the quietest tenth of frames. On this recording the noise is *low*:
    below 200 Hz it sits about 39 dB above the 8-16 kHz band, so the first version of this
    function — which measured 8-15 kHz on the assumption of hiss — was watching an empty part
    of the spectrum and reported that every filter did nothing. Returning the voice band too
    matters: a filter that dulls the voice shows up as both numbers falling together, which a
    single figure would hide.
    """
    y, sr = sf.read(str(path), dtype="float32", always_2d=False)
    if y.ndim > 1:
        y = y.mean(1)
    n = 1024
    frames = y[: len(y) // n * n].reshape(-1, n) * np.hanning(n)
    # Only the quietest tenth of frames — that is where the noise floor is audible, and this
    # clip has no true silence at all to sample instead.
    energy = (frames ** 2).mean(1)
    quiet = frames[energy <= np.percentile(energy, 10)]
    spec = np.abs(np.fft.rfft(quiet, axis=1))
    freq = np.fft.rfftfreq(n, 1 / sr)
    rumble = spec[:, freq < 200].mean()
    full = np.abs(np.fft.rfft(frames, axis=1))
    voice = full[:, (freq >= 200) & (freq <= 3500)].mean()
    return float(20 * np.log10(rumble + 1e-12)), float(20 * np.log10(voice + 1e-12))


PAD = 0.6      # seconds of head padding, see apply_filter


def apply_filter(src: Path, dst: Path, chain: str) -> None:
    """Run the filter chain with a padded head, then trim the padding back off.

    `afftdn` with `tn=1` learns its noise profile from the start of the stream and treats
    those first samples as noise. On a clip that opens on speech that eats the opening words —
    measured: every candidate dropped "and paper" from the transcript before this. Prepending
    silence gives the tracker something to learn from that is genuinely noise, and `atrim`
    removes it afterwards so the returned clip is the same length as the input.
    """
    chained = f"adelay={int(PAD*1000)}|{int(PAD*1000)},{chain},atrim=start={PAD},asetpts=PTS-STARTPTS"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-af", chained,
                    "-ar", "32000", "-ac", "1", str(dst)], check=True)


def speaker_similarity(a: Path, b: Path) -> float | None:
    """Cosine similarity from ERes2NetV2 — the model GPT-SoVITS already ships for v2Pro.

    Hand-rolled proxies were tried on this project and did not work: pitch put two different
    speakers 5 Hz apart and MFCC cosine saturated above 0.997. The domain model separated the
    same pair by 0.165. Returns None if it cannot be loaded rather than falling back to a
    metric that would mislead.
    """
    gsv = REPO / "GPT-SoVITS"
    ckpt = gsv / "GPT_SoVITS/pretrained_models/sv/pretrained_eres2netv2w24s4ep4.ckpt"
    if not ckpt.is_file():
        return None
    # Load it exactly the way GPT_SoVITS/sv.py does. Its ERes2NetV2.py uses flat imports
    # (`import pooling_layers`), so the eres2net directory itself has to be on sys.path —
    # importing it as a package raises ModuleNotFoundError and the similarity check silently
    # reports "n/a", which is how a denoise setting could get chosen without any identity
    # evidence at all. Feature extraction and `forward3` are copied from sv.py rather than
    # reinvented, so the numbers are comparable to the project's existing 0.919 baseline.
    code = f'''
import sys, torch, torchaudio
sys.path.insert(0, r"{gsv / "GPT_SoVITS" / "eres2net"}")
from ERes2NetV2 import ERes2NetV2
import kaldi as Kaldi
import soundfile as sf
m = ERes2NetV2(baseWidth=24, scale=4, expansion=4)
m.load_state_dict(torch.load(r"{ckpt}", map_location="cpu", weights_only=False))
m.eval()
def emb(p):
    y, sr = sf.read(p, dtype="float32", always_2d=False)
    if y.ndim > 1: y = y.mean(1)
    t = torch.from_numpy(y)[None]
    if sr != 16000:
        t = torchaudio.transforms.Resample(sr, 16000)(t)
    feat = torch.stack([Kaldi.fbank(w.unsqueeze(0), num_mel_bins=80,
                                    sample_frequency=16000, dither=0) for w in t])
    with torch.no_grad():
        return m.forward3(feat).squeeze(0)
a, b = emb(r"{a}"), emb(r"{b}")
print(float(torch.nn.functional.cosine_similarity(a.flatten()[None], b.flatten()[None])[0]))
'''
    py = gsv / ".venv" / "Scripts" / "python.exe"
    if not py.is_file():
        return None
    try:
        out = subprocess.run([str(py), "-c", code], capture_output=True, text=True, timeout=300)
        for line in reversed(out.stdout.strip().splitlines()):
            try:
                return float(line)
            except ValueError:
                continue
    except Exception:
        return None
    return None


def transcribe(path: Path) -> str:
    try:
        from voice_studio import transcribe as tr
        return tr(path, "en")[0]
    except Exception as exc:
        return f"(ASR unavailable: {type(exc).__name__})"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("src")
    ap.add_argument("--apply", metavar="NAME", default=None,
                    help="write the named candidate to --out instead of only reporting")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    src = Path(args.src)
    if not src.is_file():
        raise SystemExit(f"no such file: {src}")

    tmp = Path(tempfile.mkdtemp(prefix="denoise-"))
    hiss0, voice0 = snr_db(src)
    print(f"\noriginal  hiss {hiss0:6.1f} dB   voice {voice0:6.1f} dB   "
          f"separation {voice0-hiss0:5.1f} dB")
    print(f"          {transcribe(src)[:90]}\n")
    print(f"{'candidate':11} {'rumble':>8} {'voice':>8} {'rumble cut':>11} {'voice lost':>11} "
          f"{'sim':>8}   transcript")
    print("-" * 104)

    results = []
    for name, chain in CANDIDATES:
        dst = tmp / f"{name}.wav"
        try:
            apply_filter(src, dst, chain)
        except subprocess.CalledProcessError:
            print(f"{name:11}  (ffmpeg rejected: {chain})")
            continue
        hiss, voice = snr_db(dst)
        sim = speaker_similarity(src, dst)
        heard = transcribe(dst)
        results.append({"name": name, "chain": chain, "path": dst, "hiss": hiss,
                        "voice": voice, "gain": hiss0 - hiss, "voice_lost": voice0 - voice,
                        "sim": sim, "heard": heard})
        sims = f"{sim:.4f}" if sim is not None else "n/a"
        print(f"{name:11} {hiss:7.1f}dB {voice:7.1f}dB {hiss0-hiss:8.1f}dB {voice0-voice:10.1f}dB "
              f"{sims:>8}   {heard[:36]}")

    if results:
        # Keep the speaker and do not dull the voice while doing it. 0.95 is deliberately
        # strict: this project's own baseline for "same speaker, different line" is 0.919, so
        # anything at or above 0.95 is comfortably inside identity. The voice-band limit
        # matters just as much — a filter that quietens everything equally has not removed
        # noise, it has only turned the clip down.
        safe = [r for r in results
                if (r["sim"] is None or r["sim"] >= 0.95) and r["voice_lost"] <= 1.0]
        best = max(safe or results, key=lambda r: r["gain"])
        print(f"\nbest by measurement: {best['name']}  "
              f"({best['gain']:.1f} dB quieter, similarity "
              f"{best['sim']:.4f})" if best["sim"] is not None else f"\nbest: {best['name']}")
        print(f"  chain: {best['chain']}")
        if not safe:
            print("  WARNING: no candidate kept similarity >= 0.95 — listen before applying.")

    if args.apply:
        chosen = next((r for r in results if r["name"] == args.apply), None)
        if not chosen:
            raise SystemExit(f"no candidate named {args.apply!r}")
        out = Path(args.out or src)
        if out == src:
            backup = src.with_suffix(src.suffix + ".orig")
            if not backup.exists():
                backup.write_bytes(src.read_bytes())
                print(f"\noriginal kept at {backup.name}")
        out.write_bytes(chosen["path"].read_bytes())
        print(f"wrote {out}  ({chosen['name']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
