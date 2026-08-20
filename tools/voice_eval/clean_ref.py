#!/usr/bin/env python3
"""Isolate the voice from a reference recording and bring it to a normal listening level.

Two problems, two different tools, and conflating them wastes time — which is how the first
attempt at this went.

**The room.** A high-pass removes what sits *below* the voice; it cannot remove what overlaps
it. Measured on Sofia's reference, filtering took 5.5 dB off the sub-200 Hz rumble and left the
rest. Demucs is a learned source separator: it pulls the voice out as a stem and leaves the
room behind, taking 22.8 dB instead. It is trained on music rather than speech, so the result
is checked rather than trusted.

**The level.** Separation does not make anything louder, and the recording is quiet in absolute
terms: -34 LUFS against the -16 LUFS that is normal for speech. That is roughly 18 dB of
missing loudness, and no amount of denoising addresses it. `loudnorm` does, with a true-peak
ceiling so nothing clips.

Order matters. Normalise first and you amplify the room along with the voice, then ask the
separator to work on a louder mess. Separate first, then normalise what is left.

    .venv\\Scripts\\python.exe tools\\voice_eval\\clean_ref.py kols/sofia-hsu/voice/ref_human.wav.orig
    .venv\\Scripts\\python.exe tools\\voice_eval\\clean_ref.py <in> --apply --out <out>
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools" / "voice_eval"))
sys.path.insert(0, str(REPO / "tools" / "studio"))

# -16 LUFS is the usual target for spoken-word content; -1.5 dBTP leaves headroom so that
# whatever encodes this later cannot clip on an intersample peak.
TARGET_LUFS = -16.0
TRUE_PEAK = -1.5


def loudness(path: Path) -> tuple[float | None, float | None]:
    """Integrated loudness (LUFS) and peak (dBFS)."""
    out = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
                          "-af", "ebur128=framelog=quiet", "-f", "null", "-"],
                         capture_output=True, text=True)
    m = re.search(r"I:\s*(-?\d+\.?\d*)\s*LUFS", out.stderr)
    out2 = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
                           "-af", "volumedetect", "-f", "null", "-"],
                          capture_output=True, text=True)
    p = re.search(r"max_volume:\s*(-?\d+\.?\d*)\s*dB", out2.stderr)
    return (float(m.group(1)) if m else None), (float(p.group(1)) if p else None)


def separate(src: Path, workdir: Path) -> Path:
    """Pull the voice out as its own stem with Demucs.

    NOT the right tool for preparing a CosyVoice reference clip, on this project's own
    measurements — see sofia-hsu' profile, reference_cleanup. Demucs wins on rumble by a wide
    margin (19.6 dB against 5.5 dB for a plain high-pass) and loses on the two things that turned
    out to matter more: its artefacts raise high-frequency noise, and a render cloned from the
    separated stem scores 0.4968 against the original speaker where the high-passed one scores
    0.6320. The separation is doing real work; it is just work that damages the voice it is
    meant to preserve.

    Kept because it is the right tool elsewhere — pulling a vocal out of a finished song for
    voice conversion is exactly what it is for, and `livestream/songs.py` uses it for that.
    """
    subprocess.run([sys.executable, "-m", "demucs", "--two-stems=vocals", "-n", "htdemucs",
                    "-o", str(workdir), "--filename", "{stem}.{ext}", str(src)],
                   check=True, capture_output=True, text=True)
    vocals = workdir / "htdemucs" / "vocals.wav"
    if not vocals.is_file():
        raise RuntimeError("demucs produced no vocals stem")
    return vocals


def normalise(src: Path, dst: Path, lufs: float = TARGET_LUFS, sr: int = 32000) -> None:
    """Two-pass loudnorm. One pass guesses; two measures then corrects, which matters on a clip
    this short where a single pass can overshoot badly."""
    probe = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(src),
         "-af", f"loudnorm=I={lufs}:TP={TRUE_PEAK}:LRA=11:print_format=json",
         "-f", "null", "-"], capture_output=True, text=True)
    stats = {}
    for key in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset"):
        m = re.search(rf'"{key}"\s*:\s*"(-?[\d.]+|-?inf)"', probe.stderr)
        if m and m.group(1) not in ("-inf", "inf"):
            stats[key] = m.group(1)
    if len(stats) == 5:
        af = (f"loudnorm=I={lufs}:TP={TRUE_PEAK}:LRA=11"
              f":measured_I={stats['input_i']}:measured_TP={stats['input_tp']}"
              f":measured_LRA={stats['input_lra']}:measured_thresh={stats['input_thresh']}"
              f":offset={stats['target_offset']}:linear=true")
    else:
        af = f"loudnorm=I={lufs}:TP={TRUE_PEAK}:LRA=11"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-af", af,
                    "-ar", str(sr), "-ac", "1", str(dst)], check=True)


def report(label: str, path: Path) -> None:
    import denoise_ref as D
    rumble, voice = D.snr_db(path)
    lufs, peak = loudness(path)
    lufs_s = f"{lufs:6.1f}" if lufs is not None else "     ?"
    peak_s = f"{peak:6.1f}" if peak is not None else "     ?"
    print(f"  {label:26} rumble {rumble:7.1f}dB  voice {voice:7.1f}dB  "
          f"{lufs_s} LUFS  peak {peak_s} dB")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("src")
    ap.add_argument("--lufs", type=float, default=TARGET_LUFS)
    ap.add_argument("--apply", action="store_true", help="write the result to --out")
    ap.add_argument("--out", default=None)
    ap.add_argument("--keep", default=None, help="directory to keep the intermediates in")
    args = ap.parse_args()

    src = Path(args.src)
    if not src.is_file():
        raise SystemExit(f"no such file: {src}")
    work = Path(args.keep) if args.keep else Path(tempfile.mkdtemp(prefix="clean-"))
    work.mkdir(parents=True, exist_ok=True)

    import denoise_ref as D
    print()
    report("original", src)

    print("  separating the voice (demucs htdemucs)...")
    vocals = separate(src, work)
    report("after separation", vocals)

    final = work / "clean.wav"
    normalise(vocals, final, args.lufs)
    report(f"after loudnorm ({args.lufs:.0f} LUFS)", final)

    sim = D.speaker_similarity(src, final)
    heard = D.transcribe(final)
    print()
    if sim is not None:
        print(f"  speaker similarity vs original: {sim:.4f}")
        print(f"    Read this against what changed, not against the 0.919 same-speaker")
        print(f"    baseline alone: the embedding sees the whole signal, and removing 20+ dB")
        print(f"    of room is itself a large change. The check that settles it is whether a")
        print(f"    render from this reference still sounds like her.")
    print(f"  transcript: {heard[:88]}")

    if args.apply:
        out = Path(args.out or src)
        if out.suffix != ".wav":
            raise SystemExit("--out must be a .wav")
        if out.exists() and not out.name.endswith(".orig"):
            backup = out.with_suffix(out.suffix + ".prev")
            backup.write_bytes(out.read_bytes())
            print(f"  previous kept at {backup.name}")
        out.write_bytes(final.read_bytes())
        print(f"  wrote {out}")
    else:
        print(f"\n  intermediates in {work}")
        print(f"  add --apply --out <file> to write it")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
