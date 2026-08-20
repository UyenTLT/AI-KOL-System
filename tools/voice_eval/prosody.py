"""Prosody comparison, v3 — corrects the octave-tracking error in v2.

v2 ran pyin with fmin=70. Both the human clip and output B have strong low-frequency
energy (vocal fry, plus room rumble in a phone recording), so the tracker locked an
octave low on many frames and inflated every pitch statistic derived from it. The v2
"12.6x delivery variety" figure was largely that artefact.

v3: high-pass at 80 Hz to drop rumble, fmin=110 so a female voice cannot be tracked an
octave down, and frames pinned to the floor are discarded as unreliable rather than
averaged in.
"""
import sys, subprocess, tempfile, random
from pathlib import Path
import numpy as np
import librosa
from scipy.signal import butter, sosfiltfilt

SR = 16000
FMIN, FMAX = 110.0, 450.0
random.seed(7)
_HP = butter(4, 80.0, btype="highpass", fs=SR, output="sos")


def load_any(path, sr=SR):
    p = Path(path)
    if p.suffix.lower() in (".wav", ".flac"):
        y = librosa.load(str(p), sr=sr, mono=True)[0]
    else:
        tmp = Path(tempfile.gettempdir()) / (p.stem + ".conv.wav")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(p), "-ar", str(sr),
                        "-ac", "1", str(tmp)], check=True)
        y = librosa.load(str(tmp), sr=sr, mono=True)[0]
    return sosfiltfilt(_HP, y).astype(np.float32)


def feats(y, sr=SR):
    y, _ = librosa.effects.trim(y, top_db=40)
    if len(y) < sr * 1.0:
        return None
    f0, _, _ = librosa.pyin(y, fmin=FMIN, fmax=FMAX, sr=sr,
                            frame_length=1024, hop_length=256)
    v = f0[~np.isnan(f0)]
    v = v[v > FMIN * 1.02]                 # frames pinned at the floor are unreliable
    if v.size < 20:
        return None
    st = 12 * np.log2(v / np.median(v))
    rms = librosa.feature.rms(y=y, frame_length=1024, hop_length=256)[0]
    db = 20 * np.log10(np.maximum(rms, 1e-6))
    db = db[db > db.max() - 45]
    hop_s = 256 / sr
    runs, cur = [], 0
    for q in np.isnan(f0):
        if q:
            cur += 1
        elif cur:
            runs.append(cur); cur = 0
    if cur:
        runs.append(cur)
    dur = len(y) / sr
    return {"dur": dur, "f0_med": float(np.median(v)),
            "f0_range_st": float(np.percentile(st, 95) - np.percentile(st, 5)),
            "db_sd": float(np.std(db)),
            "pause_rate": len([r for r in runs if r * hop_s >= 0.20]) / dur * 10.0}


def chunk(y, lo=4.0, hi=7.5, sr=SR):
    out = []
    for s, e in librosa.effects.split(y, top_db=28):
        seg = y[s:e]
        n = int(hi * sr)
        while len(seg) > n:
            out.append(seg[:n]); seg = seg[n:]
        if len(seg) >= lo * sr:
            out.append(seg)
    return out


def summarise(name, rows):
    if not rows:
        print(f"\n===== {name}: no usable audio"); return None
    g = {k: (float(np.mean([r[k] for r in rows])), float(np.std([r[k] for r in rows])))
         for k in ("dur", "f0_med", "f0_range_st", "db_sd", "pause_rate")}
    spread_st = 12 * np.log2(1 + g["f0_med"][1] / g["f0_med"][0])
    print(f"\n===== {name}   (n={len(rows)}, mean clip {g['dur'][0]:.1f} s)")
    print(f"  pitch range within a clip   {g['f0_range_st'][0]:6.2f} st")
    print(f"  loudness sd within a clip   {g['db_sd'][0]:6.2f} dB")
    print(f"  pauses per 10 s             {g['pause_rate'][0]:6.2f}")
    print(f"  median pitch                {g['f0_med'][0]:6.1f} Hz")
    print(f"  pitch spread clip-to-clip   {spread_st:6.2f} st   <- delivery variety")
    g["spread_st"] = (spread_st, 0.0)
    return g


def measure_files(paths):
    """Per-file mode: one line per clip. Used to compare individual renders."""
    print(f"{'clip':28} {'dur':>6} {'median':>9} {'range':>8} {'pauses/10s':>11}")
    for p in paths:
        r = feats(load_any(p))
        if not r:
            print(f"{Path(p).name:28}   too short / unvoiced")
            continue
        print(f"{Path(p).name:28} {r['dur']:5.1f}s {r['f0_med']:7.1f} Hz "
              f"{r['f0_range_st']:6.2f} st {r['pause_rate']:10.2f}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and all(a.lower().endswith((".wav", ".flac", ".mp3", ".m4a"))
                                 for a in sys.argv[1:]):
        measure_files(sys.argv[1:])
        raise SystemExit(0)

    repo = Path(sys.argv[1])
    N = int(sys.argv[2]) if len(sys.argv) > 2 else 45

    clips = sorted((repo / "kols/sofia-hsu/voice/dataset").glob("*.wav"))
    syn = [f for f in (feats(load_any(c)) for c in random.sample(clips, min(N, len(clips)))) if f]
    g_syn = summarise("SYNTHETIC bootstrap — what she is trained on", syn)

    raw = repo / "kols/sofia-hsu/voice/raw/kols_sofia-hsu_raw voice.m4a"
    g_real = None
    if raw.is_file():
        real = [f for f in (feats(c) for c in chunk(load_any(raw))) if f]
        g_real = summarise("REAL human, matched clip length — the target", real)

    if g_syn and g_real:
        print("\n===== VERDICT  (human vs synthetic, octave-safe)")
        for k, label in (("f0_range_st", "expressiveness (pitch range in a clip)"),
                         ("pause_rate",  "phrasing       (pauses per 10 s)"),
                         ("spread_st",   "delivery variety (clip-to-clip pitch)")):
            s, r = g_syn[k][0], g_real[k][0]
            print(f"  {label:40} synthetic {s:6.2f}   human {r:6.2f}   {r/s if s else 0:5.1f}x")
