#!/usr/bin/env python3
"""The whole studio in one window: voices, speech, video, scenarios, service health.

The web versions of this exist and are served on :8771-:8775. On this machine the browser
fetches them — the access logs show the page request and the follow-up favicon fetch, so the
HTML is parsed — and then nothing appears. A sixth page would very likely do the same, so this
is the same control surface built as a desktop window instead.

Tk and winsound ship with Python, so there is nothing to install and nothing to serve.

    .venv\\Scripts\\python.exe tools\\studio\\control_panel.py

Engines it talks to, each shown live in the status bar:
    :9880  GPT-SoVITS      the four fine-tuned voices
    :9881  CosyVoice 2     sofia-hsu
    :11434 Ollama          scenario writing
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import sys
import threading
import time
import traceback
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
for sub in ("studio", "livetalking", "voice_eval"):
    sys.path.insert(0, str(REPO / "tools" / sub))

CLIPS = REPO / "renders" / "studio"
CLIPS.mkdir(parents=True, exist_ok=True)
LT_PY = REPO / "LiveTalking" / ".venv" / "Scripts" / "python.exe"

BG, CARD, INK, MUTED, FAINT, RULE = "#EFF2F2", "#FFFFFF", "#111719", "#5A6A6C", "#8A9899", "#D2DADA"
ACCENT, OK, BAD, WARN = "#0E6E68", "#3C7F55", "#B04352", "#A0700F"

SERVICES = [("GPT-SoVITS", "http://127.0.0.1:9880/docs"),
            ("CosyVoice", "http://127.0.0.1:9881/health"),
            ("Ollama", "http://127.0.0.1:11434/api/tags"),
            ("LiveTalking", "http://127.0.0.1:8010/index.html")]


def up(url: str, timeout: float = 1.5) -> bool:
    try:
        urllib.request.urlopen(url, timeout=timeout)
        return True
    except Exception:
        return False


def characters() -> list[dict]:
    try:
        from voice_studio import characters as ch
        return ch()
    except Exception:
        return []


def avatars() -> list[str]:
    root = REPO / "LiveTalking" / "data" / "avatars"
    return sorted(d.name for d in root.iterdir() if d.is_dir()) if root.is_dir() else []


def play(path: Path) -> None:
    try:
        import winsound
        winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)
    except Exception:
        try:
            os.startfile(str(path))  # noqa: S606
        except Exception:
            pass


def main() -> int:
    import tkinter as tk
    from tkinter import font as tkfont, ttk

    root = tk.Tk()
    root.title("AI KOL Studio")
    root.configure(bg=BG)
    root.geometry("760x640")
    root.minsize(660, 560)

    serif = tkfont.Font(family="Cambria", size=20, weight="bold")
    body = tkfont.Font(family="Segoe UI", size=10)
    big = tkfont.Font(family="Segoe UI", size=12)
    mono = tkfont.Font(family="Consolas", size=9)
    lbl = tkfont.Font(family="Segoe UI", size=8, weight="bold")

    outer = tk.Frame(root, bg=BG)
    outer.pack(fill="both", expand=True, padx=18, pady=(14, 12))

    tk.Label(outer, text="AI KOL Studio", font=serif, bg=BG, fg=INK, anchor="w").pack(fill="x")

    # ---- service health ---------------------------------------------------------
    svc_row = tk.Frame(outer, bg=BG)
    svc_row.pack(fill="x", pady=(2, 12))
    svc_labels = {}
    for name, _ in SERVICES:
        f = tk.Frame(svc_row, bg=BG)
        f.pack(side="left", padx=(0, 16))
        dot = tk.Label(f, text="●", font=body, bg=BG, fg=FAINT)
        dot.pack(side="left")
        tk.Label(f, text=name, font=mono, bg=BG, fg=MUTED).pack(side="left", padx=(3, 0))
        svc_labels[name] = dot

    def refresh_services() -> None:
        def work():
            for name, url in SERVICES:
                alive = up(url)
                root.after(0, lambda d=svc_labels[name], a=alive: d.config(fg=OK if a else BAD))
        threading.Thread(target=work, daemon=True).start()

    # ---- voice + text -----------------------------------------------------------
    chars = characters()
    ids = [c["id"] for c in chars] or ["sofia-hsu"]
    names = {c["id"]: f"{c.get('name', c['id'])}  ·  {c.get('lang','')}" for c in chars}

    tk.Label(outer, text="VOICE", font=lbl, bg=BG, fg=FAINT, anchor="w").pack(fill="x")
    vrow = tk.Frame(outer, bg=BG)
    vrow.pack(fill="x", pady=(2, 10))
    voice = tk.StringVar(value=ids[0])
    vbox = ttk.Combobox(vrow, textvariable=voice, values=[names.get(i, i) for i in ids],
                        state="readonly", font=body)
    vbox.current(0)
    vbox.pack(side="left", fill="x", expand=True)

    # --- cloned voice -----------------------------------------------------------
    # A clip chosen here overrides the dropdown: whatever is typed gets spoken in that voice
    # instead. Zero-shot, no training, so it works on a file picked seconds ago.
    clone_ref: dict = {"path": None, "text": ""}

    clone_lbl = tk.Label(outer, text="", font=mono, bg=BG, fg=ACCENT, anchor="w",
                         wraplength=700, justify="left")

    def clear_clone() -> None:
        clone_ref.update(path=None, text="")
        clone_lbl.config(text="")
        clone_lbl.pack_forget()
        vbox.config(state="readonly")

    def pick_clone() -> None:
        from tkinter import filedialog
        p = filedialog.askopenfilename(
            title="Pick 5-15 seconds of the voice to clone",
            filetypes=[("Audio", "*.wav *.mp3 *.m4a *.flac *.ogg"), ("All files", "*.*")])
        if not p:
            return
        clone_lbl.pack(fill="x", pady=(0, 8))
        clone_lbl.config(text=f"{Path(p).name} — cleaning the clip…", fg=MUTED)
        vbox.config(state="disabled")

        def job():
            try:
                from voice_studio import transcribe
                import clean_ref as CR
                # Clean the uploaded clip before cloning from it. This is not cosmetic: cloning
                # the same speaker from a noisy reference scored 0.4474 against her production
                # voice, and from the cleaned version 0.8704 — nearly double, and the difference
                # between "sounds like someone else" and "sounds like her". Whoever picks a file
                # here will not have run it through a separator first.
                work = Path(tempfile.mkdtemp(prefix="clone-"))
                try:
                    vocals = CR.separate(Path(p), work)
                    cleaned = work / "clean.wav"
                    CR.normalise(vocals, cleaned, -16.0)
                    use = cleaned
                    note = "cleaned"
                except Exception:
                    use, note = Path(p), "as supplied — could not separate"
                clone_ref["path"] = str(use)
                root.after(0, lambda: clone_lbl.config(
                    text=f"{Path(p).name} ({note}) — transcribing…", fg=MUTED))

                # CosyVoice matches the prompt audio against the prompt text, so a wrong
                # transcript is the usual cause of a clone that sounds nothing like the source.
                # Typing it by hand is where that goes wrong, so it is filled in automatically.
                heard, _lang = transcribe(use, None)
                clone_ref["text"] = heard
                root.after(0, lambda: clone_lbl.config(
                    text=f"cloning {Path(p).name} ({note})  ·  heard: {heard[:60]}"
                         f"{'…' if len(heard) > 60 else ''}   [Clear to go back]", fg=ACCENT))
            except Exception as exc:
                root.after(0, lambda: clone_lbl.config(
                    text=f"could not use {Path(p).name}: {exc}", fg=BAD))
        threading.Thread(target=job, daemon=True).start()

    tk.Button(vrow, text="Clone a clip…", font=body, relief="flat", bg=CARD, fg=ACCENT,
              cursor="hand2", padx=10, command=pick_clone).pack(side="left", padx=(8, 0))
    tk.Button(vrow, text="Clear", font=body, relief="flat", bg=BG, fg=FAINT,
              cursor="hand2", command=clear_clone).pack(side="left", padx=(4, 0))

    tk.Label(outer, text="TEXT", font=lbl, bg=BG, fg=FAINT, anchor="w").pack(fill="x")
    box = tk.Text(outer, height=5, font=big, bg=CARD, fg=INK, relief="flat",
                  highlightthickness=1, highlightbackground=RULE, highlightcolor=ACCENT,
                  wrap="word", padx=11, pady=9, insertbackground=INK)
    box.pack(fill="both", expand=True, pady=(2, 8))
    box.insert("1.0", "Honestly, this is my favourite thing I have tried all month.")

    opts = tk.Frame(outer, bg=BG)
    opts.pack(fill="x")
    speed = tk.StringVar(value="1.0")
    tk.Label(opts, text="pace", font=mono, bg=BG, fg=FAINT).pack(side="left")
    for t, v in (("0.85", "0.85"), ("1.0", "1.0"), ("1.15", "1.15")):
        tk.Radiobutton(opts, text=t, value=v, variable=speed, font=body, bg=BG, fg=INK,
                       selectcolor=CARD, activebackground=BG, highlightthickness=0
                       ).pack(side="left", padx=(4, 0))
    # Which catalogue entry a selling script may quote from. Without one the guard treats every
    # price and link as invented and the script cannot state either — correct by default, and
    # exactly wrong when you actually have the product details in hand.
    def product_ids(k: str) -> list[str]:
        p = REPO / "kols" / k / "products.json"
        if not p.is_file():
            return []
        try:
            return [i.get("id", "") for i in json.loads(p.read_text(encoding="utf-8")).get("products", [])]
        except Exception:
            return []

    tk.Label(opts, text="   product", font=mono, bg=BG, fg=FAINT).pack(side="left", padx=(14, 0))
    prod = tk.StringVar(value="(none)")
    prod_box = ttk.Combobox(opts, textvariable=prod, values=["(none)"], state="readonly",
                            width=22, font=mono)
    prod_box.pack(side="left", padx=(4, 0))

    def refresh_products(*_a) -> None:
        vals = ["(none)"] + product_ids(ids[vbox.current()] if vbox.current() >= 0 else ids[0])
        prod_box.config(values=vals)
        if prod.get() not in vals:
            prod.set("(none)")

    vbox.bind("<<ComboboxSelected>>", refresh_products)
    refresh_products()

    tk.Label(opts, text="   avatar", font=mono, bg=BG, fg=FAINT).pack(side="left", padx=(14, 0))
    av = tk.StringVar(value=(avatars() or [""])[0])
    av_list = avatars() or [""]
    if "sofia-hsu_v2" in av_list:
        av.set("sofia-hsu_v2")
    ttk.Combobox(opts, textvariable=av, values=av_list, state="readonly", width=20,
                 font=mono).pack(side="left", padx=(4, 0))

    # ---- actions ----------------------------------------------------------------
    acts = tk.Frame(outer, bg=BG)
    acts.pack(fill="x", pady=(12, 0))

    def mk(parent, text, cmd, primary=False):
        return tk.Button(parent, text=text, font=big, relief="flat", cursor="hand2",
                         padx=18, pady=6, command=cmd,
                         bg=ACCENT if primary else CARD, fg="white" if primary else INK,
                         activebackground="#0b5b56" if primary else "#e7ecec",
                         activeforeground="white" if primary else INK)

    status = tk.Label(outer, text="", font=mono, bg=BG, fg=MUTED, anchor="w", justify="left",
                      wraplength=700)

    def set_status(msg: str, colour: str = MUTED) -> None:
        status.config(text=msg, fg=colour)

    buttons: list[tk.Button] = []

    def busy(on: bool, note: str = "") -> None:
        for b in buttons:
            b.config(state="disabled" if on else "normal")
        if note:
            set_status(note)

    def cid() -> str:
        return ids[vbox.current()]

    def text() -> str:
        return box.get("1.0", "end").strip()

    def run(fn):
        """Everything heavy goes off the UI thread — synthesis is seconds, video is tens."""
        def wrapped():
            try:
                fn()
            except Exception as exc:
                print(traceback.format_exc(), file=sys.stderr)
                msg = f"{type(exc).__name__}: {exc}"
                root.after(0, lambda: set_status(msg, BAD))
            finally:
                root.after(0, lambda: busy(False))
                root.after(0, refresh_recent)
        threading.Thread(target=wrapped, daemon=True).start()

    def do_speak():
        t = text()
        if not t:
            set_status("write something first", BAD)
            return
        busy(True, "synthesising…")

        def job():
            from stream_speak import speak_streaming
            cloning = clone_ref.get("path")
            if cloning and not clone_ref.get("text"):
                raise RuntimeError("still transcribing the reference clip — try again in a "
                                   "moment, or Clear to use a built-in voice")
            out = CLIPS / (f"{datetime.now():%H%M%S}-"
                           f"{'clone' if cloning else uuid.uuid4().hex[:4]}.wav")
            who = f"clone of {Path(cloning).name}" if cloning else cid()

            # Long text is spoken sentence by sentence, and the first piece starts playing while
            # the rest is still rendering. The model runs faster than real time (RTF 0.56-0.67),
            # so once the first chunk is out the queue stays ahead of the listener. Measured on
            # a 235-character paragraph: first sound at 3.8 s instead of 10.5 s.
            def chunk(i, n, waited):
                msg = (f"speaking {i}/{n} · first sound after {waited:.1f}s"
                       if n > 1 else f"speaking · {waited:.1f}s")
                root.after(0, lambda: set_status(msg, OK))

            speak_streaming(cid() if not cloning else "", t, out, speed=float(speed.get()),
                            ref_audio=cloning, ref_text=clone_ref.get("text") or None,
                            on_chunk=chunk)
            out.with_suffix(".txt").write_text(t, encoding="utf-8")
            root.after(0, lambda: set_status(f"{who} · {out}", OK))
        run(job)

    def do_scenario():
        brief = text()
        if not brief:
            set_status("describe the scene first", BAD)
            return
        busy(True, "she is writing…")

        def job():
            from voice_studio import synthesize, write_script
            started = time.perf_counter()
            pid = None if prod.get() == "(none)" else prod.get()
            try:
                script = write_script(cid(), brief, seconds=18, product=pid)
            except ValueError as exc:
                # The rule checker refused it. That is the system working.
                root.after(0, lambda: set_status(f"refused: {exc}", WARN))
                return
            wrote = time.perf_counter() - started
            out = CLIPS / f"{datetime.now():%H%M%S}-scen.wav"
            synthesize(cid(), script, out=out)
            out.with_suffix(".txt").write_text(script, encoding="utf-8")
            root.after(0, lambda: (box.delete("1.0", "end"), box.insert("1.0", script),
                                   set_status(f"script {wrote:.1f}s · {out.name}", OK),
                                   play(out)))
        run(job)

    def do_video():
        t = text()
        if not t:
            set_status("write something first", BAD)
            return
        if not LT_PY.is_file():
            set_status(f"LiveTalking venv missing: {LT_PY}", BAD)
            return
        busy(True, "rendering video — this takes about a second per three of speech…")

        def job():
            out = CLIPS / f"{datetime.now():%H%M%S}-video.mp4"
            started = time.perf_counter()
            proc = subprocess.run(
                [str(LT_PY), str(REPO / "tools/livetalking/render_video.py"), cid(),
                 "--text", t, "--avatar-id", av.get(), "--out", str(out)],
                capture_output=True, text=True, cwd=str(REPO),
                env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
            if proc.returncode != 0 or not out.is_file():
                tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
                raise RuntimeError("render failed: " + " / ".join(tail))
            took = time.perf_counter() - started
            root.after(0, lambda: (set_status(f"{took:.1f}s · {out}", OK), os.startfile(str(out))))
        run(job)

    buttons.append(mk(acts, "Speak", do_speak, primary=True))
    buttons[-1].pack(side="left")
    buttons.append(mk(acts, "Write it for me", do_scenario))
    buttons[-1].pack(side="left", padx=(8, 0))
    buttons.append(mk(acts, "Render video", do_video))
    buttons[-1].pack(side="left", padx=(8, 0))
    tk.Button(acts, text="Open folder", font=body, relief="flat", bg=BG, fg=ACCENT,
              cursor="hand2", command=lambda: os.startfile(str(CLIPS))).pack(side="right")

    status.pack(fill="x", pady=(10, 0))

    # ---- recent -----------------------------------------------------------------
    tk.Label(outer, text="RECENT", font=lbl, bg=BG, fg=FAINT, anchor="w").pack(fill="x", pady=(14, 2))
    rec_frame = tk.Frame(outer, bg=BG)
    rec_frame.pack(fill="x")

    def refresh_recent() -> None:
        for w in rec_frame.winfo_children():
            w.destroy()
        files = sorted(list(CLIPS.glob("*.wav")) + list(CLIPS.glob("*.mp4")),
                       key=lambda p: p.stat().st_mtime, reverse=True)[:6]
        if not files:
            tk.Label(rec_frame, text="nothing yet", font=mono, bg=BG, fg=FAINT,
                     anchor="w").pack(fill="x")
            return
        for f in files:
            r = tk.Frame(rec_frame, bg=CARD, highlightthickness=1, highlightbackground=RULE)
            r.pack(fill="x", pady=1)
            tk.Label(r, text=f"{datetime.fromtimestamp(f.stat().st_mtime):%H:%M}", font=mono,
                     bg=CARD, fg=FAINT).pack(side="left", padx=(9, 8), pady=4)
            txt = f.with_suffix(".txt")
            words = txt.read_text(encoding="utf-8")[:70] if txt.is_file() else f.name
            tk.Label(r, text=words, font=body, bg=CARD, fg=MUTED, anchor="w").pack(
                side="left", fill="x", expand=True)
            opener = (lambda p=f: play(p)) if f.suffix == ".wav" else (lambda p=f: os.startfile(str(p)))
            tk.Button(r, text="play", font=mono, relief="flat", bg=CARD, fg=ACCENT,
                      cursor="hand2", command=opener).pack(side="right", padx=(0, 8))

    def tick() -> None:
        refresh_services()
        root.after(15000, tick)

    refresh_recent()
    tick()
    root.bind("<Control-Return>", lambda e: (do_speak(), "break")[1])
    box.bind("<Control-Return>", lambda e: (do_speak(), "break")[1])
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
