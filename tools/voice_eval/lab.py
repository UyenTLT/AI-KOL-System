#!/usr/bin/env python3
"""Voice lab — hear the engines side by side, against real human speech.

`/studio` is the production tool: pick a character, get audio. `/selftest` answers pass/fail.
Neither answers the question that actually matters here — *does this sound like a person* —
because that is a listening judgement, not a metric.

So this page puts the candidates next to each other, with the real human clip pinned at the
top as the thing to beat, and the numbers underneath each render rather than instead of it.

Two features exist to keep the listening honest:

  * **Blind mode** shuffles the rows and hides the engine names until you reveal them. Knowing
    which one is "the new engine" is worth a surprising amount of imagined improvement.
  * **Measure** runs the octave-safe prosody metrics and an ASR round-trip on a clip you have
    already heard, so the numbers confirm or contradict your ear instead of leading it.

Engines are reached over HTTP, never imported, because they pin incompatible stacks:

    GPT-SoVITS api_v2   :9880   the 5 fine-tuned voices in use today
    CosyVoice 2         :9881   tools/voice_eval/cosy_server.py, in its own venv
    LiveTalking         :8010   optional — speak a clip through the avatar for lip-sync

    .venv\\Scripts\\python.exe tools\\voice_eval\\lab.py       # http://127.0.0.1:8773
"""
from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools" / "studio"))
sys.path.insert(0, str(REPO / "tools" / "voice_eval"))

GSV_API = "http://127.0.0.1:9880"
COSY_API = "http://127.0.0.1:9881"
LIVETALKING = "http://127.0.0.1:8010"

CLIPS = Path(tempfile.gettempdir()) / "ai-kol-voicelab"
CLIPS.mkdir(parents=True, exist_ok=True)

DEFAULT_LINE = ("Okay so, I honestly did not expect this to work. "
                "But look at my skin right now. I mean, come on!")
DEFAULT_INSTRUCT = ("Speak warmly and conversationally, like talking to a close friend, "
                    "with natural pauses.")

# The one piece of real human speech in the repo, and the reference the CosyVoice conditions
# clone from. Rights confirmed by the owner (commit 6b00847).
HUMAN_RAW = REPO / "kols/sofia-vargas/voice/raw/kols_sofia-vargas_raw voice.m4a"
HUMAN_SPAN = (7.7, 14.2)
HUMAN_TEXT = ("and paper. I want you to write down in one section all the good things "
              "that he's done for you.")


def probe(url: str, timeout: float = 1.0) -> bool:
    try:
        urllib.request.urlopen(url, timeout=timeout)
        return True
    except urllib.error.HTTPError:
        return True
    except Exception:
        return False


_PROBE_CACHE: dict = {"at": 0.0, "result": None}


def probe_all_cached(urls: dict[str, str], ttl: float = 10.0) -> dict[str, bool]:
    """Service health, cached briefly.

    Probing on every page load meant the browser waited ~1 s before receiving a single byte,
    while /ping answered instantly — the only behavioural difference left between a page that
    loaded and one that appeared not to. Health does not change second to second; a short TTL
    keeps it fresh enough to be useful and makes the page respond immediately.
    """
    now = time.time()
    if _PROBE_CACHE["result"] is not None and now - _PROBE_CACHE["at"] < ttl:
        return _PROBE_CACHE["result"]
    result = probe_all(urls)
    _PROBE_CACHE.update(at=now, result=result)
    return result


def probe_all(urls: dict[str, str]) -> dict[str, bool]:
    """Probe every engine at once.

    A *down* service costs ~2 s here rather than failing fast, so probing three in series made
    the page take 4 s to build whenever two engines were off — which is the normal state while
    an engine is still being set up. Slow enough that a browser looks like it is hanging.
    """
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=len(urls)) as pool:
        futures = {k: pool.submit(probe, u) for k, u in urls.items()}
        return {k: f.result() for k, f in futures.items()}


def human_ref() -> Path:
    """The human reference, cut once and cached. Everything clones from this."""
    dst = CLIPS / "human_ref.wav"
    if dst.is_file():
        return dst
    if not HUMAN_RAW.is_file():
        raise FileNotFoundError(str(HUMAN_RAW))
    start, end = HUMAN_SPAN
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(HUMAN_RAW),
                    "-ss", str(start), "-to", str(end), "-ar", "16000", "-ac", "1",
                    str(dst)], check=True)
    return dst


def gsv_voices() -> list[dict]:
    try:
        from voice_studio import characters
        return characters()
    except Exception:
        return []


def conditions() -> list[dict]:
    """Every row the lab can render. Order is the order they appear."""
    rows = [{"id": f"gsv:{c['id']}", "engine": "GPT-SoVITS",
             "label": c.get("name") or c["id"],
             "note": "in use today · fine-tuned",
             "lang": "zh" if str(c.get("lang", "")).lower().startswith(("zh", "chinese")) else "en"}
            for c in gsv_voices()]
    rows += [
        {"id": "cosy:zs-synth", "engine": "CosyVoice 2", "label": "zero-shot · synthetic ref",
         "note": "clones Sofia's current reference clip", "lang": "en"},
        {"id": "cosy:zs-human", "engine": "CosyVoice 2", "label": "zero-shot · human ref",
         "note": "clones the real human clip — no fine-tuned weights to fight it", "lang": "en"},
        {"id": "cosy:instruct", "engine": "CosyVoice 2", "label": "instruction-controlled",
         "note": "human ref plus a delivery instruction", "lang": "en"},
    ]
    return rows


# ------------------------------------------------------------------------ rendering

def render_gsv(cid: str, text: str) -> Path:
    from voice_studio import synthesize
    out = CLIPS / f"{cid}-{uuid.uuid4().hex[:8]}.wav"
    synthesize(cid, text, out=out)
    return out


def render_cosy(which: str, text: str, instruct: str) -> tuple[Path, dict]:
    ref_synth = REPO / "kols/sofia-vargas/voice/ref.wav"
    ref_synth_text = (REPO / "kols/sofia-vargas/voice/ref.txt").read_text(
        encoding="utf-8").strip() if (REPO / "kols/sofia-vargas/voice/ref.txt").is_file() else ""

    if which == "zs-synth":
        body = {"text": text, "mode": "zero_shot", "ref": str(ref_synth),
                "ref_text": ref_synth_text}
    elif which == "zs-human":
        body = {"text": text, "mode": "zero_shot", "ref": str(human_ref()),
                "ref_text": HUMAN_TEXT}
    elif which == "instruct":
        body = {"text": text, "mode": "instruct", "ref": str(human_ref()),
                "instruct": instruct or DEFAULT_INSTRUCT}
    else:
        raise ValueError(f"unknown CosyVoice condition {which!r}")

    req = urllib.request.Request(f"{COSY_API}/say", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=180) as r:
        audio = r.read()
        meta = {"rtf": r.headers.get("X-RTF"), "gen_s": r.headers.get("X-Gen-Seconds")}
    out = CLIPS / f"cosy-{which}-{uuid.uuid4().hex[:8]}.wav"
    out.write_bytes(audio)
    return out, meta


def do_render(row_id: str, text: str, instruct: str) -> dict:
    started = time.perf_counter()
    kind, which = row_id.split(":", 1)
    meta: dict = {}
    if kind == "gsv":
        path = render_gsv(which, text)
    elif kind == "cosy":
        path, meta = render_cosy(which, text, instruct)
    else:
        raise ValueError(f"unknown row {row_id!r}")
    elapsed = time.perf_counter() - started
    return {"clip": path.name, "gen_seconds": round(elapsed, 2),
            "kb": round(path.stat().st_size / 1024), **meta}


# ------------------------------------------------------------------------ measuring

def do_measure(clip: str, lang: str) -> dict:
    """Prosody plus an ASR round-trip. Slow (pyin then Whisper), hence a separate action."""
    path = CLIPS / Path(clip).name
    if not path.is_file():
        raise FileNotFoundError(clip)
    import prosody
    r = prosody.feats(prosody.load_any(path))
    out = {}
    if r:
        out.update(seconds=round(r["dur"], 2), median_hz=round(r["f0_med"], 1),
                   range_st=round(r["f0_range_st"], 2),
                   pauses_per_10s=round(r["pause_rate"], 2))
    try:
        from voice_studio import transcribe
        heard, detected = transcribe(path, lang or None)
        out["heard"] = heard
        out["detected_lang"] = detected
    except Exception as exc:
        out["heard"] = f"(ASR unavailable: {type(exc).__name__})"
    return out


def do_lipsync(clip: str, sessionid: str) -> dict:
    """Speak an already-rendered line through the avatar. LiveTalking has no endpoint that
    lists sessions, so the id has to be supplied — /demo logs it on Connect."""
    text = (CLIPS / (Path(clip).stem + ".txt"))
    body = json.dumps({"sessionid": _coerce(sessionid), "text": text.read_text(encoding="utf-8")
                       if text.is_file() else "", "type": "echo", "interrupt": True}).encode()
    req = urllib.request.Request(f"{LIVETALKING}/human", data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def _coerce(sid: str):
    try:
        return int(sid)
    except (TypeError, ValueError):
        return sid


# ---------------------------------------------------------------------------- page

CSS = """
*,*::before,*::after{box-sizing:border-box}
:root{--bg:#f6f7f9;--panel:#fff;--line:#e3e6ea;--fg:#14171a;--mut:#666e78;--ok:#0f8a4c;
  --bad:#c62b2b;--warn:#a86400;--accent:#2f5fd0;--soft:#eef1f5;--target:#7a4dd0}
@media (prefers-color-scheme:dark){:root{--bg:#0f1215;--panel:#171b1f;--line:#282e35;
  --fg:#e7eaee;--mut:#98a1ac;--ok:#43c07d;--bad:#ef6a6a;--warn:#e0a33c;--accent:#7aa2f7;
  --soft:#1e242a;--target:#a98cf0}}
:root[data-theme=dark]{--bg:#0f1215;--panel:#171b1f;--line:#282e35;--fg:#e7eaee;--mut:#98a1ac;
  --ok:#43c07d;--bad:#ef6a6a;--warn:#e0a33c;--accent:#7aa2f7;--soft:#1e242a;--target:#a98cf0}
:root[data-theme=light]{--bg:#f6f7f9;--panel:#fff;--line:#e3e6ea;--fg:#14171a;--mut:#666e78;
  --ok:#0f8a4c;--bad:#c62b2b;--warn:#a86400;--accent:#2f5fd0;--soft:#eef1f5;--target:#7a4dd0}
body{margin:0;background:var(--bg);color:var(--fg);
  font:14px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,"Noto Sans TC",sans-serif}
.wrap{max-width:1000px;margin:0 auto;padding:24px 20px 64px}
h1{font-size:20px;margin:0 0 3px;letter-spacing:-.01em}
.sub{color:var(--mut);font-size:12.5px;margin:0 0 18px}
h2{font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:var(--mut);
  margin:26px 0 9px;font-weight:600}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.target{border-left:3px solid var(--target)}
.target .nm{color:var(--target)}
.row{background:var(--panel);border:1px solid var(--line);border-radius:10px;
  margin-bottom:8px;padding:12px 14px}
.row.done{border-color:color-mix(in srgb,var(--accent) 40%,var(--line))}
.head{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap}
.nm{font-weight:600}
.eng{font-size:11px;letter-spacing:.04em;text-transform:uppercase;color:var(--mut);
  border:1px solid var(--line);border-radius:3px;padding:1px 6px}
.note{color:var(--mut);font-size:12.5px;flex:1;min-width:180px}
.btn{font:inherit;font-size:13px;padding:5px 12px;border:1px solid var(--line);border-radius:7px;
  background:var(--panel);color:var(--fg);cursor:pointer}
.btn:hover{border-color:var(--accent)} .btn:disabled{opacity:.5;cursor:default}
.btn.pri{background:var(--accent);border-color:var(--accent);color:#fff}
.btn:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
audio{width:100%;margin-top:9px}
.met{display:flex;flex-wrap:wrap;gap:14px;margin-top:8px;font-size:12.5px;color:var(--mut);
  font-variant-numeric:tabular-nums}
.met b{color:var(--fg);font-weight:600}
.heard{margin-top:6px;font-size:12.5px;color:var(--mut);font-style:italic}
.bar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:0 0 14px}
textarea,input[type=text]{font:inherit;font-size:13px;width:100%;padding:8px 10px;
  border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--fg);resize:vertical}
label{font-size:12px;color:var(--mut);display:block;margin:10px 0 3px}
.svc{font-size:12px;color:var(--mut);display:flex;gap:14px;flex-wrap:wrap;margin-top:10px}
.dot{width:8px;height:8px;border-radius:50%;display:inline-block;margin-right:5px}
.up{background:var(--ok)}.down{background:var(--bad)}
.err{color:var(--bad);font-size:12.5px;margin-top:6px}
.hidden-name{filter:blur(5px);user-select:none}
"""


def page(blind: bool) -> str:
    rows = conditions()
    if blind:
        random.shuffle(rows)
    services = probe_all_cached({"gsv": f"{GSV_API}/docs", "cosy": f"{COSY_API}/health",
                                 "lt": f"{LIVETALKING}/index.html"})
    data = json.dumps({"rows": rows, "blind": blind, "services": services,
                       "defaultLine": DEFAULT_LINE, "defaultInstruct": DEFAULT_INSTRUCT})
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Voice lab — does it sound like a person?</title><style>{CSS}</style></head><body>
<div class="wrap">
  <h1>Voice lab</h1>
  <p class="sub">The same line through every engine, with real human speech pinned on top as
     the thing to beat. Render, listen, then measure — in that order.</p>

  <div class="panel target">
    <div class="head"><span class="nm">Real human speech</span>
      <span class="eng">target</span>
      <span class="note">48 s recording, rights confirmed by the owner. Not synthesised.
        This is what "sounds like a person" means.</span></div>
    <audio controls src="/audio/human_ref.wav"></audio>
    <div class="met" id="human-met"><button class="btn" onclick="measureHuman()">Measure</button></div>
  </div>

  <h2>Line to speak</h2>
  <div class="panel">
    <textarea id="line" rows="2"></textarea>
    <label for="instruct">Delivery instruction — CosyVoice instruction-controlled row only</label>
    <input type="text" id="instruct">
    <div class="bar" style="margin-top:12px">
      <button class="btn pri" id="render-all">Render every row</button>
      <button class="btn" onclick="toggleBlind()" id="blind-btn"></button>
      <button class="btn" onclick="reveal()" id="reveal-btn" style="display:none">Reveal names</button>
    </div>
    <div class="svc" id="svc"></div>
  </div>

  <h2>Candidates</h2>
  <div id="rows"></div>
</div>
<script>
const D = {data};
const el=(t,c,x)=>{{const e=document.createElement(t); if(c)e.className=c;
  if(x!==undefined)e.textContent=x; return e;}};
document.getElementById('line').value = D.defaultLine;
document.getElementById('instruct').value = D.defaultInstruct;
document.getElementById('blind-btn').textContent = D.blind ? 'Blind mode: on' : 'Blind mode: off';
if (D.blind) document.getElementById('reveal-btn').style.display='';

function svc(){{
  const s=D.services, box=document.getElementById('svc');
  const one=(up,name)=>`<span><i class="dot ${{up?'up':'down'}}"></i>${{name}}</span>`;
  box.innerHTML = one(s.gsv,'GPT-SoVITS :9880') + one(s.cosy,'CosyVoice :9881')
                + one(s.lt,'LiveTalking :8010');
  if(!s.cosy) box.innerHTML += '<span style="color:var(--warn)">CosyVoice rows will fail '
    + 'until you start tools/voice_eval/cosy_server.py in the CosyVoice venv</span>';
}}

function render(){{
  const host=document.getElementById('rows');
  D.rows.forEach((r,i)=>{{
    const box=el('div','row'); box.id='row-'+i;
    const h=el('div','head');
    const nm=el('span','nm', D.blind ? 'Candidate '+String.fromCharCode(65+i) : r.label);
    if(D.blind) nm.dataset.real=r.label;
    h.appendChild(nm);
    const eng=el('span','eng', D.blind?'?':r.engine); if(D.blind) eng.dataset.real=r.engine;
    h.appendChild(eng);
    h.appendChild(el('span','note', D.blind?'':r.note));
    const b=el('button','btn','Render'); b.onclick=()=>one(i); h.appendChild(b);
    box.appendChild(h); host.appendChild(box);
  }});
}}

async function one(i){{
  const r=D.rows[i], box=document.getElementById('row-'+i);
  const btn=box.querySelector('.btn'); btn.disabled=true; btn.textContent='rendering…';
  box.querySelectorAll('audio,.met,.heard,.err').forEach(n=>n.remove());
  try{{
    const res=await fetch('/api/render',{{method:'POST',
      headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{id:r.id, text:document.getElementById('line').value,
                           instruct:document.getElementById('instruct').value}})}});
    const j=await res.json();
    if(j.error) throw new Error(j.error);
    const a=document.createElement('audio'); a.controls=true; a.src='/audio/'+j.clip;
    box.appendChild(a);
    const m=el('div','met');
    m.innerHTML=`<span>generated in <b>${{j.gen_seconds}}s</b></span><span><b>${{j.kb}}</b> KB</span>`
      + (j.rtf?`<span>RTF <b>${{j.rtf}}</b></span>`:'');
    const mb=el('button','btn','Measure'); mb.style.padding='2px 9px'; mb.style.fontSize='12px';
    mb.onclick=()=>measure(i,j.clip,mb); m.appendChild(mb);
    box.appendChild(m); box.classList.add('done');
  }}catch(e){{ box.appendChild(el('div','err', String(e.message||e))); }}
  btn.disabled=false; btn.textContent='Render';
}}

async function measure(i,clip,btn){{
  btn.disabled=true; btn.textContent='measuring…';
  try{{
    const res=await fetch('/api/measure',{{method:'POST',
      headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{clip, lang:D.rows[i].lang}})}});
    const j=await res.json();
    if(j.error) throw new Error(j.error);
    const box=document.getElementById('row-'+i);
    const m=el('div','met');
    m.innerHTML=`<span>pitch <b>${{j.median_hz}}</b> Hz</span>`
      +`<span>range <b>${{j.range_st}}</b> st</span>`
      +`<span>pauses/10s <b>${{j.pauses_per_10s}}</b></span>`
      +`<span><b>${{j.seconds}}</b> s</span>`;
    box.appendChild(m);
    if(j.heard) box.appendChild(el('div','heard','heard back: '+j.heard));
    btn.remove();
  }}catch(e){{ btn.disabled=false; btn.textContent='Measure';
    document.getElementById('row-'+i).appendChild(el('div','err',String(e.message||e))); }}
}}

async function measureHuman(){{
  const box=document.getElementById('human-met');
  box.textContent='measuring…';
  const res=await fetch('/api/measure',{{method:'POST',
    headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{clip:'human_ref.wav', lang:'en'}})}});
  const j=await res.json();
  box.innerHTML=`<span>pitch <b>${{j.median_hz}}</b> Hz</span>`
    +`<span>range <b>${{j.range_st}}</b> st</span>`
    +`<span>pauses/10s <b>${{j.pauses_per_10s}}</b></span>`;
}}

function toggleBlind(){{ location.search = D.blind ? '' : '?blind=1'; }}
function reveal(){{
  document.querySelectorAll('[data-real]').forEach(n=>{{ n.textContent=n.dataset.real; }});
  D.rows.forEach((r,i)=>{{
    const n=document.getElementById('row-'+i).querySelector('.note');
    if(n) n.textContent=r.note;
  }});
  document.getElementById('reveal-btn').style.display='none';
}}

document.getElementById('render-all').onclick=async e=>{{
  e.target.disabled=true; const t=e.target.textContent; e.target.textContent='rendering…';
  for(let i=0;i<D.rows.length;i++) await one(i);
  e.target.textContent=t; e.target.disabled=false;
}};

svc(); render();
</script></body></html>"""


# -------------------------------------------------------------------------- server

class Handler(BaseHTTPRequestHandler):
    server_version = "VoiceLab/1.0"

    def log_message(self, fmt, *args):
        pass

    def _send(self, body: bytes, ctype: str, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, status: int = 200):
        self._send(json.dumps(obj, ensure_ascii=False).encode(), "application/json", status)

    def handle_one_request(self):
        """Browsers open speculative connections and drop them, which raises WinError 10053 on
        Windows and buries the log in tracebacks for something that is not an error. Swallow
        exactly that case; everything else still surfaces."""
        try:
            super().handle_one_request()
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            self.close_connection = True

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/ping":
            # Smallest possible response, no engine probes, no JS. If this renders in the
            # browser but "/" does not, the problem is the page, not the connection.
            self._send(b"voice lab is reachable", "text/plain; charset=utf-8")
        elif parsed.path == "/":
            blind = urllib.parse.parse_qs(parsed.query).get("blind", ["0"])[0] == "1"
            try:
                human_ref()
            except Exception:
                pass
            self._send(page(blind).encode("utf-8"), "text/html; charset=utf-8")
        elif parsed.path.startswith("/audio/"):
            name = Path(urllib.parse.unquote(parsed.path[len("/audio/"):])).name  # no traversal
            f = CLIPS / name
            if not f.is_file():
                self._json({"error": "no such clip"}, 404)
                return
            self._send(f.read_bytes(), "audio/wav")
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception as exc:
            self._json({"error": f"bad request: {exc}"}, 400)
            return
        try:
            if path == "/api/render":
                self._json(do_render(body.get("id", ""), body.get("text") or DEFAULT_LINE,
                                     body.get("instruct") or DEFAULT_INSTRUCT))
            elif path == "/api/measure":
                self._json(do_measure(body.get("clip", ""), body.get("lang", "en")))
            elif path == "/api/lipsync":
                self._json(do_lipsync(body.get("clip", ""), body.get("sessionid", "")))
            else:
                self._json({"error": "not found"}, 404)
        except urllib.error.URLError as exc:
            self._json({"error": f"engine unreachable: {exc.reason}"}, 502)
        except Exception as exc:
            self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8773)
    args = ap.parse_args()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"voice lab -> http://{args.host}:{args.port}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
