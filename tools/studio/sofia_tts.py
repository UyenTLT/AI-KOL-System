#!/usr/bin/env python3
"""A page that does one thing: type text, hear Sofia say it.

`simple_server.py` covers five voices and three features. This is the narrow version — one
voice, one job — because the common case is writing a line and hearing it back, and every
extra control on the way is friction.

No JavaScript. Every interaction is a form POST and the reply is ordinary HTML, which on this
machine has been the only reliably renderable kind of page.

It also assumes the browser may not play audio at all, so a result is never *only* a player:
the file path is shown in a selectable box and a download link sits next to it. Renders go to
`renders/sofia/` and the last dozen stay listed, so nothing has to be regenerated to be found.

    .venv\\Scripts\\python.exe tools\\studio\\sofia_tts.py         # :8775

Needs tools/voice_eval/cosy_server.py on :9881 (her engine). If it is down the page says so
rather than quietly handing back her old, flatter GPT-SoVITS voice.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import sys
import time
import traceback
import urllib.parse
import urllib.request
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools" / "studio"))
sys.path.insert(0, str(REPO / "tools" / "livetalking"))

KOL = "sofia-vargas"
CLIPS = Path(os.getenv("KOL_RENDER_DIR") or (REPO / "renders" / "sofia"))
CLIPS.mkdir(parents=True, exist_ok=True)

SAMPLES = [
    "Honestly, this is my favourite thing I have tried all month.",
    "Okay so, I honestly did not expect this to work. But look at my skin right now.",
    "I mean... it's fine? Like, it's not bad, but I would not repurchase.",
    "Have you tried this one yet? Tell me what you think.",
]

CSS = """
:root{
  --paper:#EFF2F2; --surface:#FFF; --surface-2:#E7ECEC; --ink:#111719; --text:#1B2426;
  --muted:#5A6A6C; --faint:#8A9899; --rule:#D2DADA; --accent:#0E6E68; --accent-soft:#0E6E680F;
  --warn:#A0700F; --bad:#B04352;
  --serif:Cambria,"Iowan Old Style",Charter,Georgia,serif;
  --sans:"Segoe UI Variable Text","Segoe UI",system-ui,-apple-system,sans-serif;
  --mono:"Cascadia Mono",Consolas,ui-monospace,monospace;
}
*,*::before,*::after{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--text);font-family:var(--sans);
 font-size:16px;line-height:1.6;-webkit-font-smoothing:antialiased}
.w{max-width:720px;margin:0 auto;padding:44px 22px 80px}
.eyebrow{font-family:var(--mono);font-size:11px;letter-spacing:.15em;text-transform:uppercase;
 color:var(--accent)}
h1{font-family:var(--serif);font-size:34px;line-height:1.1;font-weight:600;color:var(--ink);
 margin:6px 0 6px;letter-spacing:-.015em}
.sub{color:var(--muted);font-size:15px;margin:0 0 8px}
.who{display:flex;gap:14px;flex-wrap:wrap;font-family:var(--mono);font-size:11.5px;
 color:var(--faint);padding:10px 0 0;border-top:1px solid var(--rule);margin-top:16px}
form{background:var(--surface);border:1px solid var(--rule);border-radius:13px;
 padding:18px 20px;margin:22px 0 16px}
label{display:block;font-size:11.5px;letter-spacing:.07em;text-transform:uppercase;
 color:var(--faint);font-weight:600;margin:0 0 6px}
textarea{width:100%;font:inherit;font-size:17px;line-height:1.5;padding:12px 13px;
 border:1px solid var(--rule);border-radius:9px;background:var(--paper);color:var(--ink);
 resize:vertical;min-height:96px}
textarea:focus{outline:2px solid var(--accent);outline-offset:1px;background:var(--surface)}
.controls{display:flex;gap:14px;align-items:flex-end;flex-wrap:wrap;margin-top:14px}
.controls>div{flex:0 0 auto}
select{font:inherit;font-size:14px;padding:8px 11px;border:1px solid var(--rule);
 border-radius:8px;background:var(--paper);color:var(--ink)}
button{font:inherit;font-size:15.5px;font-weight:600;padding:11px 26px;
 border:1px solid var(--accent);border-radius:9px;background:var(--accent);color:#fff;
 cursor:pointer;margin-left:auto}
button:hover{background:#0b5b56}
button:focus-visible{outline:2px solid var(--ink);outline-offset:2px}
.out{background:var(--surface);border:1px solid var(--rule);border-left:3px solid var(--accent);
 border-radius:13px;padding:18px 20px;margin:0 0 20px}
.out .said{font-family:var(--serif);font-size:19px;line-height:1.45;color:var(--ink);margin:0 0 12px}
audio{width:100%;margin:2px 0 10px}
.meta{font-family:var(--mono);font-size:11.5px;color:var(--faint);display:flex;gap:14px;
 flex-wrap:wrap;font-variant-numeric:tabular-nums}
.meta b{color:var(--text);font-weight:600}
.path{font-family:var(--mono);font-size:12px;background:var(--surface-2);color:var(--text);
 padding:9px 11px;border-radius:7px;margin-top:12px;word-break:break-all;user-select:all}
.path b{display:block;font-family:var(--sans);font-size:10.5px;text-transform:uppercase;
 letter-spacing:.07em;color:var(--accent);margin-bottom:3px;font-weight:600}
a.dl{display:inline-block;margin-top:10px;font-size:14px;color:var(--accent);font-weight:600}
.err{background:var(--surface);border:1px solid var(--rule);border-left:3px solid var(--bad);
 border-radius:13px;padding:16px 20px;margin:0 0 20px;color:var(--bad);font-size:14.5px}
.err pre{white-space:pre-wrap;font-size:11.5px;color:var(--muted);margin:8px 0 0}
h2{font-family:var(--mono);font-size:11px;letter-spacing:.11em;text-transform:uppercase;
 color:var(--faint);font-weight:600;margin:30px 0 10px}
.samples{display:flex;flex-direction:column;gap:0;background:var(--surface);
 border:1px solid var(--rule);border-radius:11px;overflow:hidden}
.samples form{margin:0;border:0;border-radius:0;padding:0;background:none}
.samples button{margin:0;width:100%;text-align:left;background:none;color:var(--text);
 border:0;border-bottom:1px solid var(--rule);border-radius:0;font-weight:400;
 font-size:14.5px;padding:12px 16px;cursor:pointer}
.samples form:last-child button{border-bottom:0}
.samples button:hover{background:var(--accent-soft);color:var(--ink)}
.recent{display:flex;flex-direction:column;gap:6px}
.rec{display:flex;gap:12px;align-items:baseline;font-size:13.5px;padding:8px 12px;
 background:var(--surface);border:1px solid var(--rule);border-radius:9px}
.rec .t{font-family:var(--mono);font-size:11px;color:var(--faint);flex:0 0 auto}
.rec .x{flex:1;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.rec a{color:var(--accent);font-weight:600;flex:0 0 auto;font-size:13px}
.down{background:var(--surface);border:1px solid var(--rule);border-left:3px solid var(--warn);
 border-radius:11px;padding:14px 18px;margin:0 0 18px;font-size:14.5px;color:var(--warn)}
.down code{font-family:var(--mono);font-size:12.5px;color:var(--text);
 background:var(--surface-2);padding:1px 5px;border-radius:3px}
footer{margin-top:36px;padding-top:14px;border-top:1px solid var(--rule);
 font-family:var(--mono);font-size:11.5px;color:var(--faint)}
"""


def esc(s) -> str:
    return html.escape(str(s), quote=True)


def voice_cfg() -> dict:
    try:
        prof = json.loads((REPO / "kols" / KOL / "profile.json").read_text(encoding="utf-8"))
        return (prof.get("ai_assets") or {}).get("voice") or {}
    except Exception:
        return {}


def engine_up(v: dict) -> bool:
    try:
        urllib.request.urlopen(f"{v.get('api', 'http://127.0.0.1:9881')}/health", timeout=2)
        return True
    except Exception:
        return False


def recent(n: int = 12) -> list[tuple[Path, str]]:
    out = []
    for w in sorted(CLIPS.glob("*.wav"), key=lambda p: p.stat().st_mtime, reverse=True)[:n]:
        txt = w.with_suffix(".txt")
        out.append((w, txt.read_text(encoding="utf-8") if txt.is_file() else w.stem))
    return out


def page(body: str, text: str = "") -> bytes:
    v = voice_cfg()
    up = engine_up(v)
    warn = "" if up else (
        '<div class="down">Her engine is not answering on '
        f'<code>{esc(v.get("api", "http://127.0.0.1:9881"))}</code>. Start it with '
        '<code>CosyVoice\\.venv\\Scripts\\python.exe tools\\voice_eval\\cosy_server.py</code> '
        '&mdash; without it you would get her older, flatter voice instead of this one.</div>')

    samples = "\n".join(
        f'<form method="post" action="/say"><input type="hidden" name="text" value="{esc(s)}">'
        f'<button type="submit">{esc(s)}</button></form>' for s in SAMPLES)

    rows = "\n".join(
        f'<div class="rec"><span class="t">{datetime.fromtimestamp(w.stat().st_mtime):%H:%M}</span>'
        f'<span class="x">{esc(t)}</span>'
        f'<a href="/media/{esc(w.name)}" download>save</a></div>'
        for w, t in recent())
    recent_block = (f'<h2>Recent</h2><div class="recent">{rows}</div>'
                    if rows else "")

    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sofia — text to speech</title><style>{CSS}</style></head><body><div class="w">

<div class="eyebrow">Text to speech</div>
<h1>Sofia Vargas</h1>
<p class="sub">Write a line. She says it back.</p>
<div class="who">
  <span>{esc(v.get("engine", "?"))} &middot; {esc(v.get("mode", "?"))}</span>
  <span>cloned from her own recording</span>
  <span>levelled to {esc(v.get("target_lufs", "?"))} LUFS</span>
  <span>{"engine ready" if up else "engine down"}</span>
</div>

{warn}
{body}

<form method="post" action="/say">
  <label for="t">What should she say</label>
  <textarea id="t" name="text" autofocus>{esc(text)}</textarea>
  <div class="controls">
    <div><label for="sp">Pace</label>
      <select id="sp" name="speed">
        <option value="0.85">slower</option>
        <option value="1.0" selected>normal</option>
        <option value="1.15">quicker</option>
      </select></div>
    <button type="submit">Speak</button>
  </div>
</form>

<h2>Or start from one of these</h2>
<div class="samples">{samples}</div>

{recent_block}

<footer>CosyVoice 2 &middot; RTX 5070 &middot; nothing leaves this machine.
  Clips are kept in {esc(CLIPS)}</footer>
</div></body></html>"""
    return doc.encode("utf-8")


def result(clip: str, said: str, meta: str) -> str:
    return f"""<div class="out">
  <div class="said">&ldquo;{esc(said)}&rdquo;</div>
  <audio controls autoplay src="/media/{esc(clip)}"></audio>
  <div class="meta">{meta}</div>
  <div class="path"><b>on disk &mdash; open this in any player</b>{esc(CLIPS / clip)}</div>
  <a class="dl" href="/media/{esc(clip)}" download>Download</a>
</div>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "SofiaTTS/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        print(f'  {self.client_address[0]}  "{self.requestline}"', flush=True)

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
            self._send(b"sofia tts is reachable", "text/plain; charset=utf-8")
        elif path.startswith("/media/"):
            f = CLIPS / Path(urllib.parse.unquote(path[7:])).name   # no traversal
            if not f.is_file():
                self._send(b"no such clip", "text/plain; charset=utf-8", 404)
                return
            self._send(f.read_bytes(), "audio/wav")
        else:
            self._send(b"not found", "text/plain; charset=utf-8", 404)

    def do_POST(self):
        if urllib.parse.urlparse(self.path).path != "/say":
            self._send(b"not found", "text/plain; charset=utf-8", 404)
            return
        n = int(self.headers.get("Content-Length") or 0)
        form = {k: v[0] for k, v in
                urllib.parse.parse_qs(self.rfile.read(n).decode("utf-8") if n else "").items()}
        text = (form.get("text") or "").strip()
        if not text:
            self._send(page('<div class="err">Write something first.</div>'),
                       "text/html; charset=utf-8")
            return
        try:
            from voice_studio import synthesize
            speed = float(form.get("speed") or 1.0)
            name = f"{datetime.now():%H%M%S}-{uuid.uuid4().hex[:4]}.wav"
            started = time.perf_counter()
            synthesize(KOL, text, out=CLIPS / name, speed=speed)
            # Keep the words beside the audio so the recent list is readable later.
            (CLIPS / name).with_suffix(".txt").write_text(text, encoding="utf-8")
            took = time.perf_counter() - started
            kb = (CLIPS / name).stat().st_size / 1024
            meta = (f"<span><b>{took:.1f}</b> s</span><span><b>{kb:.0f}</b> KB</span>"
                    f"<span>pace {speed}&times;</span>")
            self._send(page(result(name, text, meta), text), "text/html; charset=utf-8")
        except Exception as exc:
            body = (f'<div class="err"><b>{esc(type(exc).__name__)}</b><br>{esc(exc)}'
                    f'<pre>{esc(traceback.format_exc()[-600:])}</pre></div>')
            self._send(page(body, text), "text/html; charset=utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8775)
    args = ap.parse_args()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Sofia text-to-speech -> http://{args.host}:{args.port}")
    print(f"clips -> {CLIPS}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
