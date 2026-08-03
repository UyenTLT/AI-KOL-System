#!/usr/bin/env python3
"""Build a LiveTalking wav2lip avatar from a KOL's portrait.

LiveTalking's avatar builder consumes a **video**, but the KOLs only have still
images. This bridges that gap: it turns a portrait into a base clip, then runs the
upstream generator to produce `full_imgs/ face_imgs/ coords.pkl`.

The base clip supplies the frames wav2lip paints a mouth onto, so its motion is what
makes the avatar look alive (or not):

    --motion static   one held frame. Head is frozen, only the mouth moves. Fast and
                      reliable — use it to prove the pipeline before investing in motion.
    --motion subtle   slow drift + breathing zoom, like a handheld camera. Reads as
                      alive without needing a video model. Default.
    --motion video    you supply a real clip with --video (skips generation entirely);
                      this is the path for LivePortrait / image-to-video output later.

Usage
    python tools/livetalking/build_avatar.py lena-chen
    python tools/livetalking/build_avatar.py lena-chen --motion static --seconds 6
    python tools/livetalking/build_avatar.py lena-chen --motion video --video clip.mp4

Run with the LiveTalking venv (it owns torch + the face detector):
    LiveTalking\\.venv\\Scripts\\python.exe tools\\livetalking\\build_avatar.py lena-chen
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LT = REPO / "LiveTalking"

# Match the stock wav2lip256 avatar so performance and VRAM behaviour are identical.
FRAME_W, FRAME_H = 576, 768
FACE_SIZE = 256
FPS = 25


def ffmpeg_bin(name: str = "ffmpeg") -> str:
    sys.path.insert(0, str(REPO / "tools" / "voice_crawl"))
    import ffmpeg_util
    return ffmpeg_util.resolve(name)


def pick_portrait(kol_id: str, explicit: str | None) -> Path:
    if explicit:
        p = Path(explicit)
        if not p.is_absolute():
            p = REPO / p
        if not p.is_file():
            raise SystemExit(f"image not found: {p}")
        return p
    img_dir = REPO / "kols" / kol_id / "images"
    cands = [p for p in img_dir.rglob("*") if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")]
    if not cands:
        raise SystemExit(f"no images under {img_dir} — pass --image explicitly")
    # Prefer something that looks like a frontal portrait; the face detector needs one.
    def score(p: Path) -> tuple:
        n = p.name.lower()
        return (("portrait" in n or "frontal" in n or "closeup" in n), p.stat().st_size)
    best = sorted(cands, key=score, reverse=True)[0]
    return best


def prepare_frame(src: Path, dst: Path) -> None:
    """Centre-crop to the avatar aspect ratio, then resize. Crop rather than squash:
    a stretched face makes the detector's landmarks (and the pasted mouth) wrong."""
    from PIL import Image

    im = Image.open(src).convert("RGB")
    target = FRAME_W / FRAME_H
    w, h = im.size
    if w / h > target:                     # too wide -> trim sides
        new_w = int(h * target)
        left = (w - new_w) // 2
        im = im.crop((left, 0, left + new_w, h))
    else:                                  # too tall -> trim from the bottom,
        new_h = int(w / target)            # keeping the head near the top
        top = int((h - new_h) * 0.15)
        im = im.crop((0, top, w, top + new_h))
    im = im.resize((FRAME_W, FRAME_H), Image.LANCZOS)
    dst.parent.mkdir(parents=True, exist_ok=True)
    im.save(dst, quality=96)


def render_static(frame: Path, out: Path, seconds: float) -> None:
    subprocess.run([ffmpeg_bin(), "-y", "-hide_banner", "-loglevel", "error",
                    "-loop", "1", "-i", str(frame), "-t", str(seconds),
                    "-r", str(FPS), "-pix_fmt", "yuv420p",
                    "-vf", f"scale={FRAME_W}:{FRAME_H}", str(out)], check=True)


def render_subtle(frame: Path, out: Path, seconds: float) -> None:
    """Slow drift + a breathing zoom, built from two out-of-phase sine waves.

    Rendered by generating frames in Python rather than with ffmpeg's zoompan, whose
    rounding jitters by a pixel and makes the face detector's box twitch between
    frames — which shows up as a shivering mouth in the final avatar.
    """
    from PIL import Image

    base = Image.open(frame).convert("RGB")
    n = int(seconds * FPS)
    work = out.parent / "_frames"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    # Zoom in slightly so there is room to move without exposing empty edges.
    pad = 0.06
    big = base.resize((int(FRAME_W * (1 + pad * 2)), int(FRAME_H * (1 + pad * 2))), Image.LANCZOS)
    max_dx = int(FRAME_W * pad)
    max_dy = int(FRAME_H * pad)

    for i in range(n):
        t = i / FPS
        dx = max_dx * (0.5 + 0.5 * math.sin(2 * math.pi * t / 11.0))
        dy = max_dy * (0.5 + 0.5 * math.sin(2 * math.pi * t / 7.0 + 1.1))
        # breathing scale, +-0.6%
        s = 1.0 + 0.006 * math.sin(2 * math.pi * t / 5.0)
        cw, ch = int(FRAME_W / s), int(FRAME_H / s)
        x = max(0, min(big.width - cw, int(dx)))
        y = max(0, min(big.height - ch, int(dy)))
        fr = big.crop((x, y, x + cw, y + ch)).resize((FRAME_W, FRAME_H), Image.LANCZOS)
        fr.save(work / f"{i:05d}.png")

    subprocess.run([ffmpeg_bin(), "-y", "-hide_banner", "-loglevel", "error",
                    "-r", str(FPS), "-i", str(work / "%05d.png"),
                    "-pix_fmt", "yuv420p", str(out)], check=True)
    shutil.rmtree(work, ignore_errors=True)


def run_genavatar(video: Path, avatar_id: str) -> Path:
    """Invoke LiveTalking's own generator so the output format stays authoritative."""
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(LT), env.get("PYTHONPATH", "")]).rstrip(os.pathsep)
    cmd = [sys.executable, "-m", "avatars.wav2lip.genavatar",
           "--video_path", str(video), "--avatar_id", avatar_id,
           "--img_size", str(FACE_SIZE), "--save_path", "data/avatars"]
    print(f"  $ {' '.join(cmd[1:])}")
    proc = subprocess.run(cmd, cwd=str(LT), env=env)
    if proc.returncode != 0:
        raise SystemExit(f"genavatar failed (exit {proc.returncode})")
    return LT / "data" / "avatars" / avatar_id


def verify(avatar_dir: Path, expect_frames: int) -> dict:
    """A built avatar is only usable if all three artefacts agree in length."""
    import pickle

    full = sorted((avatar_dir / "full_imgs").glob("*.png")) or \
        sorted((avatar_dir / "full_imgs").glob("*.jpg"))
    face = sorted((avatar_dir / "face_imgs").glob("*.png")) or \
        sorted((avatar_dir / "face_imgs").glob("*.jpg"))
    coords_path = avatar_dir / "coords.pkl"
    if not coords_path.is_file():
        raise SystemExit(f"no coords.pkl in {avatar_dir} — face detection produced nothing, "
                         f"which usually means no face was found in the base video")
    with open(coords_path, "rb") as fh:
        coords = pickle.load(fh)

    from PIL import Image
    info = {"full": len(full), "face": len(face), "coords": len(coords),
            "expected": expect_frames}
    if face:
        info["face_size"] = Image.open(face[0]).size
    if full:
        info["full_size"] = Image.open(full[0]).size

    if not (len(full) == len(face) == len(coords)):
        raise SystemExit(f"avatar is inconsistent: {info} — full_imgs, face_imgs and coords "
                         f"must all have the same count")
    if len(face) == 0:
        raise SystemExit("no faces were detected in the base video")
    if info.get("face_size") != (FACE_SIZE, FACE_SIZE):
        print(f"  ! warning: face crops are {info.get('face_size')}, expected "
              f"{(FACE_SIZE, FACE_SIZE)} — did you pass --img_size {FACE_SIZE}?")
    return info


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kol_id")
    ap.add_argument("--image", help="portrait to use (default: auto-pick from kols/<id>/images)")
    ap.add_argument("--video", help="use this clip as-is (--motion video)")
    ap.add_argument("--motion", default="subtle", choices=["static", "subtle", "video"])
    ap.add_argument("--seconds", type=float, default=8.0, help="base clip length")
    ap.add_argument("--avatar-id", default=None, help="default: <kol_id>_v1")
    ap.add_argument("--keep-video", action="store_true", help="keep the generated base clip")
    args = ap.parse_args()

    avatar_id = args.avatar_id or f"{args.kol_id}_v1"
    work = REPO / "kols" / args.kol_id / "avatar"
    work.mkdir(parents=True, exist_ok=True)
    base_video = work / f"base_{args.motion}.mp4"

    print(f"[avatar] kol={args.kol_id}  avatar_id={avatar_id}  motion={args.motion}")

    if args.motion == "video":
        if not args.video:
            raise SystemExit("--motion video requires --video <clip>")
        src = Path(args.video)
        if not src.is_absolute():
            src = REPO / src
        if not src.is_file():
            raise SystemExit(f"video not found: {src}")
        # Normalise fps and size. LiveTalking renders at FPS (25); a 30 fps source would
        # otherwise play back slightly slow-motion, and a different frame size changes the
        # avatar geometry from the rest of the pipeline.
        base_video = work / "base_video.mp4"
        print(f"  supplied clip: {src.name} -> normalising to {FRAME_W}x{FRAME_H} @ {FPS}fps")
        subprocess.run([ffmpeg_bin(), "-y", "-hide_banner", "-loglevel", "error",
                        "-i", str(src), "-r", str(FPS),
                        "-vf", f"scale={FRAME_W}:{FRAME_H}:force_original_aspect_ratio=increase,"
                               f"crop={FRAME_W}:{FRAME_H}",
                        "-an", "-pix_fmt", "yuv420p", str(base_video)], check=True)
        n_frames = None
    else:
        portrait = pick_portrait(args.kol_id, args.image)
        print(f"  portrait: {portrait.relative_to(REPO)}")
        frame = work / "frame.png"
        prepare_frame(portrait, frame)
        print(f"  prepared frame -> {FRAME_W}x{FRAME_H}")
        n_frames = int(args.seconds * FPS)
        print(f"  rendering {args.motion} base clip: {args.seconds}s @ {FPS}fps "
              f"({n_frames} frames)")
        (render_static if args.motion == "static" else render_subtle)(
            frame, base_video, args.seconds)

    print("  building avatar (face detection)...")
    avatar_dir = run_genavatar(base_video, avatar_id)
    info = verify(avatar_dir, n_frames or 0)

    print(f"\n{'='*66}")
    print(f"avatar   : {avatar_dir}")
    print(f"frames   : {info['full']} full / {info['face']} face / {info['coords']} coords")
    print(f"sizes    : full {info.get('full_size')}  face {info.get('face_size')}")
    if not args.keep_video and args.motion != "video" and base_video.exists():
        print(f"base clip: {base_video.relative_to(REPO)} (kept for inspection)")
    print("\nRun it:")
    print(f"  .\\tools\\livetalking\\run_livetalking.ps1 {args.kol_id} -AvatarId {avatar_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
