#!/usr/bin/env python3
"""A demo page for the three jobs and the three controls, in one place.

Jobs
    1  text to speech      type a line, hear it in a chosen voice
    2  voice clone         upload a clip, hear that voice say something else
    3  selling product     paste product information, get a sales script, hear it

Controls
    1  volume              applied to the render, and again live in the player
    2  play / pause        the one thing the desktop window cannot do — winsound has no
                           pause, only play and stop, so the browser's own player is the
                           feature rather than a wrapper around it
    3  speed               changed at render time (resampled) and live (playbackRate)

The live controls need JavaScript, which every other page in this project deliberately avoids
because pages on this machine have been unreliable. Here it is unavoidable: pausing and
volume are properties of a running player, not of a file. The generation forms are still plain
form POSTs, so if the script never runs the page still renders and still produces audio — it
just loses the live sliders.

    .venv\\Scripts\\python.exe tools\\studio\\demo_server.py        # :8776
"""
from __future__ import annotations

import argparse
import html
import os
import sys
import time
import traceback
import urllib.parse
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
for sub in ("studio", "livetalking", "voice_eval"):
    sys.path.insert(0, str(REPO / "tools" / sub))

CLIPS = Path(os.getenv("KOL_RENDER_DIR") or (REPO / "renders" / "demo_web"))
CLIPS.mkdir(parents=True, exist_ok=True)
UPLOADS = CLIPS / "uploads"
UPLOADS.mkdir(parents=True, exist_ok=True)

CSS = """
:root{--bg:#EFF2F2;--card:#FFF;--card2:#E7ECEC;--ink:#111719;--tx:#1B2426;--mut:#5A6A6C;
 --faint:#8A9899;--rule:#D2DADA;--acc:#0E6E68;--accdim:#0E6E680F;--bad:#B04352;--ok:#3C7F55}
@media (prefers-color-scheme:dark){:root{--bg:#0D1214;--card:#141B1D;--card2:#1D2628;
 --ink:#E8EDED;--tx:#DAE2E2;--mut:#96A5A6;--faint:#6E7D7E;--rule:#263133;--acc:#4FB3A8;
 --accdim:#4FB3A814;--bad:#D0707C;--ok:#5FA97A}}
*,*::before,*::after{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--tx);
 font:16px/1.6 "Segoe UI Variable Text","Segoe UI",system-ui,-apple-system,sans-serif}
.w{max-width:780px;margin:0 auto;padding:38px 20px 70px}
h1{font-family:Cambria,Georgia,serif;font-size:31px;margin:0 0 4px;color:var(--ink)}
.sub{color:var(--mut);font-size:15px;margin:0 0 6px}
.svc{display:flex;gap:14px;flex-wrap:wrap;font-family:Consolas,monospace;font-size:11.5px;
 color:var(--faint);border-top:1px solid var(--rule);padding-top:10px;margin-top:14px}
h2{font-family:Cambria,Georgia,serif;font-size:20px;margin:30px 0 4px;color:var(--ink)}
h2 b{font-family:Consolas,monospace;font-size:12px;color:var(--acc);
 border:1px solid var(--acc);border-radius:3px;padding:1px 6px;margin-right:8px;vertical-align:3px}
.note{color:var(--mut);font-size:14px;margin:0 0 12px}
form{background:var(--card);border:1px solid var(--rule);border-radius:12px;padding:16px 18px;
 margin:0 0 14px}
label{display:block;font-size:11.5px;letter-spacing:.06em;text-transform:uppercase;
 color:var(--faint);font-weight:600;margin:12px 0 5px}
label:first-of-type{margin-top:0}
textarea,input[type=text],input[type=file],select{width:100%;font:inherit;font-size:15px;
 padding:9px 11px;border:1px solid var(--rule);border-radius:8px;background:var(--bg);
 color:var(--ink)}
textarea{resize:vertical}
.row{display:flex;gap:12px;flex-wrap:wrap;align-items:flex-end}
.row>div{flex:1;min-width:130px}
button{font:inherit;font-size:15px;font-weight:600;padding:10px 22px;border:1px solid var(--acc);
 border-radius:8px;background:var(--acc);color:#fff;cursor:pointer;margin-top:14px}
button:hover{filter:brightness(1.08)}
.out{background:var(--card);border:1px solid var(--rule);border-left:3px solid var(--acc);
 border-radius:12px;padding:16px 18px;margin:0 0 18px}
.said{font-size:15.5px;color:var(--ink);padding-left:12px;border-left:2px solid var(--rule);
 margin:0 0 12px}
audio{width:100%;margin:2px 0 10px}
.ctl{background:var(--accdim);border:1px solid var(--rule);border-radius:10px;padding:12px 14px;
 margin:10px 0 0;display:flex;flex-direction:column;gap:10px}
.ctl .hd{font-family:Consolas,monospace;font-size:11px;letter-spacing:.07em;
 text-transform:uppercase;color:var(--acc);font-weight:600}
.slider{display:flex;gap:10px;align-items:center;font-family:Consolas,monospace;font-size:12px;
 color:var(--mut)}
.slider input[type=range]{flex:1;accent-color:var(--acc)}
.slider .v{min-width:52px;text-align:right;color:var(--ink);font-weight:600}
.btns{display:flex;gap:8px;flex-wrap:wrap}
.btns button{margin:0;padding:6px 14px;font-size:13.5px;background:var(--card);
 color:var(--acc);border-color:var(--rule)}
.meta{font-family:Consolas,monospace;font-size:11.5px;color:var(--faint);display:flex;gap:13px;
 flex-wrap:wrap}
.path{font-family:Consolas,monospace;font-size:12px;background:var(--card2);padding:8px 10px;
 border-radius:6px;margin-top:10px;word-break:break-all;user-select:all;color:var(--tx)}
.err{background:var(--card);border:1px solid var(--rule);border-left:3px solid var(--bad);
 border-radius:12px;padding:15px 18px;margin:0 0 18px;color:var(--bad);font-size:14.5px}
.err pre{white-space:pre-wrap;font-size:11.5px;color:var(--mut);margin:8px 0 0}
footer{margin-top:34px;padding-top:13px;border-top:1px solid var(--rule);
 font-family:Consolas,monospace;font-size:11.5px;color:var(--faint)}

/* the handbook — a dialog on the page, and the same content as its own page without script */
.lblrow{display:flex;justify-content:space-between;align-items:baseline;gap:12px}
.hbbtn{font-family:Consolas,monospace;font-size:11.5px;color:var(--acc);text-decoration:none;
 border:1px solid var(--acc);border-radius:20px;padding:2px 11px;white-space:nowrap;cursor:pointer}
.hbbtn:hover{background:var(--accdim)}
dialog{border:1px solid var(--rule);border-radius:14px;background:var(--card);color:var(--tx);
 padding:0;max-width:660px;width:calc(100% - 30px);max-height:86vh;overflow:auto;
 box-shadow:0 20px 54px #00000033}
dialog::backdrop{background:#0A0F1166}
.hb{padding:22px 24px 26px}
.hb h3{font-family:Cambria,Georgia,serif;font-size:21px;margin:0 0 3px;color:var(--ink)}
.hb .lead{color:var(--mut);font-size:14px;margin:0 0 14px}
.fld{border-top:1px solid var(--rule);padding:11px 0 3px}
.fld .n{font-family:Consolas,monospace;font-size:12.5px;color:var(--acc);font-weight:600}
.fld .need{font-family:Consolas,monospace;font-size:10px;letter-spacing:.07em;
 text-transform:uppercase;color:var(--faint);margin-left:8px}
.fld .d{font-size:14px;margin:3px 0 0}
.fld .ex{font-size:13.5px;color:var(--mut);margin:5px 0 0;padding-left:11px;
 border-left:2px solid var(--rule)}
.rules{background:var(--card2);border-radius:9px;padding:12px 15px;margin:17px 0 0;font-size:13.5px}
.rules b{color:var(--ink)}
.rules ul{margin:7px 0 0;padding-left:19px}
.rules li{margin:5px 0}
.tpl{font-family:Consolas,monospace;font-size:12.5px;background:var(--card2);border-radius:9px;
 padding:13px 15px;margin:9px 0 0;white-space:pre-wrap;user-select:all;color:var(--tx)}
.hbfoot{display:flex;gap:9px;flex-wrap:wrap;margin-top:16px}
.hbfoot button{margin:0;padding:8px 17px;font-size:14px}
.hbfoot .sec{background:var(--card);color:var(--acc);border-color:var(--rule)}
"""

# Live controls. Deliberately the only script on the page, and everything it touches degrades
# to a plain <audio controls> element if it never runs.
JS = """
function ctl(id){
  var a=document.getElementById(id); if(!a) return;
  var vol=document.getElementById(id+'-vol'), volv=document.getElementById(id+'-volv');
  var spd=document.getElementById(id+'-spd'), spdv=document.getElementById(id+'-spdv');
  if(vol){vol.oninput=function(){a.volume=vol.value/100; volv.textContent=vol.value+'%';};}
  if(spd){spd.oninput=function(){a.playbackRate=spd.value/100; spdv.textContent=(spd.value/100).toFixed(2)+'x';};}
  var p=document.getElementById(id+'-play');
  if(p){p.onclick=function(){ if(a.paused){a.play(); p.textContent='Pause';}
                              else{a.pause(); p.textContent='Play';} };
        a.onended=function(){p.textContent='Play';};}
  var s=document.getElementById(id+'-stop');
  if(s){s.onclick=function(){a.pause(); a.currentTime=0; if(p)p.textContent='Play';};}
  var r=document.getElementById(id+'-restart');
  if(r){r.onclick=function(){a.currentTime=0; a.play(); if(p)p.textContent='Pause';};}
}

/* The handbook opens as a dialog when script runs. When it does not, the button is still a
   plain link to /handbook, which serves the identical content as its own page. */
function hbInit(){
  var d=document.getElementById('hb'), o=document.getElementById('hb-open');
  if(!d||!o||!d.showModal) return;
  o.onclick=function(e){ e.preventDefault(); d.showModal(); };
  var c=document.getElementById('hb-close');
  if(c) c.onclick=function(){ d.close(); };
  var t=document.getElementById('hb-fill'), src=document.getElementById('hb-tpl');
  if(t&&src) t.onclick=function(){
    var pi=document.getElementById('pi'), tpl=src.textContent.replace(/^\\n+/,'');
    if(pi){ pi.value = pi.value.trim() ? pi.value.replace(/\\s+$/,'')+'\\n\\n'+tpl : tpl; }
    d.close();
    if(pi){ pi.focus(); pi.setSelectionRange(pi.value.length, pi.value.length); }
  };
}
document.addEventListener('DOMContentLoaded', hbInit);
"""


def esc(s) -> str:
    return html.escape(str(s), quote=True)


# What to type, and why. These are exactly the fields `product_editor.FIELDS` looks for, ordered
# for someone filling them in by hand rather than pasting a page: the three the script genuinely
# cannot work without, then the two that stop it sounding like an advert, then the two the
# verification rule governs. Every "why" here describes behaviour that is enforced in code —
# nothing is aspirational.
FIELD_GUIDE = [
    ("Product name", "essential",
     "What she says out loud. Leave it out and the script calls it “this product” throughout, "
     "which is the single clearest sign a pitch was not written by someone who used the thing.",
     "GlowLab Vitamin C Serum 15%"),
    ("What it is", "essential",
     "One or two plain sentences. The whole script is built on this line; everything else only "
     "trims it. Say what it physically is, not what it promises.",
     "A 30 ml vitamin C serum at 15% strength for dull, uneven skin. Water-light, no oil."),
    ("Who it is for", "essential",
     "Lets her talk to a person instead of a crowd. Name the situation people recognise "
     "themselves in, not an age bracket.",
     "People whose skin looks tired by mid-afternoon and who cannot stand sticky textures."),
    ("Why someone would buy it", "recommended",
     "The strongest single reason, in your own words. This becomes the line the script leans on, "
     "so a specific claim carries the pitch and a vague one wastes it.",
     "Visible brightening in about four weeks, without the sting most vitamin C causes."),
    ("Honest drawbacks, or who it is NOT for", "recommended",
     "The honest-review angle needs something real to weigh against, and if you do not give it "
     "one the writer invents its own. Left blank on a trading bot, it volunteered “their user "
     "interface could use some work” — nobody told it that. A true drawback here is not just "
     "more honest, it is what stops a made-up one taking its place.",
     "The scent is strong for the first minute. Not for very sensitive or broken skin."),
    ("Price", "optional — but read the rules",
     "Write it as you would say it, with the currency. Left out, no price can be spoken at all: "
     "the script simply works around it rather than guessing.",
     "NT$1,280, about US$39"),
    ("Where to buy", "optional — same rule",
     "A link is treated exactly like a price. If it is not here, none can be said.",
     "https://glowlab.example/serum"),
    ("Category", "helps",
     "A word or two. It sets the register she speaks in — a serum and a power tool are not sold "
     "in the same voice.",
     "skincare, serum"),
]

TEMPLATE = """Product name:
Category:
What it is:
Who it is for:
Why someone would buy it:
Honest drawbacks, or who it is NOT for:
Price:
Where to buy:"""


def handbook_inner(with_fill: bool) -> str:
    """The handbook itself, shared by the dialog and the standalone page."""
    flds = "\n".join(
        f'<div class="fld"><span class="n">{esc(n)}</span>'
        f'<span class="need">{esc(need)}</span>'
        f'<p class="d">{esc(why)}</p><p class="ex">{esc(ex)}</p></div>'
        for n, need, why, ex in FIELD_GUIDE)
    foot = ('<button type="button" id="hb-fill">Put this template in the form</button>'
            '<button type="button" class="sec" id="hb-close">Close</button>'
            if with_fill else '<a class="hbbtn" href="/">&larr; back to the demo</a>')
    return f"""<div class="hb">
  <h3>What to write about the product</h3>
  <p class="lead">You can paste a product page, or type it out yourself. Either way these are the
     things worth saying — and what happens when you leave one out.</p>
  {flds}
  <div class="rules"><b>Three rules that decide what the script may say</b>
    <ul>
      <li>Anything you leave blank counts as unknown, and unknown is unsayable. It is not a gap
          the writer fills in — the checker strips it out.</li>
      <li>Prices and links are compared against your own words, character by character. A number
          you did not type is dropped even when the model states it confidently: given a product
          description with no price at all, it produced “$29.99” on three runs out of three.</li>
      <li>Guaranteed profit, guaranteed returns and risk-free investment are never spoken, even
          if you write them in yourself.</li>
    </ul>
  </div>
  <p class="lead" style="margin:15px 0 0">The template is only a reminder — loose notes work just
     as well. Fill in what you know and leave the rest empty.</p>
  <pre class="tpl" id="hb-tpl">{esc(TEMPLATE)}</pre>
  <div class="hbfoot">{foot}</div>
</div>"""


def handbook_page() -> bytes:
    return (f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>What to write &mdash; Studio demo</title><style>{CSS}</style></head><body>
<div class="w"><h1>Product handbook</h1>
<p class="sub">The same guide the demo page shows, as its own page.</p>
<div class="out" style="border-left-color:var(--acc);padding:0">{handbook_inner(False)}</div>
</div></body></html>""").encode("utf-8")


def characters():
    try:
        from voice_studio import characters as ch
        return ch()
    except Exception:
        return []


def up(url: str) -> bool:
    import urllib.request
    try:
        urllib.request.urlopen(url, timeout=1.5)
        return True
    except Exception:
        return False


def voice_options(sel: str = "") -> str:
    out = []
    for c in characters():
        cid = c.get("id", "")
        s = " selected" if cid == sel else ""
        out.append(f'<option value="{esc(cid)}"{s}>{esc(c.get("name", cid))} — '
                   f'{esc(c.get("lang", ""))}</option>')
    return "\n".join(out) or '<option value="">(no voices)</option>'


def sell_row(pfx: str) -> str:
    """Voice, angle and length — the three choices both selling forms need."""
    return f"""<div class="row">
    <div><label for="{pfx}v">Voice</label>
      <select id="{pfx}v" name="voice">{voice_options()}</select></div>
    <div><label for="{pfx}a">Angle</label>
      <select id="{pfx}a" name="angle">
        <option value="honest" selected>honest review</option>
        <option value="hook">scroll-stopping hook</option>
        <option value="problem">problem then solution</option>
        <option value="demo">talking through using it</option>
      </select></div>
    <div><label for="{pfx}s">Length</label>
      <select id="{pfx}s" name="seconds">
        <option value="10">10 seconds</option><option value="15" selected>15 seconds</option>
        <option value="25">25 seconds</option>
      </select></div>
  </div>"""


def player(clip: str, said: str, meta: str) -> str:
    """One result, with the three live controls attached."""
    pid = "p" + uuid.uuid4().hex[:6]
    return f"""<div class="out">
  <div class="said">{esc(said)}</div>
  <audio id="{pid}" controls src="/media/{esc(clip)}"></audio>
  <div class="ctl">
    <div class="hd">live controls — these change playback, not the file</div>
    <div class="slider"><span>volume</span>
      <input type="range" id="{pid}-vol" min="0" max="100" value="100">
      <span class="v" id="{pid}-volv">100%</span></div>
    <div class="slider"><span>speed&nbsp;</span>
      <input type="range" id="{pid}-spd" min="50" max="200" value="100" step="5">
      <span class="v" id="{pid}-spdv">1.00x</span></div>
    <div class="btns">
      <button type="button" id="{pid}-play">Play</button>
      <button type="button" id="{pid}-stop">Stop</button>
      <button type="button" id="{pid}-restart">Restart</button>
    </div>
  </div>
  <div class="meta" style="margin-top:10px">{meta}</div>
  <div class="path">{esc(CLIPS / clip)}</div>
  <script>ctl("{pid}");</script>
</div>"""


def page(body: str = "", **keep) -> bytes:
    svc = " ".join(
        f'<span>{n}: {"up" if u else "down"}</span>' for n, u in [
            ("GPT-SoVITS", up("http://127.0.0.1:9880/docs")),
            ("CosyVoice", up("http://127.0.0.1:9881/health")),
            ("Ollama", up("http://127.0.0.1:11434/api/tags"))])
    text = keep.get("text") or "Honestly, this is my favourite thing I have tried all month."
    product = keep.get("product") or ""
    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Studio demo</title><style>{CSS}</style><script>{JS}</script></head><body><div class="w">

<h1>Studio demo</h1>
<p class="sub">Three jobs, three controls. Everything runs locally.</p>
<div class="svc">{svc}</div>

{body}

<h2><b>1</b>Text to speech</h2>
<p class="note">Volume and speed here are baked into the file. The live sliders on the result
   change playback only — both are worth having, and they are not the same thing.</p>
<form method="post" action="/say">
  <label for="t">Text</label>
  <textarea id="t" name="text" rows="3">{esc(text)}</textarea>
  <div class="row">
    <div><label for="v">Voice</label><select id="v" name="voice">{voice_options()}</select></div>
    <div><label for="sp">Render speed</label>
      <select id="sp" name="speed">
        <option value="0.8">0.8&times;</option><option value="0.9">0.9&times;</option>
        <option value="1.0" selected>1.0&times;</option>
        <option value="1.15">1.15&times;</option><option value="1.3">1.3&times;</option>
      </select></div>
    <div><label for="vo">Render volume</label>
      <select id="vo" name="volume_db">
        <option value="-6">&minus;6 dB quieter</option>
        <option value="-3">&minus;3 dB</option>
        <option value="0" selected>unchanged</option>
        <option value="3">+3 dB</option><option value="6">+6 dB louder</option>
      </select></div>
  </div>
  <button type="submit">Speak it</button>
</form>

<h2><b>2</b>Voice clone</h2>
<p class="note">Upload five to fifteen seconds of any voice. The clip is separated from its
   background and levelled first — cloning from a noisy reference scored 0.4474 against the
   speaker, and from the cleaned version 0.8704.</p>
<form method="post" action="/clone" enctype="multipart/form-data">
  <label for="ref">Reference clip</label>
  <input type="file" id="ref" name="ref" accept="audio/*">
  <label for="ct">What should that voice say</label>
  <textarea id="ct" name="text" rows="2">This is my voice, cloned from a short clip.</textarea>
  <button type="submit">Clone and speak</button>
</form>

<h2><b>3</b>Selling a product</h2>
<p class="note">Paste a product page, a spec sheet or your own notes — or open the handbook and drop
   its template in to fill out. The facts get pulled from whatever you write, and anything the
   extractor invents on the way, a price or a link, is checked against your own words and thrown
   out. What you did not write cannot be said.</p>
<form method="post" action="/sell">
  <div class="lblrow"><label for="pi">Product information</label>
    <a class="hbbtn" href="/handbook" id="hb-open">What should I write? &rarr;</a></div>
  <textarea id="pi" name="product" rows="8"
    placeholder="Paste the product page or your own notes — or open the handbook above for a template to fill in…">{esc(product)}</textarea>
  {sell_row("p")}
  <button type="submit">Write it and speak it</button>
</form>

<footer>CosyVoice 2 + GPT-SoVITS &middot; clips kept in {esc(CLIPS)}</footer>
</div>
<dialog id="hb">{handbook_inner(True)}</dialog>
</body></html>"""
    return doc.encode("utf-8")


def error(what: str, detail: str, tb: str = "") -> str:
    extra = f"<pre>{esc(tb)}</pre>" if tb else ""
    return f'<div class="err"><b>{esc(what)}</b><br>{esc(detail)}{extra}</div>'


def parse_multipart(body: bytes, ctype: str) -> dict:
    if "boundary=" not in ctype:
        return {}
    sep = b"--" + ctype.split("boundary=", 1)[1].strip().strip('"').encode()
    out: dict = {}
    for part in body.split(sep):
        head, _, payload = part.partition(b"\r\n\r\n")
        if not _:
            continue
        h = head.decode("utf-8", "replace")
        name = None
        for tok in h.split(";"):
            tok = tok.strip()
            if tok.startswith("name="):
                name = tok[5:].strip().strip('"').split("\r\n")[0]
        if name:
            out[name] = payload.rstrip(b"\r\n")
    return out


class Handler(BaseHTTPRequestHandler):
    server_version = "StudioDemo/1.0"
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
        p = urllib.parse.urlparse(self.path).path
        if p == "/":
            self._send(page(), "text/html; charset=utf-8")
        elif p == "/handbook":
            self._send(handbook_page(), "text/html; charset=utf-8")
        elif p == "/ping":
            self._send(b"studio demo is reachable", "text/plain; charset=utf-8")
        elif p.startswith("/media/"):
            f = CLIPS / Path(urllib.parse.unquote(p[7:])).name
            if not f.is_file():
                self._send(b"no such clip", "text/plain; charset=utf-8", 404)
                return
            self._send(f.read_bytes(), "audio/wav")
        else:
            self._send(b"not found", "text/plain; charset=utf-8", 404)

    def do_POST(self):
        p = urllib.parse.urlparse(self.path).path
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        ctype = self.headers.get("Content-Type", "")
        form = (parse_multipart(raw, ctype) if ctype.startswith("multipart/")
                else {k: v[0].encode() for k, v in
                      urllib.parse.parse_qs(raw.decode("utf-8")).items()})
        g = lambda k, d="": form.get(k, b"").decode("utf-8", "replace") or d
        try:
            if p == "/say":
                self._say(g)
            elif p == "/clone":
                self._clone(form, g)
            elif p == "/sell":
                self._sell(g)
            else:
                self._send(b"not found", "text/plain; charset=utf-8", 404)
        except Exception as exc:
            self._send(page(error(type(exc).__name__, str(exc),
                                  traceback.format_exc()[-600:]),
                            text=g("text"), product=g("product")),
                       "text/html; charset=utf-8")

    def _new(self, tag: str) -> Path:
        return CLIPS / f"{datetime.now():%H%M%S}-{tag}-{uuid.uuid4().hex[:4]}.wav"

    def _say(self, g):
        from voice_studio import synthesize
        text = g("text").strip()
        if not text:
            self._send(page(error("Nothing to say", "Type some text first.")),
                       "text/html; charset=utf-8")
            return
        out = self._new("tts")
        t = time.perf_counter()
        synthesize(g("voice", "sofia-hsu"), text, out=out,
                   speed=float(g("speed", "1.0")), volume_db=float(g("volume_db", "0")))
        meta = (f"<span><b>{time.perf_counter()-t:.1f}</b> s</span>"
                f"<span>{out.stat().st_size/1024:.0f} KB</span>"
                f"<span>rendered at {g('speed','1.0')}&times;, {g('volume_db','0')} dB</span>")
        self._send(page(player(out.name, text, meta), text=text), "text/html; charset=utf-8")

    def _clone(self, form, g):
        from voice_studio import synthesize, transcribe
        import clean_ref as CR
        blob = form.get("ref") or b""
        text = g("text").strip()
        if len(blob) < 2000:
            self._send(page(error("No reference clip", "Pick five to fifteen seconds of audio.")),
                       "text/html; charset=utf-8")
            return
        src = UPLOADS / f"ref-{uuid.uuid4().hex[:6]}.wav"
        src.write_bytes(blob)
        t = time.perf_counter()
        work = UPLOADS / f"w{uuid.uuid4().hex[:6]}"
        work.mkdir(parents=True, exist_ok=True)
        try:
            vocals = CR.separate(src, work)
            cleaned = work / "clean.wav"
            CR.normalise(vocals, cleaned, -16.0)
            ref, note = cleaned, "cleaned"
        except Exception:
            ref, note = src, "as supplied"
        heard, _ = transcribe(ref, None)
        out = self._new("clone")
        synthesize("", text, out=out, ref_audio=str(ref), ref_text=heard)
        meta = (f"<span><b>{time.perf_counter()-t:.1f}</b> s</span><span>{note}</span>"
                f"<span>reference heard as: {esc(heard[:52])}</span>")
        self._send(page(player(out.name, text, meta)), "text/html; charset=utf-8")

    def _sell(self, g):
        from sell import write_sales_script
        from voice_studio import synthesize
        info = g("product").strip()
        if not info:
            self._send(page(error("No product information", "Paste something about it first.")),
                       "text/html; charset=utf-8")
            return
        t = time.perf_counter()
        r = write_sales_script(g("voice", "sofia-hsu"), info,
                               angle=g("angle", "honest"), seconds=int(g("seconds", "15")))
        out = self._new("sell")
        synthesize(g("voice", "sofia-hsu"), r["script"], out=out)
        known = [k for k, v in r["facts"].items() if v and not k.startswith("__")]
        # Worth surfacing rather than hiding: when this line is non-empty the extractor invented
        # a price or a link and verification threw it away. That is the handbook's second rule
        # visibly doing its job, and it is the moment a user learns to type the number in.
        binned = "".join(f'<span style="color:var(--bad)">discarded: {esc(d)}</span>'
                         for d in (r.get("dropped") or []))
        meta = (f"<span><b>{time.perf_counter()-t:.1f}</b> s</span>"
                f"<span>angle: {esc(r['angle'])}</span>"
                f"<span>used: {esc(', '.join(known)) or 'nothing'}</span>"
                f"<span>not stated: {esc(', '.join(r['unstated'])) or 'none'}</span>{binned}")
        self._send(page(player(out.name, r["script"], meta), product=info),
                   "text/html; charset=utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8776)
    args = ap.parse_args()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Studio demo -> http://{args.host}:{args.port}")
    print(f"clips -> {CLIPS}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
