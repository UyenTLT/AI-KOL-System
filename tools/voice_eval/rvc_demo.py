#!/usr/bin/env python3
"""Hear what the trained RVC model actually does: a voice goes in, Sofia comes out.

The numbers from the verification are in the profile and they are the honest summary, but a
similarity score is a poor way to answer "does this sound like her". This page puts the source
and the conversion next to each other and lets you decide, with the measurements alongside
rather than instead.

Three things it deliberately makes audible:

* **The conversion itself** — pick another character, have her say a line, convert it. The
  source and the result play from the same row, so the comparison is one click apart.
* **The pitch limit.** The shift control goes past the measured safe range on purpose. Identity
  falls from 0.6448 at no shift to 0.5476 at +10 semitones, and that is a thing to hear, not to
  read. Past ±5 the page says so.
* **The nondeterminism.** Convert the same clip twice and the files differ — four identical
  invocations produced four different outputs, spread 0.0211 in similarity. There is a button
  for exactly that, because it is the finding most likely to be disbelieved.

Identity measurement is opt-in per run: it loads ERes2NetV2 in a subprocess and takes far longer
than the conversion, so making it automatic would make the page feel broken.

    .venv\\Scripts\\python.exe tools\\voice_eval\\rvc_demo.py        # :8778
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
for sub in ("studio", "tts_train", "voice_eval"):
    sys.path.insert(0, str(REPO / "tools" / sub))

CLIPS = Path(os.getenv("KOL_RVC_DEMO_DIR") or (REPO / "renders" / "rvc_demo"))
CLIPS.mkdir(parents=True, exist_ok=True)

KOL = "sofia-hsu"
RESULTS: list[dict] = []

CSS = """
:root{--bg:#EFF2F2;--card:#FFF;--card2:#E7ECEC;--ink:#111719;--tx:#1B2426;--mut:#5A6A6C;
 --faint:#8A9899;--rule:#D2DADA;--acc:#0E6E68;--accdim:#0E6E680F;--bad:#B04352;--ok:#3C7F55;
 --src:#4A5C8A;--srcdim:#4A5C8A12}
@media (prefers-color-scheme:dark){:root{--bg:#0D1214;--card:#141B1D;--card2:#1D2628;
 --ink:#E8EDED;--tx:#DAE2E2;--mut:#96A5A6;--faint:#6E7D7E;--rule:#263133;--acc:#4FB3A8;
 --accdim:#4FB3A814;--bad:#D0707C;--ok:#5FA97A;--src:#8FA3D4;--srcdim:#8FA3D41A}}
*,*::before,*::after{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--tx);
 font:16px/1.6 "Segoe UI Variable Text","Segoe UI",system-ui,-apple-system,sans-serif}
.w{max-width:820px;margin:0 auto;padding:36px 20px 70px}
h1{font-family:Cambria,Georgia,serif;font-size:30px;margin:0 0 4px;color:var(--ink)}
.sub{color:var(--mut);font-size:15px;margin:0 0 6px}
.svc{display:flex;gap:14px;flex-wrap:wrap;font-family:Consolas,monospace;font-size:11.5px;
 color:var(--faint);border-top:1px solid var(--rule);padding-top:10px;margin-top:13px}
h2{font-family:Cambria,Georgia,serif;font-size:20px;margin:32px 0 4px;color:var(--ink)}
h2 b{font-family:Consolas,monospace;font-size:12px;color:var(--acc);border:1px solid var(--acc);
 border-radius:3px;padding:1px 6px;margin-right:8px;vertical-align:3px}
.note{color:var(--mut);font-size:14px;margin:0 0 12px}
form{background:var(--card);border:1px solid var(--rule);border-radius:12px;padding:16px 18px;
 margin:0 0 14px}
label{display:block;font-size:11.5px;letter-spacing:.06em;text-transform:uppercase;
 color:var(--faint);font-weight:600;margin:12px 0 5px}
label:first-of-type{margin-top:0}
input[type=text],textarea,select,input[type=file]{width:100%;font:inherit;font-size:15px;
 padding:9px 11px;border:1px solid var(--rule);border-radius:8px;background:var(--bg);
 color:var(--ink)}
.row{display:flex;gap:12px;flex-wrap:wrap;align-items:flex-end}
.row>div{flex:1;min-width:135px}
.chk{display:flex;align-items:center;gap:8px;margin-top:13px;font-size:14px;color:var(--mut)}
.chk input{width:auto}
button{font:inherit;font-size:15px;font-weight:600;padding:10px 21px;border:1px solid var(--acc);
 border-radius:8px;background:var(--acc);color:#fff;cursor:pointer;margin-top:14px}
button:hover{filter:brightness(1.08)}
button.sec{background:var(--card);color:var(--acc);border-color:var(--rule)}
.pair{background:var(--card);border:1px solid var(--rule);border-radius:12px;padding:15px 17px;
 margin:0 0 16px}
.side{padding:10px 0}
.side+.side{border-top:1px solid var(--rule)}
.tag{font-family:Consolas,monospace;font-size:10.5px;letter-spacing:.07em;text-transform:uppercase;
 font-weight:600;margin-bottom:5px}
.tag.a{color:var(--src)}
.tag.b{color:var(--acc)}
audio{width:100%;margin:3px 0 2px}
.said{font-size:15px;color:var(--ink);margin:0 0 9px;padding-left:11px;
 border-left:2px solid var(--rule)}
.meta{font-family:Consolas,monospace;font-size:11.5px;color:var(--faint);display:flex;gap:13px;
 flex-wrap:wrap;margin-top:6px}
.meta .num{color:var(--ink);font-weight:600}
.warn{background:var(--card2);border-left:3px solid var(--bad);border-radius:0 8px 8px 0;
 padding:10px 13px;margin:10px 0 0;font-size:13.5px;color:var(--mut)}
table{width:100%;border-collapse:collapse;font-size:14px;margin:4px 0 0}
th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--rule)}
th{font-family:Consolas,monospace;font-size:11px;letter-spacing:.06em;text-transform:uppercase;
 color:var(--faint);font-weight:600}
td.n{font-family:Consolas,monospace;text-align:right;font-variant-numeric:tabular-nums;
 color:var(--ink)}
.ev{background:var(--card);border:1px solid var(--rule);border-radius:12px;padding:15px 17px;
 margin:0 0 14px}
.ev p{font-size:13.5px;color:var(--mut);margin:9px 0 0}
.err{background:var(--card);border:1px solid var(--rule);border-left:3px solid var(--bad);
 border-radius:12px;padding:15px 18px;margin:0 0 16px;color:var(--bad);font-size:14.5px}
.err pre{white-space:pre-wrap;font-size:11.5px;color:var(--mut);margin:8px 0 0}
.empty{color:var(--faint);font-style:italic;font-size:14.5px}
footer{margin-top:34px;padding-top:13px;border-top:1px solid var(--rule);
 font-family:Consolas,monospace;font-size:11.5px;color:var(--faint)}
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


def characters():
    try:
        from voice_studio import characters as ch
        return [c for c in ch() if c.get("id") != KOL]
    except Exception:
        return []


def similarity(clip: Path) -> float | None:
    """Identity against her real reference, level-matched first.

    The metric is level-sensitive — the project measured the same file at two loudnesses
    scoring 0.7898 against itself — so comparing without normalising would report a volume
    difference as an identity difference.
    """
    import shutil
    from voice_studio import _normalise_loudness
    import denoise_ref as D
    ref_src = REPO / "kols" / KOL / "voice" / "ref_human.wav"
    work = CLIPS / ".lvl"
    work.mkdir(parents=True, exist_ok=True)
    pair = []
    for p in (ref_src, clip):
        d = work / f"{uuid.uuid4().hex[:6]}-{p.name}"
        shutil.copy(p, d)
        _normalise_loudness(d, -16.0)
        pair.append(d)
    try:
        return D.speaker_similarity(pair[0], pair[1])
    finally:
        for p in pair:
            p.unlink(missing_ok=True)


def player(tag: str, cls: str, clip: str, meta: str = "") -> str:
    return (f'<div class="side"><div class="tag {cls}">{esc(tag)}</div>'
            f'<audio controls src="/media/{esc(clip)}"></audio>'
            f'{f"<div class=meta>{meta}</div>" if meta else ""}</div>')


def result_block(r: dict) -> str:
    sim = lambda v: (f'<span>identity <span class="num">{v:.4f}</span></span>'
                     if isinstance(v, float) else "")
    warn = f'<div class="warn">{esc(r["warning"])}</div>' if r.get("warning") else ""
    return f"""<div class="pair">
  <p class="said">{esc(r["text"])}</p>
  {player(f'source — {r["src_name"]}', 'a', r['src_clip'], sim(r.get('src_sim')))}
  {player(f'converted — Sofia', 'b', r['out_clip'],
          sim(r.get('out_sim')) +
          f'<span>pitch {r["pitch"]:+d}</span><span>index {r["index_rate"]}</span>'
          f'<span>protect {r["protect"]}</span><span>{r["secs"]:.1f} s</span>')}
  {warn}
</div>"""


def page(body: str = "", **keep) -> bytes:
    from rvc_pipeline import available
    ok = available(KOL)
    svc = " ".join(f'<span>{n}: {"up" if u else "down"}</span>' for n, u in [
        ("CosyVoice", up("http://127.0.0.1:9881/health")),
        ("RVC model", ok)])

    opts = "".join(f'<option value="{esc(c["id"])}">{esc(c.get("name", c["id"]))}</option>'
                   for c in characters()) or '<option value="">(no other voices)</option>'
    pitches = "".join(
        f'<option value="{v}"{" selected" if v == 0 else ""}>{v:+d} semitones'
        f'{"  — past the safe range" if abs(v) > 5 else ""}</option>'
        for v in (-5, -2, 0, 2, 5, 8, 10))
    text = keep.get("text") or ("When the evening comes around and the lights are low, "
                                "I still hear the melody you left behind for me.")
    results = "\n".join(result_block(r) for r in reversed(RESULTS)) or (
        '<p class="empty">Nothing converted yet — run one above.</p>')

    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sofia — voice conversion</title><style>{CSS}</style></head><body><div class="w">

<h1>Voice conversion &mdash; Sofia</h1>
<p class="sub">Another voice goes in, hers comes out. The model keeps the source's melody and
   replaces the timbre, which is what makes a sung line possible at all.</p>
<div class="svc">{svc}</div>

{body}

<h2><b>1</b>Convert a voice</h2>
<p class="note">Another character says the line, then the same audio is put through Sofia's
   model. Both play below, one above the other.</p>
<form method="post" action="/convert">
  <label for="t">Line to say</label>
  <textarea id="t" name="text" rows="2">{esc(text)}</textarea>
  <div class="row">
    <div><label for="v">Source voice</label>
      <select id="v" name="voice">{opts}</select></div>
    <div><label for="p">Pitch shift</label>
      <select id="p" name="pitch">{pitches}</select></div>
  </div>
  <div class="chk"><input type="checkbox" id="m" name="measure" value="1">
    <label for="m" style="margin:0;text-transform:none;letter-spacing:0;font-size:14px;
      color:var(--mut);font-weight:400">Measure identity as well &mdash; accurate, but it loads a
      second model and adds most of the wait</label></div>
  <button type="submit">Convert</button>
</form>

<h2><b>2</b>Convert your own clip</h2>
<p class="note">Any voice, singing or speaking. It comes back as her.</p>
<form method="post" action="/upload" enctype="multipart/form-data">
  <label for="f">Audio file</label>
  <input type="file" id="f" name="audio" accept="audio/*">
  <div class="row">
    <div><label for="p2">Pitch shift</label>
      <select id="p2" name="pitch">{pitches}</select></div>
  </div>
  <div class="chk"><input type="checkbox" id="m2" name="measure" value="1">
    <label for="m2" style="margin:0;text-transform:none;letter-spacing:0;font-size:14px;
      color:var(--mut);font-weight:400">Measure identity as well</label></div>
  <button type="submit">Convert</button>
</form>

<h2><b>3</b>Results</h2>
{results}

<h2><b>4</b>What was measured</h2>
<div class="ev">
  <table>
    <tr><th>Pitch shift</th><th style="text-align:right">Identity</th>
        <th style="text-align:right">&plusmn;</th><th style="text-align:right">Median</th></tr>
    <tr><td>none</td><td class="n">0.6448</td><td class="n">0.0028</td><td class="n">220 Hz</td></tr>
    <tr><td>+5 semitones</td><td class="n">0.6013</td><td class="n">0.0100</td><td class="n">280 Hz</td></tr>
    <tr><td>+10 semitones</td><td class="n">0.5476</td><td class="n">0.0118</td><td class="n">296 Hz</td></tr>
  </table>
  <p>Mean of three runs each. Her training corpus is speech at roughly 195&ndash;220 Hz, so +10
     asks the model for a register it never saw &mdash; keep a sung source within about five
     semitones of her speaking range.</p>
  <p><b>The ceiling is 0.6931</b>, not 1.0: the model was trained on CosyVoice renders of her,
     because the real recording of the owner's voice is 50 seconds in total against RVC's
     guidance of ten minutes. Converting a different voice moves it from 0.4275 to about 0.645,
     which is most of the way to that ceiling. Ten minutes of real recording would raise the
     ceiling itself.</p>
  <p><b>Nothing here is repeatable to better than about 0.02.</b> Four byte-identical
     invocations produced four different files, spreading 0.0211. That is why the seven training
     checkpoints could not be ranked against each other, and why the button below exists.</p>
</div>
<form method="post" action="/twice">
  <button type="submit" class="sec">Convert the same clip twice, and compare</button>
</form>

<footer>RVC v2 40k &middot; trained 150 epochs on 30.2 min &middot; clips in {esc(CLIPS)}</footer>
</div></body></html>"""
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
        name = None
        for tok in head.decode("utf-8", "replace").split(";"):
            tok = tok.strip()
            if tok.startswith("name="):
                name = tok[5:].strip().strip('"').split("\r\n")[0]
        if name:
            out[name] = payload.rstrip(b"\r\n")
    return out


class Handler(BaseHTTPRequestHandler):
    server_version = "RvcDemo/1.0"
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
        elif p == "/ping":
            self._send(b"rvc demo is reachable", "text/plain; charset=utf-8")
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
            if p == "/convert":
                self._convert(g)
            elif p == "/upload":
                self._upload(form, g)
            elif p == "/twice":
                self._twice()
            else:
                self._send(b"not found", "text/plain; charset=utf-8", 404)
        except Exception as exc:
            self._send(page(error(type(exc).__name__, str(exc),
                                  traceback.format_exc()[-600:]), text=g("text")),
                       "text/html; charset=utf-8")

    def _stamp(self, tag: str) -> str:
        return f"{datetime.now():%H%M%S}-{tag}-{uuid.uuid4().hex[:4]}.wav"

    def _record(self, *, text, src_name, src_clip, out_clip, r, secs, measure):
        row = {"text": text, "src_name": src_name, "src_clip": src_clip, "out_clip": out_clip,
               "pitch": r["pitch"], "index_rate": r["index_rate"], "protect": r["protect"],
               "secs": secs, "warning": r.get("warning"), "at": f"{datetime.now():%H:%M:%S}"}
        if measure:
            row["src_sim"] = similarity(CLIPS / src_clip)
            row["out_sim"] = similarity(CLIPS / out_clip)
        RESULTS.append(row)
        if len(RESULTS) > 12:
            del RESULTS[0]

    def _convert(self, g):
        from voice_studio import synthesize
        from rvc_pipeline import convert
        text = g("text").strip()
        voice = g("voice")
        if not text or not voice:
            self._send(page(error("Nothing to convert", "Pick a source voice and type a line.")),
                       "text/html; charset=utf-8")
            return
        src = self._stamp("src")
        synthesize(voice, text, out=CLIPS / src)
        out = self._stamp("sofia")
        t = time.perf_counter()
        r = convert(CLIPS / src, CLIPS / out, kol_id=KOL, pitch=int(g("pitch", "0")))
        secs = time.perf_counter() - t
        names = {c["id"]: c.get("name", c["id"]) for c in characters()}
        self._record(text=text, src_name=names.get(voice, voice), src_clip=src, out_clip=out,
                     r=r, secs=secs, measure=bool(g("measure")))
        self._send(page(text=text), "text/html; charset=utf-8")

    def _upload(self, form, g):
        from rvc_pipeline import convert
        blob = form.get("audio") or b""
        if len(blob) < 2000:
            self._send(page(error("No audio", "Choose a file first.")),
                       "text/html; charset=utf-8")
            return
        src = self._stamp("upload")
        (CLIPS / src).write_bytes(blob)
        out = self._stamp("sofia")
        t = time.perf_counter()
        r = convert(CLIPS / src, CLIPS / out, kol_id=KOL, pitch=int(g("pitch", "0")))
        secs = time.perf_counter() - t
        self._record(text="(uploaded audio)", src_name="your file", src_clip=src, out_clip=out,
                     r=r, secs=secs, measure=bool(g("measure")))
        self._send(page(), "text/html; charset=utf-8")

    def _twice(self):
        """Convert one clip twice and show that the results differ."""
        import hashlib
        from voice_studio import synthesize
        from rvc_pipeline import convert
        line = "The same words, the same settings, converted twice in a row."
        src = self._stamp("src")
        synthesize("preset-en-warm", line, out=CLIPS / src)
        outs, digests = [], []
        for _ in range(2):
            o = self._stamp("sofia")
            r = convert(CLIPS / src, CLIPS / o, kol_id=KOL)
            outs.append(o)
            digests.append(hashlib.sha256((CLIPS / o).read_bytes()).hexdigest()[:12])
        same = digests[0] == digests[1]
        verdict = ("identical — which would contradict the measurement" if same else
                   "different files from identical inputs, as measured")
        body = f"""<div class="pair">
  <p class="said">{esc(line)}</p>
  {player('source', 'a', src)}
  {player('run 1', 'b', outs[0], f'<span>sha {esc(digests[0])}</span>')}
  {player('run 2', 'b', outs[1], f'<span>sha {esc(digests[1])}</span>')}
  <div class="warn">Same model, same settings, same input: {esc(verdict)}. This is why no
    comparison finer than about 0.02 on this metric means anything without repeats.</div>
</div>"""
        self._send(page(body), "text/html; charset=utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8778)
    args = ap.parse_args()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"RVC demo -> http://{args.host}:{args.port}")
    print(f"clips -> {CLIPS}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
