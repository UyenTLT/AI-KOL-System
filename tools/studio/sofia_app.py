#!/usr/bin/env python3
"""One box. Type, press Speak, hear Sofia. A desktop window, not a web page.

Every browser-served version of this — the dashboard, the voice lab, the plain-HTML studio,
the Sofia page — reaches the browser on this machine and then fails to display. The server
logs show the requests arriving and even the follow-up favicon fetch, so the HTML is being
parsed; it simply never appears. Rather than keep rebuilding pages against that, this skips
the browser entirely: Tk ships with Python, opens a native window, and plays the audio itself
through winsound.

    .venv\\Scripts\\python.exe tools\\studio\\sofia_app.py

Needs tools/voice_eval/cosy_server.py on :9881, which is where her voice lives. The window says
so plainly if it is not answering, instead of quietly falling back to her older, flatter voice.
"""
from __future__ import annotations

import json
import sys
import threading
import time
import traceback
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools" / "studio"))
sys.path.insert(0, str(REPO / "tools" / "livetalking"))

KOL = "sofia-hsu"
CLIPS = REPO / "renders" / "sofia"
CLIPS.mkdir(parents=True, exist_ok=True)

BG, CARD, INK, MUTED, RULE, ACCENT = "#EFF2F2", "#FFFFFF", "#111719", "#5A6A6C", "#D2DADA", "#0E6E68"
BAD, OK = "#B04352", "#3C7F55"


def voice_cfg() -> dict:
    try:
        prof = json.loads((REPO / "kols" / KOL / "profile.json").read_text(encoding="utf-8"))
        return (prof.get("ai_assets") or {}).get("voice") or {}
    except Exception:
        return {}


def engine_up(api: str) -> bool:
    try:
        urllib.request.urlopen(f"{api}/health", timeout=2)
        return True
    except Exception:
        return False


def play(path: Path) -> None:
    """Play the clip without opening anything else.

    winsound is part of the Windows Python install and plays a wav straight from the file, so
    there is no media player window to manage and no dependency to install. Asynchronous so
    the window stays responsive; falls back to the shell association elsewhere."""
    try:
        import winsound
        winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)
    except Exception:
        import os
        try:
            os.startfile(str(path))  # noqa: S606
        except Exception:
            pass


def main() -> int:
    import tkinter as tk
    from tkinter import font as tkfont

    cfg = voice_cfg()
    api = cfg.get("api", "http://127.0.0.1:9881")

    root = tk.Tk()
    root.title("Sofia — text to speech")
    root.configure(bg=BG)
    root.geometry("640x460")
    root.minsize(520, 400)

    serif = tkfont.Font(family="Cambria", size=22, weight="bold")
    body = tkfont.Font(family="Segoe UI", size=11)
    big = tkfont.Font(family="Segoe UI", size=13)
    mono = tkfont.Font(family="Consolas", size=9)

    wrap = tk.Frame(root, bg=BG)
    wrap.pack(fill="both", expand=True, padx=22, pady=(18, 16))

    tk.Label(wrap, text="Sofia Vargas", font=serif, bg=BG, fg=INK, anchor="w").pack(fill="x")
    tk.Label(wrap, text="Write a line. She says it back.", font=body, bg=BG, fg=MUTED,
             anchor="w").pack(fill="x", pady=(0, 12))

    box = tk.Text(wrap, height=6, font=big, bg=CARD, fg=INK, relief="flat",
                  highlightthickness=1, highlightbackground=RULE, highlightcolor=ACCENT,
                  wrap="word", padx=12, pady=10, insertbackground=INK)
    box.pack(fill="both", expand=True)
    box.insert("1.0", "Honestly, this is my favourite thing I have tried all month.")
    box.focus_set()

    row = tk.Frame(wrap, bg=BG)
    row.pack(fill="x", pady=(12, 0))

    speed = tk.StringVar(value="1.0")
    tk.Label(row, text="Pace", font=mono, bg=BG, fg=MUTED).pack(side="left")
    for label, val in (("slower", "0.85"), ("normal", "1.0"), ("quicker", "1.15")):
        tk.Radiobutton(row, text=label, value=val, variable=speed, font=body, bg=BG, fg=INK,
                       selectcolor=CARD, activebackground=BG, highlightthickness=0
                       ).pack(side="left", padx=(6, 0))

    btn = tk.Button(row, text="Speak", font=big, bg=ACCENT, fg="white", relief="flat",
                    padx=26, pady=6, cursor="hand2", activebackground="#0b5b56",
                    activeforeground="white")
    btn.pack(side="right")

    status = tk.Label(wrap, text="", font=mono, bg=BG, fg=MUTED, anchor="w", justify="left")
    status.pack(fill="x", pady=(12, 0))

    where = tk.Label(wrap, text=f"clips: {CLIPS}", font=mono, bg=BG, fg="#8A9899", anchor="w")
    where.pack(fill="x", pady=(4, 0))

    def set_status(msg: str, colour: str = MUTED) -> None:
        status.config(text=msg, fg=colour)

    def check_engine() -> None:
        if engine_up(api):
            set_status(f"ready · {cfg.get('engine','?')} {cfg.get('mode','')} "
                       f"· {cfg.get('target_lufs','?')} LUFS", OK)
        else:
            set_status(f"engine not answering on {api}\n"
                       f"start: CosyVoice\\.venv\\Scripts\\python.exe "
                       f"tools\\voice_eval\\cosy_server.py", BAD)

    def worker(text: str, spd: float) -> None:
        try:
            from voice_studio import synthesize
            name = f"{datetime.now():%H%M%S}-{uuid.uuid4().hex[:4]}.wav"
            started = time.perf_counter()
            out = CLIPS / name
            synthesize(KOL, text, out=out, speed=spd)
            out.with_suffix(".txt").write_text(text, encoding="utf-8")
            took = time.perf_counter() - started
            kb = out.stat().st_size / 1024
            root.after(0, lambda: (set_status(f"{took:.1f}s · {kb:.0f} KB · {out}", OK),
                                   play(out)))
        except Exception as exc:
            msg = f"{type(exc).__name__}: {exc}"
            print(traceback.format_exc(), file=sys.stderr)
            root.after(0, lambda: set_status(msg, BAD))
        finally:
            root.after(0, lambda: btn.config(state="normal", text="Speak"))

    def speak(_event=None) -> str:
        text = box.get("1.0", "end").strip()
        if not text:
            set_status("write something first", BAD)
            return "break"
        btn.config(state="disabled", text="speaking…")
        set_status("synthesising…")
        # Off the UI thread, or the window freezes for the two seconds it takes.
        threading.Thread(target=worker, args=(text, float(speed.get())), daemon=True).start()
        return "break"

    btn.config(command=speak)
    root.bind("<Control-Return>", speak)
    box.bind("<Control-Return>", speak)

    check_engine()
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
