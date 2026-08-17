#!/usr/bin/env python3
"""Type a line, hear it. A terminal front end for the voice, with no browser in the way.

The dashboard, the voice lab and the plain-HTML studio all serve the same features over HTTP,
and on this machine none of them could be opened in a browser. This needs no browser, no port
and no page: it reads from the terminal, synthesises, and hands the clip to the system player.

    .venv\\Scripts\\python.exe tools\\studio\\say.py                    # interactive
    .venv\\Scripts\\python.exe tools\\studio\\say.py "hello there"      # one line and exit
    .venv\\Scripts\\python.exe tools\\studio\\say.py --voice preset-zhtw "你好"
    .venv\\Scripts\\python.exe tools\\studio\\say.py --scenario "unboxing a sunscreen"

Interactive commands: `voice` to switch speaker, `speed 1.2`, `scenario <brief>`, `quit`.

Clips land in `renders/` at the repo root and the full path is printed after each one. That
matters here: the browser on this machine cannot play audio, so opening the file by hand in a
normal media player is the reliable way to hear it. Set KOL_RENDER_DIR to write elsewhere.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

import time
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools" / "studio"))
sys.path.insert(0, str(REPO / "tools" / "livetalking"))

# Written into the repo rather than a temp folder, because the clips are the point: on this
# machine the browser cannot play them, so the reliable way to hear one is to open the file in
# an ordinary media player. A path buried under AppData\Local\Temp is not that. Gitignored.
OUT = Path(os.getenv("KOL_RENDER_DIR") or (REPO / "renders"))
OUT.mkdir(parents=True, exist_ok=True)


def play(path: Path) -> None:
    """Hand the clip to whatever plays wav files here. Never fatal — the path is printed
    anyway, so a machine with no default player still leaves something to open."""
    try:
        if os.name == "nt":
            os.startfile(str(path))  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.run(["afplay", str(path)], check=False)
        else:
            subprocess.run(["xdg-open", str(path)], check=False)
    except Exception as exc:
        print(f"  (could not auto-play: {type(exc).__name__} — open the file yourself)")


def list_voices() -> list[dict]:
    from voice_studio import characters
    return characters()


def show_voices(voices: list[dict], current: str) -> None:
    print("\n  available voices:")
    for i, c in enumerate(voices, 1):
        mark = "*" if c.get("id") == current else " "
        print(f"   {mark}{i}. {c.get('id',''):18} {c.get('lang',''):24} {c.get('name','')}")
    print()


def speak(voice: str, text: str, speed: float) -> Path:
    from voice_studio import synthesize
    path = OUT / f"{voice}-{uuid.uuid4().hex[:6]}.wav"
    started = time.perf_counter()
    synthesize(voice, text, out=path, speed=speed)
    took = time.perf_counter() - started
    print(f"  [{took:.1f}s · {path.stat().st_size/1024:.0f} KB] {path}")
    return path


def write_and_speak(voice: str, brief: str, speed: float, seconds: int = 18) -> Path | None:
    from voice_studio import write_script
    print(f"  writing a ~{seconds}s script for {voice}…")
    started = time.perf_counter()
    try:
        script = write_script(voice, brief, seconds=seconds)
    except ValueError as exc:
        # The rule checker refused it. This is the system working, so say so clearly.
        print(f"  REFUSED after a retry: {exc}")
        return None
    print(f"  [{time.perf_counter()-started:.1f}s] {script}")
    return speak(voice, script, speed)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("text", nargs="*", help="say this and exit")
    ap.add_argument("--voice", default=None)
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--scenario", default=None, help="brief to write a script from")
    ap.add_argument("--seconds", type=int, default=18)
    ap.add_argument("--no-play", action="store_true")
    args = ap.parse_args()

    try:
        voices = list_voices()
    except Exception as exc:
        print(f"cannot reach GPT-SoVITS api_v2 on :9880 ({type(exc).__name__}: {exc})")
        print("start it:  GPT-SoVITS\\.venv\\Scripts\\python.exe api_v2.py "
              "-a 127.0.0.1 -p 9880 -c GPT_SoVITS/configs/tts_infer.yaml")
        return 1
    if not voices:
        print("no voices found — is api_v2 running on :9880?")
        return 1

    ids = [c.get("id") for c in voices]
    voice = args.voice or ids[0]
    if voice not in ids:
        print(f"unknown voice {voice!r}; have: {', '.join(ids)}")
        return 1
    speed = args.speed

    # one-shot modes
    if args.scenario:
        p = write_and_speak(voice, args.scenario, speed, args.seconds)
        if p and not args.no_play:
            play(p)
        return 0
    if args.text:
        p = speak(voice, " ".join(args.text), speed)
        if not args.no_play:
            play(p)
        return 0

    # interactive
    print("\nVoice Studio — terminal edition.  Type a line and press Enter to hear it.")
    print("Commands:  voice   speed 1.2   scenario <brief>   quit")
    show_voices(voices, voice)
    while True:
        try:
            line = input(f"[{voice} @{speed}x] > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue
        low = line.lower()
        if low in ("quit", "exit", "q"):
            return 0
        if low in ("voice", "voices"):
            show_voices(voices, voice)
            pick = input("  which (number or id)? ").strip()
            if pick.isdigit() and 1 <= int(pick) <= len(ids):
                voice = ids[int(pick) - 1]
            elif pick in ids:
                voice = pick
            else:
                print("  unchanged")
            continue
        if low.startswith("speed"):
            try:
                speed = float(line.split(maxsplit=1)[1])
                print(f"  speed {speed}x")
            except (IndexError, ValueError):
                print("  usage: speed 1.2")
            continue
        if low.startswith("scenario"):
            brief = line.split(maxsplit=1)[1] if " " in line else ""
            if not brief:
                print("  usage: scenario unboxing a new sunscreen")
                continue
            p = write_and_speak(voice, brief, speed, args.seconds)
            if p and not args.no_play:
                play(p)
            continue
        p = speak(voice, line, speed)
        if not args.no_play:
            play(p)


if __name__ == "__main__":
    raise SystemExit(main())
