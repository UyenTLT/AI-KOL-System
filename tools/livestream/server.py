#!/usr/bin/env python3
"""A live stream Sofia can hold on her own: comments come in, she reads them out and answers.

    post a comment as a viewer      it joins the queue, with your name on it
    Sofia answers the next one      she picks the register herself and speaks the reply
    ask for a song                  she writes original lines and performs them

The register is chosen from the message rather than from a dropdown, because on a real stream
nobody labels their comment before sending it. A song request gets performed, someone opening
up gets the quiet voice, everything else gets the lively one. The dropdown is still there to
force a mode when demonstrating.

Everything is a plain form POST. A live stream is exactly the kind of page where a broken
script would otherwise leave a blank screen, and on this machine that has happened enough times
to be worth designing against — the only JavaScript here starts playback of the newest clip,
and without it the audio element still has its own controls.

    .venv\\Scripts\\python.exe tools\\livestream\\server.py        # :8777
"""
from __future__ import annotations

import argparse
import html
import json
import os
import sys
import threading
import time
import traceback
import urllib.parse
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
for sub in ("studio", "livetalking", "voice_eval", "livestream"):
    sys.path.insert(0, str(REPO / "tools" / sub))

CLIPS = Path(os.getenv("KOL_STREAM_DIR") or (REPO / "renders" / "livestream"))
CLIPS.mkdir(parents=True, exist_ok=True)

KOL = os.getenv("KOL_ID", "sofia-vargas")

# The whole stream, newest last. Kept in memory on purpose: this is a demo stage, and a stream
# that survives a restart would only make it harder to start a clean one for the next person.
LOCK = threading.Lock()
PENDING: list[dict] = []
EVENTS: list[dict] = []

# Answers rendered before anyone asked for them.
#
# Measured, the wait is not the thinking: the language model takes 0.8 s and the voice takes
# 6.8 s, so 89% of it is synthesis. But synthesis runs at RTF 0.54-0.68 — she produces audio
# faster than it can be listened to — which means that while one answer is playing there is idle
# capacity to render the next one. A stream is a queue, so the next comment is almost always
# already known.
#
# This does not make synthesis faster. It moves it off the moment somebody is waiting.
PREPARED: list[dict] = []
PREFETCH_DEPTH = 2

# When on, she works through the queue herself instead of waiting to be clicked. The rendering
# was already happening ahead of time; this is only about who decides when it gets shown.
#
# The page holds one back until the current clip has finished playing. Without that she talks
# over herself — a stream where every answer cuts off the last one is worse than one that waits.
AUTO = {"on": True}

CSS = """
:root{--bg:#EFF2F2;--card:#FFF;--card2:#E7ECEC;--ink:#111719;--tx:#1B2426;--mut:#5A6A6C;
 --faint:#8A9899;--rule:#D2DADA;--acc:#0E6E68;--accdim:#0E6E680F;--bad:#B04352;--ok:#3C7F55;
 --fan:#4A5C8A;--fandim:#4A5C8A12}
@media (prefers-color-scheme:dark){:root{--bg:#0D1214;--card:#141B1D;--card2:#1D2628;
 --ink:#E8EDED;--tx:#DAE2E2;--mut:#96A5A6;--faint:#6E7D7E;--rule:#263133;--acc:#4FB3A8;
 --accdim:#4FB3A814;--bad:#D0707C;--ok:#5FA97A;--fan:#8FA3D4;--fandim:#8FA3D41A}}
*,*::before,*::after{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--tx);
 font:16px/1.6 "Segoe UI Variable Text","Segoe UI",system-ui,-apple-system,sans-serif}
.w{max-width:800px;margin:0 auto;padding:34px 20px 70px}
h1{font-family:Cambria,Georgia,serif;font-size:30px;margin:0 0 3px;color:var(--ink)}
h1 .dot{display:inline-block;width:9px;height:9px;border-radius:50%;background:var(--bad);
 margin-right:10px;vertical-align:3px}
.sub{color:var(--mut);font-size:15px;margin:0 0 8px}
.svc{display:flex;gap:14px;flex-wrap:wrap;font-family:Consolas,monospace;font-size:11.5px;
 color:var(--faint);border-top:1px solid var(--rule);padding-top:10px;margin-top:12px}
form{background:var(--card);border:1px solid var(--rule);border-radius:12px;padding:15px 17px;
 margin:20px 0 8px}
label{display:block;font-size:11.5px;letter-spacing:.06em;text-transform:uppercase;
 color:var(--faint);font-weight:600;margin:11px 0 5px}
label:first-of-type{margin-top:0}
input[type=text],textarea,select{width:100%;font:inherit;font-size:15px;padding:9px 11px;
 border:1px solid var(--rule);border-radius:8px;background:var(--bg);color:var(--ink)}
textarea{resize:vertical}
.row{display:flex;gap:12px;flex-wrap:wrap;align-items:flex-end}
.row>div{flex:1;min-width:140px}
button{font:inherit;font-size:15px;font-weight:600;padding:10px 20px;border:1px solid var(--acc);
 border-radius:8px;background:var(--acc);color:#fff;cursor:pointer;margin-top:13px}
button:hover{filter:brightness(1.08)}
button.sec{background:var(--card);color:var(--acc);border-color:var(--rule)}
button:disabled{opacity:.45;cursor:not-allowed}
.bar{display:flex;gap:9px;align-items:center;flex-wrap:wrap;margin:0 0 6px}
.bar form{margin:0;padding:0;border:0;background:none}
.bar button{margin:0}
.queue{background:var(--fandim);border:1px solid var(--rule);border-radius:12px;padding:12px 15px;
 margin:8px 0 0}
.queue .hd{font-family:Consolas,monospace;font-size:11px;letter-spacing:.07em;
 text-transform:uppercase;color:var(--fan);font-weight:600;margin-bottom:7px}
.queue ol{margin:0;padding-left:20px;font-size:14.5px}
.queue li{margin:3px 0}
.queue .who{color:var(--fan);font-weight:600}
h2{font-family:Cambria,Georgia,serif;font-size:19px;margin:30px 0 10px;color:var(--ink)}
.turn{border-left:2px solid var(--rule);padding:0 0 0 15px;margin:0 0 20px}
.fan{color:var(--mut);font-size:15px;margin:0 0 9px}
.fan b{color:var(--fan)}
.her{background:var(--card);border:1px solid var(--rule);border-radius:12px;padding:14px 16px}
.her .said{font-size:16px;color:var(--ink);white-space:pre-wrap;margin:0 0 10px}
.badge{font-family:Consolas,monospace;font-size:10.5px;letter-spacing:.06em;text-transform:uppercase;
 color:var(--acc);border:1px solid var(--acc);border-radius:20px;padding:1px 9px;margin-right:8px}
.badge.song{color:var(--fan);border-color:var(--fan)}
audio{width:100%;margin:2px 0 8px}
.meta{font-family:Consolas,monospace;font-size:11.5px;color:var(--faint);display:flex;gap:13px;
 flex-wrap:wrap}
.note{color:var(--mut);font-size:13.5px;margin:8px 0 0}
.warn{background:var(--card2);border-radius:9px;padding:11px 14px;margin:10px 0 0;font-size:13.5px;
 color:var(--mut)}
.warn b{color:var(--ink)}
.err{background:var(--card);border:1px solid var(--rule);border-left:3px solid var(--bad);
 border-radius:12px;padding:15px 17px;margin:14px 0;color:var(--bad);font-size:14.5px}
.err pre{white-space:pre-wrap;font-size:11.5px;color:var(--mut);margin:8px 0 0}
.empty{color:var(--faint);font-size:14.5px;font-style:italic}
footer{margin-top:32px;padding-top:12px;border-top:1px solid var(--rule);
 font-family:Consolas,monospace;font-size:11.5px;color:var(--faint)}
"""

# The newest clip plays by itself. Browsers block autoplay with sound until the page has been
# interacted with, and the click that submitted the form does not always carry over the reload,
# so a rejected play() is expected rather than exceptional — the element keeps its own controls
# and the caption tells the viewer to press play.
JS = """
document.addEventListener('DOMContentLoaded', function(){
  // Every audio element holds the whole answer as a list of sentence clips. Playing them in
  // turn is what lets the server hand over the first one before the last one exists — the
  // listener hears a continuous answer, and the rendering finishes behind it.
  var players = document.querySelectorAll('audio[data-clips]');
  Array.prototype.forEach.call(players, function(el){
    var clips = (el.getAttribute('data-clips') || '').split(' ').filter(Boolean);
    var stem = el.getAttribute('data-stem') || '';
    var at = 0;
    function advance(){
      if(at >= clips.length) return false;
      el.src = '/media/' + clips[at];
      var q = el.play();
      if(q && q.catch) q.catch(function(){});
      return true;
    }
    el.addEventListener('ended', function(){
      at += 1;
      if(advance()) return;
      // Ran off the end of what the page was given. The rest of the answer is still being
      // rendered behind this, so ask for it, and keep asking until the server says it has
      // finished. Synthesis runs faster than speech, so this is a formality rather than a
      // race — but a stall here would be heard as her stopping mid-answer.
      if(!stem) return;
      var tries = 0;
      var poll = setInterval(function(){
        tries += 1;
        fetch('/clips?stem=' + encodeURIComponent(stem)).then(function(r){ return r.json(); })
          .then(function(s){
            if(s.clips && s.clips.length > clips.length){
              clips = s.clips;
              clearInterval(poll);
              advance();
            } else if(s.done || tries > 60){
              clearInterval(poll);
            }
          }).catch(function(){ clearInterval(poll); });
      }, 400);
    });
    el.addEventListener('play', function(){
      // Restarting from the controls should restart the answer, not the last sentence of it.
      if(el.ended && at >= clips.length && clips.length){
        at = 0; el.src = '/media/' + clips[0];
      }
    });
  });

  var a = document.getElementById('latest');
  if(a){
    var p = a.play();
    if(p && p.catch) p.catch(function(){
      var n = document.getElementById('latest-note');
      if(n) n.textContent = 'press play — the browser blocked autoplay';
    });
  }
  // Auto mode. The server has already spoken the next answer; this only decides when to show
  // it, and the rule is: not while she is still talking. Reloading mid-clip cuts her off, so
  // the page waits for the current audio to end (or for the viewer never to have started it).
  var auto = document.body.getAttribute('data-auto') === '1';
  if(!auto) return;
  var seen = parseInt(document.body.getAttribute('data-events') || '0', 10);
  var timer = setInterval(function(){
    fetch('/state').then(function(r){ return r.json(); }).then(function(s){
      if(!s.auto || s.events <= seen) return;
      var busy = a && !a.paused && !a.ended;
      if(busy) return;
      clearInterval(timer);
      location.reload();
    }).catch(function(){});
  }, 1500);
});
"""


def esc(s) -> str:
    return html.escape(str(s), quote=True)


def up(url: str) -> bool:
    import urllib.request
    try:
        urllib.request.urlopen(url, timeout=1.5)
        return True
    except Exception:
        return False


def history_for(who: str | None = None, limit: int = 4) -> list:
    """Earlier turns with THIS person, so a follow-up resolves and a stranger's does not.

    It used to return the last few turns from anyone. On a stream that is wrong in a way that
    produces exactly the complaint it was meant to fix: An asked where a jacket was from, then
    Mai said her skin was a mess from night shifts, and the reply came back "at least the jacket
    keeps me warm on those late nights". Two different people, one conversation, and an answer
    that belonged to neither.

    A chat is one continuous thread. A stream is many, interleaved — and the only turns that
    belong in the context are the ones from the person being answered.
    """
    if not who:
        return []
    msgs = []
    for e in EVENTS:
        if (e.get("who") or "").strip().lower() != who.strip().lower():
            continue
        msgs.append({"role": "user", "content": e["fan_text"]})
        msgs.append({"role": "assistant", "content": e["text"]})
    return msgs[-limit * 2:]


def answer(c: dict, hist: list) -> dict:
    """Turn one comment into a finished event: her words, and a clip of her saying them.

    Deliberately free of request handling so the prefetch thread and a direct click run exactly
    the same path — a fast route that behaves differently from the slow one is a bug generator.
    """
    import shutil
    from stage import (respond, perform, perform_streamed, song_for, classify,
                       strip_tics, fix_vocative, MODES)

    mode = c.get("mode") or classify(c["text"])
    t = time.perf_counter()

    # A song request may already exist as audio. A track from the library is a real sung
    # recording converted into her voice, so there is nothing to synthesise — synthesising it
    # would replace singing with speech, which is the thing this path exists to avoid.
    sung = song_for(KOL, c["text"]) if mode == "song" else None
    if sung and sung["kind"] == "library":
        clip = f"{datetime.now():%H%M%S}-sung-{uuid.uuid4().hex[:4]}.wav"
        shutil.copy(sung["audio"], CLIPS / clip)
        label = f"singing — {sung['title']}"
        if sung.get("rights") != "commercial":
            label += "  ·  INTERNAL ONLY, do not publish"
        return {"who": c["who"], "fan_text": c["text"], "text": sung["text"], "mode": "song",
                "label": label, "clip": clip, "think": time.perf_counter() - t, "speak": 0.0,
                "at": f"{datetime.now():%H:%M:%S}"}

    text = sung["text"] if sung else respond(KOL, c["text"], mode, history=hist, asker=c.get("who"))[0]
    # The same cleanup the chat has had for a while. It was never wired in here, which is why
    # the stream still signed off with "thanks for asking" long after the chat had stopped.
    text, misnamed = fix_vocative(text, c.get("who"), KOL)
    text, removed = strip_tics(text, first_message=not EVENTS, message=c.get("text", ""))
    removed += [f"called them {n}" for n in misnamed]
    if removed:
        print(f"  stripped: {removed}", flush=True)
    think = time.perf_counter() - t

    stem = f"{datetime.now():%H%M%S}-{mode}-{uuid.uuid4().hex[:4]}"
    clip, clips, first_at = "", [], 0.0
    t = time.perf_counter()
    speak = 0.0
    ev_ref = {"clips": clips}
    try:
        # Render the opening sentence, hand it over, and finish the rest behind it.
        #
        # Rendering all of them first and only then responding measures the improvement without
        # delivering it: the page would show "first words in 1.7 s" while the listener waited
        # the full 13.9 s for the response to arrive. The point is the handover, not the split.
        gen = perform_streamed(KOL, text, mode, CLIPS, stem)
        clip = next(gen)
        clips.append(clip)
        first_at = time.perf_counter() - t

        def rest():
            try:
                for name in gen:
                    with LOCK:
                        clips.append(name)
            except Exception as exc:
                print(f"  rest of the answer failed: {exc}", flush=True)
            finally:
                with LOCK:
                    ev_ref["done"] = True

        threading.Thread(target=rest, daemon=True).start()
        speak = first_at
    except StopIteration:
        ev_ref["done"] = True
    except Exception as exc:
        # Losing the audio should not lose what she said — the transcript is still the useful
        # half, and a stream that blanks out because the voice server hiccuped is worse than one
        # that keeps talking silently.
        clip = ""
        print(f"  voice failed: {exc}", flush=True)

    return {"who": c["who"], "fan_text": c["text"], "text": text, "mode": mode,
            "label": MODES[mode]["label"], "clip": clip, "clips": clips, "think": think,
            "speak": speak, "first_at": first_at, "stem": stem,
            "done": ev_ref.get("done", False), "at": f"{datetime.now():%H:%M:%S}"}


def prefetch_worker() -> None:
    """Render answers ahead of the click, whenever there is a queue and idle capacity."""
    while True:
        with LOCK:
            busy = len(PREPARED) >= PREFETCH_DEPTH or not PENDING
            c = None if busy else PENDING.pop(0)
            # c is None whenever the queue is empty, which is most of the time — asking it for a
            # name there killed the worker thread on its first idle tick and left every comment
            # sitting in the queue with nothing to process it.
            hist = history_for(c.get("who")) if c else []
        if c is None:
            time.sleep(0.4)
            continue
        try:
            ev = answer(c, hist)
        except Exception as exc:
            print(f"  prefetch failed: {exc}", flush=True)
            continue
        with LOCK:
            # In auto mode the prepared answer goes straight onto the stream. The page decides
            # WHEN to show it, so nothing here has to know about playback.
            (EVENTS if AUTO["on"] else PREPARED).append(ev)


def page(body: str = "", **keep) -> bytes:
    from stage import MODES, brain_label
    svc = " ".join(
        f'<span>{n}: {"up" if u else "down"}</span>' for n, u in [
            ("CosyVoice", up("http://127.0.0.1:9881/health")),
            ("Ollama", up("http://127.0.0.1:11434/api/tags"))])

    with LOCK:
        pending = list(PENDING)
        events = list(EVENTS)
        prepared = list(PREPARED)
        auto_on = AUTO["on"]

    # Two different states, and the difference is the whole point: one is a comment she has not
    # looked at, the other is an answer already spoken and waiting to be played.
    ready = "".join(f'<li><span class="who">{esc(p["who"])}</span> {esc(p["fan_text"])}'
                    f' &nbsp;<b style="color:var(--ok)">ready</b></li>' for p in prepared)
    items = "\n".join(f'<li><span class="who">{esc(c["who"])}</span> {esc(c["text"])}</li>'
                      for c in pending)
    if prepared or pending:
        queue = (f'<div class="queue"><div class="hd">queue &mdash; {len(prepared)} rendered, '
                 f'{len(pending)} still to do</div><ol>{ready}{items}</ol></div>')
    else:
        queue = ('<div class="queue"><div class="hd">queue &mdash; empty</div>'
                 '<span class="empty">nothing waiting</span></div>')

    turns = []
    for i, e in enumerate(reversed(events)):
        newest = (i == 0)
        aid = ' id="latest"' if newest else ""
        note = ('<div class="meta" id="latest-note"></div>' if newest else "")
        cls = " song" if e["mode"] == "song" else ""
        # The reply is rendered a sentence at a time so the first one can be heard while the
        # rest is still being made, so the element carries the whole list and the script walks
        # it. One <audio> rather than several: several would show a row of players for what the
        # listener experiences as one answer.
        rest = " ".join(e.get("clips") or [])
        clip = (f'<audio{aid} controls src="/media/{esc(e["clip"])}" '
                f'data-clips="{esc(rest)}" data-stem="{esc(e.get("stem", ""))}"></audio>'
                if e.get("clip") else '<div class="empty">no audio for this turn</div>')
        turns.append(f"""<div class="turn">
  <p class="fan"><b>{esc(e["who"])}</b> &nbsp;{esc(e["fan_text"])}</p>
  <div class="her">
    <div class="said">{esc(e["text"])}</div>
    {clip}{note}
    <div class="meta"><span class="badge{cls}">{esc(e["label"])}</span>
      <span>thought in {e["think"]:.1f}s</span><span>first words in {e.get("first_at", e["speak"]):.1f}s</span><span>spoke in {e["speak"]:.1f}s</span>
      <span>{esc(e["at"])}</span></div>
  </div>
</div>""")
    transcript = "\n".join(turns) or '<p class="empty">Nothing said yet. Post a comment below.</p>'

    opts = "".join(f'<option value="{k}">{esc(v["label"])}</option>' for k, v in MODES.items())
    who = keep.get("who") or "guest"
    n = len(pending) + len(prepared)

    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sofia — live</title><style>{CSS}</style><script>{JS}</script></head>
<body data-auto="{1 if auto_on else 0}" data-events="{len(events)}"><div class="w">

<h1><span class="dot"></span>Sofia &mdash; live</h1>
<p class="sub">Comments come in, she reads them out and answers. Everything runs on this machine.</p>
<div class="svc">{svc}</div>

{body}

<form method="post" action="/comment">
  <div class="row">
    <div style="flex:0 0 190px"><label for="who">Your name</label>
      <input type="text" id="who" name="who" value="{esc(who)}"></div>
    <div><label for="mode">Register</label>
      <select id="mode" name="mode">
        <option value="">let her decide</option>{opts}
      </select></div>
  </div>
  <label for="text">Comment</label>
  <textarea id="text" name="text" rows="2"
    placeholder="Ask her something, tell her about your day, or ask for a song…"></textarea>
  <button type="submit">Post comment</button>
</form>

{queue}

<div class="bar" style="margin-top:14px">
  <form method="post" action="/auto">
    <button type="submit">{"Auto: on — she answers by herself" if auto_on else "Auto: off"}</button>
  </form>
  <form method="post" action="/next">
    <button type="submit" class="sec"{" disabled" if not n else ""}>Answer the next one now</button>
  </form>
  <form method="post" action="/reset"><button type="submit" class="sec">Clear stream</button></form>
</div>
<p class="note">{"She works through the queue on her own, waiting for each answer to finish before starting the next. Post a comment and she replies without being asked." if auto_on else "Nothing is spoken until you ask for it."}
   She picks the register from the comment itself; the dropdown only forces one for a demo.</p>

<h2>Stream</h2>
{transcript}

<div class="warn"><b>About the singing.</b> The voice engine has no pitch or melody control, so
  this is melodic recitation, not song &mdash; measured, asking it to sing narrows its pitch
  range from 17.50 semitones to 10.06 rather than widening it. The words are always original:
  a request naming a real song is answered with her own lines about the same feeling, never
  with that song's words.</div>

<footer>persona brain: {esc(brain_label())} &middot; voice: CosyVoice 2 instruct &middot;
  clips in {esc(CLIPS)}</footer>
</div></body></html>"""
    return doc.encode("utf-8")


def error(what: str, detail: str, tb: str = "") -> str:
    extra = f"<pre>{esc(tb)}</pre>" if tb else ""
    return f'<div class="err"><b>{esc(what)}</b><br>{esc(detail)}{extra}</div>'


class Handler(BaseHTTPRequestHandler):
    server_version = "SofiaLive/1.0"
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

    def _redirect(self):
        self.send_response(303)
        self.send_header("Location", "/")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        p = urllib.parse.urlparse(self.path).path
        if p == "/":
            self._send(page(), "text/html; charset=utf-8")
        elif p == "/state":
            with LOCK:
                body = json.dumps({"events": len(EVENTS), "pending": len(PENDING),
                                   "prepared": len(PREPARED), "auto": AUTO["on"]})
            self._send(body.encode(), "application/json")
        elif p == "/clips":
            # The rest of an answer arrives after the page has already been served, so the
            # player asks for the list again when it runs off the end of what it was given.
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            stem = (q.get("stem") or [""])[0]
            with LOCK:
                ev = next((e for e in EVENTS if e.get("stem") == stem), None)
                body = json.dumps({"clips": list(ev["clips"]) if ev else [],
                                   "done": bool(ev and ev.get("done"))})
            self._send(body.encode(), "application/json")
        elif p == "/ping":
            self._send(b"sofia live is reachable", "text/plain; charset=utf-8")
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
        form = {k: v[0] for k, v in urllib.parse.parse_qs(raw.decode("utf-8")).items()}
        g = lambda k, d="": form.get(k, "") or d
        try:
            if p == "/comment":
                self._comment(g)
            elif p == "/next":
                self._next()
            elif p == "/auto":
                with LOCK:
                    AUTO["on"] = not AUTO["on"]
                self._redirect()
            elif p == "/reset":
                with LOCK:
                    PENDING.clear()
                    EVENTS.clear()
                self._redirect()
            else:
                self._send(b"not found", "text/plain; charset=utf-8", 404)
        except Exception as exc:
            self._send(page(error(type(exc).__name__, str(exc),
                                  traceback.format_exc()[-700:])),
                       "text/html; charset=utf-8")

    def _comment(self, g):
        text = g("text").strip()
        if not text:
            self._send(page(error("Empty comment", "Type something first.")),
                       "text/html; charset=utf-8")
            return
        with LOCK:
            PENDING.append({"who": g("who", "guest").strip() or "guest",
                            "text": text, "mode": g("mode") or None})
        self._redirect()

    def _next(self):
        """Show the next answer — already rendered if the prefetch thread got there first.

        Nothing that touches the socket or builds a page happens while LOCK is held. `page()`
        takes the same lock and `threading.Lock` is not reentrant, so the "nothing waiting"
        branch used to deadlock the thread against itself — and because it died holding the
        lock, every later request blocked too. The whole server hung, from one click on an
        empty queue.
        """
        c = hist = None
        served = False
        with LOCK:
            if PREPARED:
                EVENTS.append(PREPARED.pop(0))
                served = True
            elif PENDING:
                c = PENDING.pop(0)
                hist = history_for(c.get("who"))

        if served:
            self._redirect()
            return
        if c is None:
            self._send(page(error("Nothing waiting", "Post a comment first.")),
                       "text/html; charset=utf-8")
            return

        # Nothing was ready, so render it now. This is the first comment of a stream, or one
        # posted while the queue was empty; every comment behind it gets the prepared path.
        ev = answer(c, hist)
        ev["waited"] = True
        with LOCK:
            EVENTS.append(ev)
        self._redirect()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8777)
    args = ap.parse_args()
    threading.Thread(target=prefetch_worker, daemon=True).start()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Sofia live -> http://{args.host}:{args.port}")
    print(f"prefetching up to {PREFETCH_DEPTH} answers ahead")
    print(f"clips -> {CLIPS}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
