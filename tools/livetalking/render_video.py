#!/usr/bin/env python3
"""Render a finished lip-synced mp4 from a KOL's avatar and a line of text.

LiveTalking is built for realtime: it streams frames over WebRTC to a connected browser, and
its only recording path needs a live session. That is the wrong shape when you want a file —
to review a take, to send it to someone, or, as here, when the browser on this machine cannot
play media at all.

So this drives the same pieces offline. Nothing is reimplemented: the avatar directory, the
wav2lip checkpoint, the mel front end and the paste-back geometry are all LiveTalking's, loaded
the way `avatars/wav2lip_avatar.py` loads them. The only thing added is a batch loop that walks
the whole utterance instead of a queue that keeps up with a clock.

Audio comes from the character's configured voice, so the file matches what the avatar would
have said live — CosyVoice 2 for sofia-hsu, GPT-SoVITS for the rest.

    LiveTalking\\.venv\\Scripts\\python.exe tools\\livetalking\\render_video.py sofia-hsu ^
        --text "Okay so, I honestly did not expect this to work." ^
        --avatar-id sofia-hsu_v2 --out renders/sofia_talking.mp4

    ... --audio some.wav        # speak an existing clip instead of synthesising
"""
from __future__ import annotations

import argparse
import glob
import os
import pickle
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LT = REPO / "LiveTalking"
sys.path.insert(0, str(LT))
sys.path.insert(0, str(REPO / "tools" / "studio"))

FACE_SIZE = 256
FPS = 25


def mirror_index(size: int, index: int) -> int:
    """Ping-pong through the frames, the same way LiveTalking does.

    The avatar is a short loop, so a long utterance runs off the end of it. Walking forwards
    then backwards keeps every step continuous; wrapping around would put a visible jump at
    each cycle boundary.
    """
    turn = index // size
    res = index % size
    return res if turn % 2 == 0 else size - res - 1


def load_avatar(avatar_id: str):
    base = LT / "data" / "avatars" / avatar_id
    if not base.is_dir():
        raise SystemExit(f"no such avatar: {base}")
    from avatars.wav2lip_avatar import read_imgs
    with open(base / "coords.pkl", "rb") as fh:
        coords = pickle.load(fh)
    def sorted_imgs(sub):
        files = glob.glob(os.path.join(str(base / sub), "*.[jpJP][pnPN]*[gG]"))
        return read_imgs(sorted(files, key=lambda p: int(Path(p).stem)))
    return sorted_imgs("full_imgs"), sorted_imgs("face_imgs"), coords


def synth_audio(kol: str, text: str, dst: Path) -> Path:
    """Speak the line with whatever engine the character's profile names."""
    from voice_studio import synthesize
    synthesize(kol, text, out=dst)
    return dst


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("kol_id")
    ap.add_argument("--text", default=None)
    ap.add_argument("--audio", default=None, help="use this wav instead of synthesising")
    ap.add_argument("--avatar-id", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--batch-size", type=int, default=8)
    args = ap.parse_args()

    if not args.text and not args.audio:
        raise SystemExit("give --text or --audio")

    import cv2
    import numpy as np
    import torch
    from avatars.wav2lip_avatar import load_model
    from avatars.wav2lip import audio as w2l_audio

    avatar_id = args.avatar_id or f"{args.kol_id}_v1"
    out = Path(args.out or (REPO / "renders" / f"{args.kol_id}_{int(time.time())}.mp4"))
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="render-"))

    # --- audio -------------------------------------------------------------------
    if args.audio:
        wav_src = Path(args.audio)
    else:
        print(f"[1/4] speaking: {args.text[:70]}")
        wav_src = synth_audio(args.kol_id, args.text, tmp / "speech.wav")
    # wav2lip's mel front end expects 16 kHz mono; resample rather than assume.
    wav16 = tmp / "speech16.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(wav_src),
                    "-ar", "16000", "-ac", "1", str(wav16)], check=True)

    wav = w2l_audio.load_wav(str(wav16), 16000)
    mel = w2l_audio.melspectrogram(wav)
    if np.isnan(mel.reshape(-1)).sum() > 0:
        raise SystemExit("mel contains NaN — is the audio silent?")

    # 80 mel steps per second of audio; wav2lip reads a 16-step window per video frame.
    mel_step = 16
    mel_idx_multiplier = 80.0 / FPS
    mel_chunks, i = [], 0
    while True:
        start = int(i * mel_idx_multiplier)
        if start + mel_step > mel.shape[1]:
            mel_chunks.append(mel[:, mel.shape[1] - mel_step:])
            break
        mel_chunks.append(mel[:, start:start + mel_step])
        i += 1
    n_frames = len(mel_chunks)
    print(f"[2/4] {n_frames} frames at {FPS} fps = {n_frames/FPS:.1f}s")

    # --- avatar + model ----------------------------------------------------------
    frames, faces, coords = load_avatar(avatar_id)
    print(f"[3/4] avatar {avatar_id}: {len(frames)} frames")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = load_model(str(LT / "models" / "wav2lip.pth"))

    h, w = frames[0].shape[:2]
    silent = tmp / "silent.mp4"
    writer = cv2.VideoWriter(str(silent), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (w, h))

    started = time.perf_counter()
    with torch.no_grad():
        for base in range(0, n_frames, args.batch_size):
            chunk = mel_chunks[base: base + args.batch_size]
            idxs = [mirror_index(len(faces), base + k) for k in range(len(chunk))]
            img_batch = np.asarray([faces[j] for j in idxs])
            mel_batch = np.asarray(chunk)

            masked = img_batch.copy()
            masked[:, FACE_SIZE // 2:] = 0                      # hide the mouth half
            img_in = np.concatenate((masked, img_batch), axis=3) / 255.0
            mel_in = mel_batch.reshape(len(mel_batch), mel_batch.shape[1], mel_batch.shape[2], 1)

            img_t = torch.FloatTensor(np.transpose(img_in, (0, 3, 1, 2))).to(device)
            mel_t = torch.FloatTensor(np.transpose(mel_in, (0, 3, 1, 2))).to(device)
            pred = model(mel_t, img_t)
            pred = pred.cpu().numpy().transpose(0, 2, 3, 1) * 255.0

            for k, face in enumerate(pred):
                j = idxs[k]
                frame = frames[j].copy()
                y1, y2, x1, x2 = coords[j]
                frame[y1:y2, x1:x2] = cv2.resize(face.astype(np.uint8), (x2 - x1, y2 - y1))
                writer.write(frame)
    writer.release()
    took = time.perf_counter() - started
    print(f"      rendered in {took:.1f}s  ({n_frames/took:.1f} fps)")

    # --- mux ---------------------------------------------------------------------
    print(f"[4/4] muxing audio")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(silent), "-i", str(wav_src),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
                    "-c:a", "aac", "-b:a", "128k", "-shortest", str(out)], check=True)
    size = out.stat().st_size / 1e6
    print(f"\n  {out}  ({size:.1f} MB, {n_frames/FPS:.1f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
