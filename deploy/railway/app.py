#!/usr/bin/env python3
"""The live room, deployable to Railway. The brain stays on the GPU box.

WHY THIS IS A PROXY AND NOT THE WHOLE THING
-------------------------------------------
Railway has no GPU. Sofia's answer needs three models resident on one: Ollama serving the tuned
7B (4.7 GB), CosyVoice 2 for the speech, and RVC for her timbre. None of that runs on a Railway
dyno, and a deploy that pretended otherwise would put a convincing live room on the internet
with nothing behind it.

So this splits at the only honest seam. Railway serves the PAGE, which is static HTML, CSS and
JS that any host can serve. Everything that needs the models -- posting a comment, reading the
feed, fetching a rendered clip -- is forwarded to the machine the models are on, reached over a
tunnel.

    viewer ── https ──> Railway (this app) ── https ──> tunnel ──> 127.0.0.1:8777 on the GPU box

What that costs, stated plainly: the GPU box has to be switched on and tunnelled for the room to
answer anybody. This is a demo topology, not a production one. Production means either renting a
GPU host and moving the whole stack there, or moving the brain to a hosted API and giving up the
local-first property the project was built on.

    UPSTREAM   https://something.trycloudflare.com   the tunnel to the GPU box   (required)
    PORT       set by Railway                                                    (optional)

Locally:
    set UPSTREAM=http://127.0.0.1:8777 && python deploy/railway/app.py
"""
from __future__ import annotations

import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# live_ui is the single source of the room's markup. Importing it rather than copying it means
# the deployed page cannot drift from the local one, which is exactly what a duplicated
# template does after the second edit.
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools" / "livestream"))
try:
    from live_ui import live_page
except Exception:                                     # deployed without the repo tree
    live_page = None

UPSTREAM = (os.getenv("UPSTREAM") or "").rstrip("/")
PORT = int(os.getenv("PORT") or "8080")
TIMEOUT = float(os.getenv("UPSTREAM_TIMEOUT") or "120")

# Only these reach the GPU box. An allowlist rather than a catch-all proxy: this is a public
# URL, and the box behind it has no auth of its own.
PROXY_GET = ("/feed", "/state", "/clips", "/ping")
PROXY_GET_PREFIX = ("/media/", "/img/")
PROXY_POST = ("/say",)

OFFLINE = b"""<!doctype html><meta charset="utf-8"><title>Sofia is offline</title>
<style>body{background:#1a0b2e;color:#e9dcff;font:16px/1.6 system-ui,sans-serif;
display:flex;align-items:center;justify-content:center;height:100vh;margin:0;text-align:center}
div{max-width:420px;padding:26px}code{background:rgba(255,255,255,.1);padding:2px 6px;
border-radius:5px;font-size:13px}</style>
<div><h2>Sofia is not connected</h2>
<p>The room is served from here, but her voice and her brain run on a GPU machine that is not
reachable right now.</p>
<p><code>UPSTREAM</code> is not set, or the tunnel is down.</p></div>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "sofia-room"

    def log_message(self, fmt, *args):        # one line per request, not three
        sys.stderr.write("%s %s\n" % (self.command, self.path))

    def _send(self, body: bytes, ctype: str, code: int = 200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass                               # viewer navigated away mid-clip

    def _proxy(self, method: str, body: bytes | None = None):
        if not UPSTREAM:
            self._send(OFFLINE, "text/html; charset=utf-8", 503)
            return
        url = UPSTREAM + self.path
        req = urllib.request.Request(url, data=body, method=method)
        if method == "POST":
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                self._send(r.read(), r.headers.get("Content-Type", "application/octet-stream"),
                           r.status)
        except urllib.error.HTTPError as e:
            self._send(e.read() or b"upstream error", "text/plain; charset=utf-8", e.code)
        except Exception as exc:
            # The tunnel being down is the expected failure here, not an exceptional one, so it
            # gets a shape the page can handle rather than a stack trace.
            self._send(f'{{"error":"upstream unreachable: {type(exc).__name__}"}}'.encode(),
                       "application/json", 502)

    def do_GET(self):
        p = urllib.parse.urlparse(self.path).path
        if p in ("/", "/live"):
            if live_page is None:
                self._send(OFFLINE, "text/html; charset=utf-8", 500)
            else:
                self._send(live_page(), "text/html; charset=utf-8")
        elif p == "/healthz":
            # Railway's health check. Deliberately does NOT depend on the tunnel: the web
            # service being up and the GPU box being reachable are different failures, and
            # conflating them makes Railway restart a container that is working fine.
            self._send(b'{"ok":true,"upstream":' + (b'true' if UPSTREAM else b'false') + b'}',
                       "application/json")
        elif p in PROXY_GET or p.startswith(PROXY_GET_PREFIX):
            self._proxy("GET")
        else:
            self._send(b"not found", "text/plain; charset=utf-8", 404)

    def do_POST(self):
        p = urllib.parse.urlparse(self.path).path
        if p in PROXY_POST:
            n = int(self.headers.get("Content-Length") or 0)
            self._proxy("POST", self.rfile.read(n) if n else b"")
        else:
            self._send(b"not found", "text/plain; charset=utf-8", 404)


def main() -> int:
    print(f"  room on :{PORT}   upstream {UPSTREAM or '(NOT SET - room will show offline)'}",
          flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
