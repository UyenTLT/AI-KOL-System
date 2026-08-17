#!/usr/bin/env python3
"""Voice Studio, plain-HTML edition — type text, get speech or a talking video.

No JavaScript anywhere. Every interaction is a form POST and the result comes back as ordinary
HTML. That is deliberate: the browser on this machine has been unreliable with local pages, and
a page with no client-side code has far fewer ways to fail silently.

It also assumes the browser may not play media at all. Every result therefore shows three
things, not one: an inline player, a download link, and **the full path to the file on disk**.
If the player is dead, the path still works in any media player.

Renders land in `renders/` at the repo root, not a temp folder — a clip you cannot find is a
clip you cannot listen to.

    .venv\\Scripts\\python.exe tools\\studio\\simple_server.py            # :8774

Needs GPT-SoVITS api_v2 on :9880, CosyVoice on :9881 for sofia-vargas, Ollama on :11434 for
scenario mode, and the LiveTalking venv for video.
"""
from __future__ import annotations

import argparse
import html
import os
import subprocess
import sys
import time
import traceback
import urllib.parse
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools" / "studio"))
sys.path.insert(0, str(REPO / "tools" / "livetalking"))

CLIPS = Path(os.getenv("KOL_RENDER_DIR") or (REPO / "renders"))
CLIPS.mkdir(parents=True, exist_ok=True)
LT_PY = REPO / "LiveTalking" / ".venv" / "Scripts" / "python.exe"

CSS = """
body{background:#eff2f2;color:#1b2426;margin:0;
 font:16px/1.6 "Segoe UI",system-ui,-apple-system,sans-serif}
.w{max-width:780px;margin:0 auto;padding:36px 20px 70px}
h1{font-family:Cambria,Georgia,serif;font-size:30px;margin:0 0 4px;color:#111719}
h2{font-family:Cambria,Georgia,serif;font-size:20px;margin:32px 0 6px;color:#111719}
p.s{color:#5a6a6c;font-size:15px;margin:0 0 14px}
form{background:#fafbfb;border:1px solid #d2dada;border-radius:11px;padding:16px 18px;margin:0 0 14px}
label{display:block;font-size:12px;letter-spacing:.06em;text-transform:uppercase;
 color:#8a9899;margin:12px 0 4px;font-weight:600}
label:first-of-type{margin-top:0}
textarea,input[type=text],select{width:100%;font:inherit;font-size:15px;padding:9px 11px;
 border:1px solid #d2dada;border-radius:8px;background:#fff;color:#1b2426}
textarea{resize:vertical}
.row{display:flex;gap:12px;flex-wrap:wrap}
.row>div{flex:1;min-width:150px}
button{font:inherit;font-size:15px;font-weight:600;padding:10px 22px;margin-top:14px;
 border:1px solid #0e6e68;border-radius:8px;background:#0e6e68;color:#fff;cursor:pointer}
button:hover{background:#0b5b56}
button.alt{background:#fafbfb;color:#0e6e68}
button.alt:hover{background:#eef4f3}
.out{background:#fafbfb;border:1px solid #d2dada;border-left:3px solid #0e6e68;
 border-radius:11px;padding:16px 18px;margin:0 0 18px}
.out h3{margin:0 0 8px;font-size:15px;color:#111719}
audio,video{width:100%;margin:10px 0 4px;background:#000;border-radius:6px}
.said{font-size:15px;padding-left:12px;border-left:2px solid #d2dada;color:#1b2426;margin:8px 0}
.meta{font-family:Consolas,monospace;font-size:12px;color:#8a9899}
.path{font-family:Consolas,monospace;font-size:12.5px;background:#e4e9e9;color:#1b2426;
 padding:8px 10px;border-radius:6px;margin-top:8px;word-break:break-all;user-select:all}
.path b{color:#0e6e68;display:block;font-family:"Segoe UI",sans-serif;font-size:11px;
 text-transform:uppercase;letter-spacing:.06em;margin-bottom:3px}
a.dl{display:inline-block;margin-top:8px;font-size:14px;color:#0e6e68;font-weight:600}
.err{background:#fafbfb;border:1px solid #d2dada;border-left:3px solid #b04352;
 border-radius:11px;padding:16px 18px;margin:0 0 18px;color:#b04352;font-size:14.5px}
.err pre{white-space:pre-wrap;font-size:12px;color:#5a6a6c;margin:8px 0 0}
.note{color:#5a6a6c;font-size:13.5px;margin:6px 0 0}
footer{margin-top:36px;padding-top:14px;border-top:1px solid #d2dada;
 font-family:Consolas,monospace;font-size:12px;color:#8a9899}
"""


def esc(s) -> str:
    return html.escape(str(s), quote=True)


def characters():
    try:
        from voice_studio import characters as chars
        return chars()
    except Exception:
        return []


def options(sel: str) -> str:
    out = []
    for c in characters():
        cid, name = c.get("id", ""), (c.get("name") or c.get("id"))
        s = " selected" if cid == sel else ""
        out.append(f'<option value="{esc(cid)}"{s}>{esc(name)} — {esc(c.get("lang",""))}</option>')
    return "\n".join(out) or '<option value="">(no voices — is api_v2 running?)</option>'


def avatar_options(sel: str) -> str:
    root = REPO / "LiveTalking" / "data" / "avatars"
    ids = sorted(d.name for d in root.iterdir() if d.is_dir()) if root.is_dir() else []
    return "\n".join(f'<option value="{esc(i)}"{" selected" if i == sel else ""}>{esc(i)}</option>'
                     for i in ids) or '<option value="">(no avatars built)</option>'


def page(body: str, *, voice="", text="", scenario="", avatar="sofia-vargas_v2") -> bytes:
    text = text or "Honestly, this is my favourite thing I have tried all month."
    scenario = scenario or "unboxing a new sunscreen she actually likes, honest-review tone"
    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Voice Studio</title><style>{CSS}</style></head><body><div class="w">
<h1>Voice Studio</h1>
<p class="s">Type something, pick a voice, get speech — or a talking video. Plain HTML forms,
   no JavaScript. Every result is saved to <code>renders\\</code> and the full path is shown,
   so a clip is listenable even if the browser will not play it.</p>

{body}

<h2>1 &middot; Text to speech</h2>
<form method="post" action="/say">
  <label for="t">What should she say</label>
  <textarea id="t" name="text" rows="3">{esc(text)}</textarea>
  <div class="row">
    <div><label for="v">Voice</label><select id="v" name="voice">{options(voice)}</select></div>
    <div><label for="sp">Speed</label>
      <select id="sp" name="speed">
        <option value="0.8">0.8&times; slower</option><option value="0.9">0.9&times;</option>
        <option value="1.0" selected>1.0&times; normal</option>
        <option value="1.15">1.15&times;</option><option value="1.3">1.3&times; faster</option>
      </select></div>
  </div>
  <button type="submit">Speak it</button>
</form>

<h2>2 &middot; Talking video</h2>
<p class="s">The same line, lip-synced onto her avatar and written out as an mp4. Slower —
   roughly a second of render per three seconds of speech.</p>
<form method="post" action="/video">
  <label for="vt">What should she say</label>
  <textarea id="vt" name="text" rows="3">{esc(text)}</textarea>
  <div class="row">
    <div><label for="v2">Voice</label><select id="v2" name="voice">{options(voice or "sofia-vargas")}</select></div>
    <div><label for="av">Avatar</label><select id="av" name="avatar">{avatar_options(avatar)}</select></div>
  </div>
  <button type="submit">Render the video</button>
</form>

<h2>3 &middot; Scenario &rarr; she writes it herself</h2>
<p class="s">Give a brief, not a script. She drafts the copy from her own profile, then speaks
   it. Generated scripts are rule-checked — an invented price or a claimed link is refused
   rather than returned.</p>
<form method="post" action="/scenario">
  <label for="sc">The brief</label>
  <textarea id="sc" name="scenario" rows="2">{esc(scenario)}</textarea>
  <div class="row">
    <div><label for="v3">Voice</label><select id="v3" name="voice">{options(voice)}</select></div>
    <div><label for="se">Roughly how long</label>
      <select id="se" name="seconds">
        <option value="12">12 seconds</option><option value="18" selected>18 seconds</option>
        <option value="30">30 seconds</option>
      </select></div>
  </div>
  <button type="submit">Write it and speak it</button>
  <button type="submit" class="alt" name="withvideo" value="1">Write it and render video</button>
</form>

<footer>GPT-SoVITS :9880 &middot; CosyVoice :9881 &middot; Ollama :11434 &middot; all local.</footer>
</div></body></html>"""
    return doc.encode("utf-8")


def result(title: str, clip: str, said: str, meta: str, video: bool = False) -> str:
    tag = (f'<video controls src="/media/{esc(clip)}"></video>' if video
           else f'<audio controls src="/media/{esc(clip)}"></audio>')
    return f"""<div class="out">
  <h3>{esc(title)}</h3>
  {tag}
  <div class="said">{esc(said)}</div>
  <div class="meta">{esc(meta)}</div>
  <div class="path"><b>saved on disk — open this in any player</b>{esc(CLIPS / clip)}</div>
  <a class="dl" href="/media/{esc(clip)}" download>Download the file</a>
</div>"""


def error(what: str, detail: str, tb: str = "") -> str:
    extra = f"<pre>{esc(tb)}</pre>" if tb else ""
    return f'<div class="err"><b>{esc(what)}</b><br>{esc(detail)}{extra}</div>'


class Handler(BaseHTTPRequestHandler):
    server_version = "VoiceStudioSimple/1.1"
    # HTTP/1.1, not the http.server default of 1.0: under 1.0 the socket closes the moment the
    # response is written, and a browser that sent `Connection: keep-alive` can read that as a
    # reset and discard the bytes — which shows as an empty page rather than an error.
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        ua = self.headers.get("User-Agent", "-")[:50]
        print(f'  {self.client_address[0]}  "{self.requestline}"  UA={ua}', flush=True)

    def handle_one_request(self):
        try:
            super().handle_one_request()
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            self.close_connection = True

    def _send(self, body: bytes, ctype: str, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/":
            self._send(page(""), "text/html; charset=utf-8")
        elif path == "/ping":
            self._send(b"studio is reachable", "text/plain; charset=utf-8")
        elif path.startswith("/media/"):
            name = Path(urllib.parse.unquote(path[len("/media/"):])).name   # no traversal
            f = CLIPS / name
            if not f.is_file():
                self._send(b"no such file", "text/plain; charset=utf-8", 404)
                return
            ctype = "video/mp4" if f.suffix == ".mp4" else "audio/wav"
            self._send(f.read_bytes(), ctype)
        else:
            self._send(b"not found", "text/plain; charset=utf-8", 404)

    def _form(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n).decode("utf-8") if n else ""
        return {k: v[0] for k, v in urllib.parse.parse_qs(raw).items()}

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        form = self._form()
        voice = form.get("voice", "")
        try:
            if path == "/say":
                self._say(form, voice)
            elif path == "/video":
                self._video(form, voice)
            elif path == "/scenario":
                self._scenario(form, voice)
            else:
                self._send(b"not found", "text/plain; charset=utf-8", 404)
        except Exception as exc:
            body = error(type(exc).__name__, str(exc), traceback.format_exc()[-700:])
            self._send(page(body, voice=voice, text=form.get("text", ""),
                            scenario=form.get("scenario", "")), "text/html; charset=utf-8")

    def _say(self, form, voice, prefix="say"):
        from voice_studio import synthesize
        text = (form.get("text") or "").strip()
        if not text:
            self._send(page(error("Nothing to say", "Type some text first."), voice=voice),
                       "text/html; charset=utf-8")
            return
        speed = float(form.get("speed") or 1.0)
        name = f"{prefix}-{uuid.uuid4().hex[:6]}.wav"
        t = time.perf_counter()
        synthesize(voice, text, out=CLIPS / name, speed=speed)
        kb = (CLIPS / name).stat().st_size / 1024
        body = result(f"{voice} — speaking your text", name, text,
                      f"{time.perf_counter()-t:.1f} s to synthesise · {kb:.0f} KB · speed {speed}x")
        self._send(page(body, voice=voice, text=text), "text/html; charset=utf-8")

    def _render_video(self, voice: str, text: str, avatar: str) -> tuple[str, str]:
        """Shell out to the LiveTalking venv — it owns torch and the wav2lip checkpoint, and
        pins a different stack from the one serving this page."""
        if not LT_PY.is_file():
            raise RuntimeError(f"LiveTalking venv missing: {LT_PY}")
        name = f"video-{uuid.uuid4().hex[:6]}.mp4"
        cmd = [str(LT_PY), str(REPO / "tools/livetalking/render_video.py"), voice,
               "--text", text, "--avatar-id", avatar, "--out", str(CLIPS / name)]
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800,
                              cwd=str(REPO), env=env)
        if proc.returncode != 0 or not (CLIPS / name).is_file():
            tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-6:]
            raise RuntimeError("render failed:\n" + "\n".join(tail))
        return name, proc.stdout

    def _video(self, form, voice):
        text = (form.get("text") or "").strip()
        avatar = form.get("avatar") or "sofia-vargas_v2"
        if not text:
            self._send(page(error("Nothing to say", "Type some text first."), voice=voice),
                       "text/html; charset=utf-8")
            return
        t = time.perf_counter()
        name, _ = self._render_video(voice, text, avatar)
        mb = (CLIPS / name).stat().st_size / 1e6
        body = result(f"{voice} — talking video ({avatar})", name, text,
                      f"{time.perf_counter()-t:.1f} s to render · {mb:.1f} MB", video=True)
        self._send(page(body, voice=voice, text=text, avatar=avatar), "text/html; charset=utf-8")

    def _scenario(self, form, voice):
        from voice_studio import synthesize, write_script
        scenario = (form.get("scenario") or "").strip()
        if not scenario:
            self._send(page(error("No brief", "Describe the scene first."), voice=voice),
                       "text/html; charset=utf-8")
            return
        seconds = int(form.get("seconds") or 18)
        t0 = time.perf_counter()
        try:
            script = write_script(voice, scenario, seconds=seconds)
        except ValueError as exc:
            # The guard refused it. That is the system working, so say so plainly.
            self._send(page(error("The draft broke a hard rule and was refused", str(exc)),
                            voice=voice, scenario=scenario), "text/html; charset=utf-8")
            return
        wrote = time.perf_counter() - t0

        if form.get("withvideo"):
            t1 = time.perf_counter()
            name, _ = self._render_video(voice, script, "sofia-vargas_v2")
            body = result(f"{voice} — her own words, on video", name, script,
                          f"script {wrote:.1f} s · video {time.perf_counter()-t1:.1f} s",
                          video=True)
        else:
            name = f"scen-{uuid.uuid4().hex[:6]}.wav"
            t1 = time.perf_counter()
            synthesize(voice, script, out=CLIPS / name)
            body = result(f"{voice} — her own words", name, script,
                          f"script {wrote:.1f} s · speech {time.perf_counter()-t1:.1f} s")
        self._send(page(body, voice=voice, scenario=scenario), "text/html; charset=utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8774)
    args = ap.parse_args()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Voice Studio (plain HTML) -> http://{args.host}:{args.port}")
    print(f"renders -> {CLIPS}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
