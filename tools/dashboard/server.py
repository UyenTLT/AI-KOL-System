#!/usr/bin/env python3
"""Local project dashboard — live pipeline state, asset browser, and live avatar demo.

Reads real state off disk and over the wire on every request, so it never shows a
stale hardcoded snapshot:

  * `kols/index.json` + each `kols/<id>/profile.json`  -> roster, status, voice config
  * `kols/<id>/voice/dataset/{<id>.list,manifest.json}` -> dataset size + QC rejections
  * `kols/<id>/images|videos`                           -> asset counts
  * `GPT-SoVITS/{SoVITS,GPT}_weights_*`                 -> which voices are trained
  * :9880 / :8010 / :11434                              -> service health
  * `nvidia-smi`                                        -> VRAM headroom

Pages
    /                 dashboard (pipeline, services, GPU, roster)
    /kol/<id>          asset browser: images, training clips + transcripts, videos
    /demo              live LiveTalking avatar: type text, watch it speak
    /api/state         the whole state as JSON (for scripts / CI)
    /api/kol/<id>      one KOL's detail as JSON

The avatar demo proxies WebRTC *signalling* through this server (/lt/*) so the browser
only ever talks to one origin; the media itself still flows peer-to-peer from LiveTalking.

Stdlib only — no new dependencies, runs with any of the three venvs (or system python).

    python tools/dashboard/server.py            # http://127.0.0.1:8770
    python tools/dashboard/server.py --port 9000 --host 0.0.0.0
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LIVETALKING = "http://127.0.0.1:8010"
# reply_queue lives beside this file; voice_studio in tools/studio/. Both import
# persona_brain from tools/livetalking/, which they add to sys.path themselves.
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "studio"))

SERVICES = [
    {"key": "gpt_sovits", "name": "GPT-SoVITS api_v2", "url": "http://127.0.0.1:9880/docs",
     "role": "cloned voice (TTS)", "port": 9880},
    {"key": "livetalking", "name": "LiveTalking", "url": f"{LIVETALKING}/index.html",
     "role": "realtime lip-sync avatar", "port": 8010},
    {"key": "ollama", "name": "Ollama", "url": "http://127.0.0.1:11434/api/tags",
     "role": "LLM brain (persona replies)", "port": 11434},
]

IMG_EXT = (".png", ".jpg", ".jpeg", ".webp")
VID_EXT = (".mp4", ".mov", ".webm")
AUD_EXT = (".wav", ".mp3", ".m4a", ".ogg", ".flac")
SAFE_EXT = IMG_EXT + VID_EXT + AUD_EXT


# ------------------------------------------------------------------ collectors

def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def count_files(directory: Path, suffixes: tuple[str, ...]) -> int:
    if not directory.is_dir():
        return 0
    return sum(1 for p in directory.rglob("*") if p.suffix.lower() in suffixes)


def probe(url: str, timeout: float = 1.5) -> tuple[bool, str]:
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            ms = (time.perf_counter() - started) * 1000
            return True, f"HTTP {resp.status} · {ms:.0f} ms"
    except urllib.error.HTTPError as exc:      # responding, just not 200
        return True, f"HTTP {exc.code}"
    except Exception as exc:
        return False, type(exc).__name__


# The sessionid of the most recent avatar connection, captured as it passes through the
# signalling proxy.
#
# "Approve & speak" used to ask reply_queue to discover a live session by polling
# GET /api/sessions. No LiveTalking build serves that route -- the string appears nowhere in
# its source -- so the lookup returned 404, the sessionid was always None, and the button
# silently degraded to approve-only even with a viewer connected. It failed safe, and so went
# unnoticed until tools/selftest asserted it.
#
# The fix is to stop discovering what we already know: every /demo connection negotiates its
# session through this proxy, so the sessionid is in a response we are already handling.
_LAST_SESSION: dict = {"sid": None, "at": 0.0}


def _remember_session(offer_response: bytes) -> None:
    try:
        sid = json.loads(offer_response).get("sessionid")
    except Exception:
        return
    if sid is not None:
        _LAST_SESSION.update(sid=sid, at=time.time())


def live_session() -> str | None:
    """The session to speak into, or None. Prefers whatever the proxy last saw; falls back to
    reply_queue's lookup so this keeps working if LiveTalking ever does serve a session list.

    A remembered id can still be stale (the viewer closed the tab). That is not worth probing
    for -- LiveTalking answers `{"code": -1, "msg": "session not found"}`, which the caller
    surfaces as-is."""
    sid = _LAST_SESSION.get("sid")
    if sid is not None:
        return sid
    try:
        import reply_queue as rq
        return rq._livetalking_session()
    except Exception:
        return None


def gpu_state() -> dict | None:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        out = subprocess.run(
            [exe, "--query-gpu=name,memory.used,memory.total,utilization.gpu,temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=8,
        )
        if out.returncode != 0 or not out.stdout.strip():
            return None
        name, used, total, util, temp = [v.strip() for v in out.stdout.strip().splitlines()[0].split(",")]
        return {"name": name, "used_mb": int(used), "total_mb": int(total),
                "util_pct": int(util), "temp_c": int(temp)}
    except Exception:
        return None


def trained_voices() -> dict[str, dict]:
    """Map exp/kol name -> which fine-tuned weight files exist on disk."""
    found: dict[str, dict] = {}
    gsv = REPO / "GPT-SoVITS"
    for pattern, kind in (("SoVITS_weights*/*.pth", "sovits"), ("GPT_weights*/*.ckpt", "gpt")):
        for f in gsv.glob(pattern):
            # weights are named "<exp>_e8_s496.pth" or "<exp>-e12.ckpt"
            stem = f.stem
            for sep in ("_e", "-e"):
                if sep in stem:
                    stem = stem.rsplit(sep, 1)[0]
                    break
            entry = found.setdefault(stem, {"sovits": None, "gpt": None})
            cur = entry[kind]
            if cur is None or f.stat().st_mtime > cur["mtime"]:
                entry[kind] = {"file": f.name, "mb": round(f.stat().st_size / 1e6, 1),
                               "mtime": f.stat().st_mtime}
    return found


def voice_state(kol_dir: Path, kol_id: str) -> dict:
    voice = kol_dir / "voice"
    dataset = voice / "dataset"
    out: dict = {"has_dir": voice.is_dir(), "clips": 0, "minutes": 0.0,
                 "rejected": {}, "candidates": 0, "ref_ok": False, "sources": [], "langs": {}}
    if not voice.is_dir():
        return out

    out["ref_ok"] = (voice / "ref.wav").is_file() and (voice / "ref.txt").is_file()

    listf = dataset / f"{kol_id}.list"
    if listf.is_file():
        rows = [r for r in listf.read_text(encoding="utf-8").splitlines() if r.strip()]
        out["clips"] = len(rows)
        langs: dict[str, int] = {}
        for r in rows:
            parts = r.split("|")
            if len(parts) == 4:
                langs[parts[2]] = langs.get(parts[2], 0) + 1
        out["langs"] = langs

    # QC report from a crawl run; bootstrap runs write a lighter manifest.
    man = read_json(dataset / "manifest.json")
    if man:
        totals = man.get("totals", {})
        out["candidates"] = totals.get("candidates", 0)
        out["minutes"] = totals.get("accepted_minutes", 0.0)
        out["rejected"] = totals.get("rejected_by_reason", {})
        out["sources"] = man.get("sources", [])
    bs = read_json(dataset / "bootstrap_manifest.json")
    if bs:
        out["minutes"] = out["minutes"] or bs.get("accepted_minutes", 0.0)
        out["candidates"] = out["candidates"] or bs.get("candidates", 0)
        out["bootstrap_voice"] = bs.get("voice")
    if not out["minutes"] and out["clips"]:
        out["minutes"] = None  # clips exist but no manifest to size them
    return out


def collect() -> dict:
    index = read_json(REPO / "kols" / "index.json") or {}
    weights = trained_voices()

    kols = []
    for entry in index.get("kols", []):
        kol_id = entry.get("id")
        if not kol_id:
            continue
        kdir = REPO / "kols" / kol_id
        profile = read_json(kdir / "profile.json") or {}
        vcfg = (profile.get("ai_assets") or {}).get("voice") or {}
        vs = voice_state(kdir, kol_id)
        w = weights.get(kol_id, {})
        acfg = (profile.get("ai_assets") or {}).get("avatar") or {}
        # An avatar is only real if its frames exist on disk, not just in the profile.
        adir = REPO / (acfg.get("avatar_dir") or "") if acfg.get("avatar_dir") else None
        a_frames = len(list((adir / "face_imgs").glob("*"))) if adir and (adir / "face_imgs").is_dir() else 0
        kols.append({
            "id": kol_id,
            "name": entry.get("name") or kol_id,
            "handle": entry.get("handle"),
            "category": entry.get("category"),
            "status": entry.get("status"),
            "images": count_files(kdir / "images", IMG_EXT),
            "videos": count_files(kdir / "videos", VID_EXT),
            "has_products": (kdir / "products.json").is_file(),
            "voice": {
                "engine": vcfg.get("engine"),
                "status": vcfg.get("status"),
                "source": vcfg.get("source"),
                "timbre": vcfg.get("bootstrap_timbre"),
                "gsv_version": vcfg.get("gsv_version"),
                "ref_ok": vs["ref_ok"],
                "clips": vs["clips"],
                "minutes": vs["minutes"],
                "candidates": vs["candidates"],
                "langs": vs.get("langs", {}),
                "rejected": vs["rejected"],
                "sovits": (w.get("sovits") or {}).get("file"),
                "gpt": (w.get("gpt") or {}).get("file"),
            },
            "avatar": {
                "avatar_id": acfg.get("avatar_id"),
                "motion": acfg.get("motion"),
                "frames": a_frames,
                "built": a_frames > 0,
                "source_portrait": acfg.get("source_portrait"),
            },
        })

    services = []
    for s in SERVICES:
        up, detail = probe(s["url"])
        services.append({**{k: s[k] for k in ("key", "name", "role", "port")},
                         "up": up, "detail": detail})

    voiced = [k for k in kols if k["voice"]["sovits"] and k["voice"]["gpt"]]
    avatared = [k for k in kols if k["avatar"]["built"]]
    return {
        "generated_at": datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z"),
        "repo": str(REPO),
        "kols": kols,
        "services": services,
        "gpu": gpu_state(),
        "summary": {
            "kols_total": len(kols),
            "kols_with_images": sum(1 for k in kols if k["images"] > 0),
            "kols_with_dataset": sum(1 for k in kols if k["voice"]["clips"] > 0),
            "kols_voiced": len(voiced),
            "voiced_ids": [k["id"] for k in voiced],
            "kols_avatared": len(avatared),
            "avatared_ids": [k["id"] for k in avatared],
        },
    }


def rel(p: Path) -> str:
    return p.relative_to(REPO).as_posix()


def kol_detail(kol_id: str, clip_limit: int = 24) -> dict | None:
    kdir = REPO / "kols" / kol_id
    if not kdir.is_dir():
        return None
    profile = read_json(kdir / "profile.json") or {}
    vcfg = (profile.get("ai_assets") or {}).get("voice") or {}

    images = sorted((p for p in (kdir / "images").rglob("*") if p.suffix.lower() in IMG_EXT),
                    key=lambda p: p.name)
    videos = sorted((p for p in (kdir / "videos").rglob("*") if p.suffix.lower() in VID_EXT),
                    key=lambda p: p.name) if (kdir / "videos").is_dir() else []

    clips = []
    listf = kdir / "voice" / "dataset" / f"{kol_id}.list"
    total_rows = 0
    if listf.is_file():
        rows = [r for r in listf.read_text(encoding="utf-8").splitlines() if r.strip()]
        total_rows = len(rows)
        # Sample evenly across the corpus rather than just the first N, so the preview
        # reflects the whole dataset (both languages, early and late utterances).
        step = max(1, len(rows) // clip_limit)
        for r in rows[::step][:clip_limit]:
            parts = r.split("|")
            if len(parts) != 4:
                continue
            wav = Path(parts[0])
            if not wav.is_absolute():
                wav = REPO / wav
            if wav.is_file():
                clips.append({"src": rel(wav), "lang": parts[2], "text": parts[3],
                              "name": wav.name})

    ref = kdir / "voice" / "ref.wav"
    reftxt = kdir / "voice" / "ref.txt"
    return {
        "id": kol_id,
        "name": profile.get("identity", {}).get("name") or kol_id,
        "name_zh": profile.get("identity", {}).get("name_zh"),
        "handle": profile.get("identity", {}).get("handle"),
        "archetype": profile.get("persona", {}).get("archetype"),
        "voice": vcfg,
        "images": [rel(p) for p in images],
        "videos": [rel(p) for p in videos],
        "clips": clips,
        "clips_total": total_rows,
        "ref": {"src": rel(ref) if ref.is_file() else None,
                "text": reftxt.read_text(encoding="utf-8").strip() if reftxt.is_file() else None},
    }


def resolve_media(rel_path: str) -> Path | None:
    """Map a repo-relative path to a real file, refusing anything outside the repo."""
    try:
        target = (REPO / rel_path).resolve()
    except Exception:
        return None
    if not target.is_file() or target.suffix.lower() not in SAFE_EXT:
        return None
    try:
        target.relative_to(REPO.resolve())   # blocks ../ traversal
    except ValueError:
        return None
    return target


# ----------------------------------------------------------------- rendering

def esc(v) -> str:
    return (str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


CSS = """
*,*::before,*::after{box-sizing:border-box}
:root{
  --bg:#f6f7f9; --panel:#fff; --line:#e3e6ea; --fg:#14171a; --mut:#666e78;
  --ok:#0f8a4c; --bad:#c62b2b; --warn:#a86400; --accent:#2f5fd0; --track:#e8ebef;
}
@media (prefers-color-scheme:dark){
  :root{--bg:#0f1215;--panel:#171b1f;--line:#282e35;--fg:#e7eaee;--mut:#98a1ac;
        --ok:#43c07d;--bad:#ef6a6a;--warn:#e0a33c;--accent:#7aa2f7;--track:#232a31}
}
:root[data-theme=dark]{--bg:#0f1215;--panel:#171b1f;--line:#282e35;--fg:#e7eaee;--mut:#98a1ac;
  --ok:#43c07d;--bad:#ef6a6a;--warn:#e0a33c;--accent:#7aa2f7;--track:#232a31}
:root[data-theme=light]{--bg:#f6f7f9;--panel:#fff;--line:#e3e6ea;--fg:#14171a;--mut:#666e78;
  --ok:#0f8a4c;--bad:#c62b2b;--warn:#a86400;--accent:#2f5fd0;--track:#e8ebef}
body{margin:0;background:var(--bg);color:var(--fg);
  font:14px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,"Noto Sans TC",sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:24px 20px 60px}
h1{font-size:20px;margin:0 0 2px;letter-spacing:-.01em}
h2{font-size:13px;text-transform:uppercase;letter-spacing:.07em;color:var(--mut);
  margin:30px 0 10px;font-weight:600}
.sub{color:var(--mut);font-size:12.5px;margin:0}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px}
.pad{padding:14px 16px}
.grid{display:grid;gap:12px}
.g4{grid-template-columns:repeat(auto-fit,minmax(200px,1fr))}
.g3{grid-template-columns:repeat(auto-fit,minmax(260px,1fr))}
.stat .n{font-size:26px;font-weight:650;letter-spacing:-.02em;font-variant-numeric:tabular-nums}
.stat .l{color:var(--mut);font-size:12px;margin-top:1px}
.dot{width:8px;height:8px;border-radius:50%;display:inline-block;flex:0 0 auto}
.up{background:var(--ok)} .down{background:var(--bad)}
.svc{display:flex;align-items:center;gap:9px}
.svc .nm{font-weight:600}
.svc .rl{color:var(--mut);font-size:12px}
.mono{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:12px}
.scroll{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{text-align:left;padding:9px 11px;border-bottom:1px solid var(--line);white-space:nowrap}
th{color:var(--mut);font-weight:600;font-size:11.5px;text-transform:uppercase;letter-spacing:.05em}
tbody tr:last-child td{border-bottom:0}
tbody tr:hover{background:color-mix(in srgb,var(--accent) 6%,transparent)}
.num{text-align:right;font-variant-numeric:tabular-nums}
.tag{display:inline-block;padding:1.5px 7px;border-radius:999px;font-size:11px;
  border:1px solid var(--line);color:var(--mut);text-decoration:none}
.tag.ok{color:var(--ok);border-color:color-mix(in srgb,var(--ok) 45%,transparent)}
.tag.bad{color:var(--bad);border-color:color-mix(in srgb,var(--bad) 45%,transparent)}
.tag.warn{color:var(--warn);border-color:color-mix(in srgb,var(--warn) 45%,transparent)}
.bar{height:6px;border-radius:4px;background:var(--track);overflow:hidden;margin-top:8px}
.bar>i{display:block;height:100%;background:var(--accent)}
.steps{display:grid;gap:10px;grid-template-columns:repeat(auto-fit,minmax(210px,1fr))}
.step{border:1px solid var(--line);border-radius:10px;padding:13px 15px;background:var(--panel)}
.step .t{font-weight:650;font-size:13px;display:flex;justify-content:space-between;gap:8px}
.step .d{color:var(--mut);font-size:12px;margin-top:3px}
.muted{color:var(--mut)}
footer{margin-top:34px;color:var(--mut);font-size:12px}
a{color:var(--accent)}
.nav{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.btn{display:inline-block;padding:7px 14px;border-radius:8px;border:1px solid var(--line);
  background:var(--panel);color:var(--fg);font-size:13px;cursor:pointer;text-decoration:none}
.btn:hover{border-color:var(--accent)}
.btn.pri{background:var(--accent);color:#fff;border-color:var(--accent);font-weight:600}
.btn:disabled{opacity:.45;cursor:not-allowed}
.thumbs{display:grid;gap:8px;grid-template-columns:repeat(auto-fill,minmax(128px,1fr))}
.thumbs a{display:block;border:1px solid var(--line);border-radius:8px;overflow:hidden;
  background:var(--panel);aspect-ratio:3/4}
.thumbs img{width:100%;height:100%;object-fit:cover;display:block}
.cliplist{display:grid;gap:8px}
.clip{display:grid;grid-template-columns:56px 220px 1fr;gap:10px;align-items:center;
  padding:8px 12px;border:1px solid var(--line);border-radius:8px;background:var(--panel)}
.clip audio{width:220px;height:32px}
.clip .tx{font-size:13px;line-height:1.35}
@media(max-width:760px){.clip{grid-template-columns:1fr}.clip audio{width:100%}}
video{width:100%;background:#000;border-radius:10px;display:block}
textarea{width:100%;min-height:74px;padding:10px 12px;border-radius:8px;border:1px solid var(--line);
  background:var(--panel);color:var(--fg);font:inherit;resize:vertical}
#log{max-height:190px;overflow:auto;white-space:pre-wrap}
"""

JS_COMMON = """
const t=localStorage.getItem('kol-theme');if(t)document.documentElement.dataset.theme=t;
function toggleTheme(){const r=document.documentElement;
 const cur=r.dataset.theme||(matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light');
 const nxt=cur==='dark'?'light':'dark';r.dataset.theme=nxt;localStorage.setItem('kol-theme',nxt);}
"""

JS_REFRESH = """
let secs=15;const el=()=>document.getElementById('cd');
setInterval(()=>{secs--;if(secs<=0){location.reload();return}if(el())el().textContent=secs;},1000);
"""

JS_DEMO = """
let pc=null, sid=null;
const $=id=>document.getElementById(id);
function log(m){const l=$('log');l.textContent+=m+"\\n";l.scrollTop=l.scrollHeight;}
function setState(s,cls){const b=$('state');b.textContent=s;b.className='tag '+(cls||'');}

async function connect(){
  $('btnConnect').disabled=true;
  try{
    setState('connecting','warn'); log('creating peer connection...');
    pc=new RTCPeerConnection();
    pc.addTransceiver('video',{direction:'recvonly'});
    pc.addTransceiver('audio',{direction:'recvonly'});
    pc.ontrack=e=>{ log('track: '+e.track.kind); if(e.streams[0]) $('vid').srcObject=e.streams[0]; };
    pc.oniceconnectionstatechange=()=>log('ice: '+pc.iceConnectionState);

    await pc.setLocalDescription(await pc.createOffer());
    // LiveTalking does not accept trickled candidates: wait for gathering to finish.
    if(pc.iceGatheringState!=='complete'){
      await new Promise(r=>{const c=()=>{if(pc.iceGatheringState==='complete'){
        pc.removeEventListener('icegatheringstatechange',c);r();}};
        pc.addEventListener('icegatheringstatechange',c);setTimeout(r,4000);});
    }
    log('posting offer...');
    const res=await fetch('/lt/offer',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({sdp:pc.localDescription.sdp,type:pc.localDescription.type})});
    if(!res.ok) throw new Error('offer failed: HTTP '+res.status+' '+(await res.text()).slice(0,200));
    const ans=await res.json();
    sid=ans.sessionid; log('sessionid: '+sid);
    await pc.setRemoteDescription(ans);
    setState('connected','ok'); $('btnSpeak').disabled=false; $('btnStop').disabled=false;
    log('ready — type something and press Speak.');
  }catch(e){ setState('failed','bad'); log('ERROR '+e.message);
    log('Is LiveTalking running?  .\\\\tools\\\\livetalking\\\\run_livetalking.ps1 lena-chen');
    $('btnConnect').disabled=false; }
}

async function speak(){
  const text=$('txt').value.trim(); if(!text||sid===null) return;
  $('btnSpeak').disabled=true;
  try{
    const r=await fetch('/lt/human',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({sessionid:sid,text:text,type:'echo',interrupt:true})});
    log('/human -> '+(await r.text()).trim());
  }catch(e){ log('ERROR '+e.message); }
  $('btnSpeak').disabled=false;
}

async function stop(){
  try{ if(sid!==null) await fetch('/lt/interrupt_talk',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify({sessionid:sid})}); }catch(e){}
  if(pc){pc.close();pc=null;} sid=null; $('vid').srcObject=null;
  setState('disconnected',''); $('btnConnect').disabled=false;
  $('btnSpeak').disabled=true; $('btnStop').disabled=true; log('closed.');
}
function preset(s){$('txt').value=s;}
"""


JS_REPLIES = """
const $=id=>document.getElementById(id);
async function post(url,body){
  const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify(body)});
  return r.json();
}
async function makeDraft(){
  const kol=$('kol').value, msg=$('msg').value.trim();
  if(!msg) return;
  $('mkbtn').disabled=true; $('mkbtn').textContent='drafting…';
  try{ await post('/api/reply/draft',{kol_id:kol,message:msg}); location.reload(); }
  catch(e){ alert('draft failed: '+e.message); $('mkbtn').disabled=false;
            $('mkbtn').textContent='Draft reply'; }
}
async function decide(kol,id,action,speak){
  const ta=document.querySelector(`textarea[data-id="${id}"]`);
  const body={kol_id:kol,id:id,action:action};
  if(ta && action!=='reject') body.text=ta.value;
  if(speak) body.speak=true;
  const res=await post('/api/reply/decide',body);
  if(res.status==='blocked'){ alert('Blocked by the rule check: '+(res.violations||[]).join(', ')
    +'\\nEdit the text and try again.'); }
  location.reload();
}
"""


JS_STUDIO = """
const $=id=>document.getElementById(id);
function tab(name){
  ['tts','clone','character'].forEach(t=>{
    $('tab-'+t).style.display = (t===name)?'block':'none';
    $('btn-'+t).className = 'btn' + ((t===name)?' pri':'');
  });
}
async function post(url,body){
  const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify(body)});
  const j=await r.json();
  if(j.error) throw new Error(j.error);
  return j;
}
function busy(id,on,label){const b=$(id);b.disabled=on;b.textContent=on?'working…':label;}
function player(id,src){
  $(id).innerHTML = '<audio controls autoplay style="width:100%" src="'+src+
    '?t='+Date.now()+'"></audio><div style="margin-top:6px"><a class="tag" download href="'+
    src+'">download wav</a></div>';
}
function charLang(){
  const o=$('character').selectedOptions[0];
  const lg=o?o.dataset.lang:'en';
  $('lang').value = lg;
  return lg;
}
async function speak(){
  busy('btn-say',true,'Speak');
  try{
    const r=await post('/api/studio/say',{character:$('character').value,
      text:$('script').value, speed:parseFloat($('speed').value),
      volume_db:parseFloat($('vol').value), lang:$('lang').value});
    player('out', r.url);
  }catch(e){ alert('Synthesis failed:\\n'+e.message); }
  busy('btn-say',false,'Speak');
}
async function makeScript(){
  busy('btn-script',true,'Write script from scenario');
  try{
    const r=await post('/api/studio/script',{character:$('character').value,
      scenario:$('scenario').value, seconds:parseInt($('secs').value)});
    $('script').value=r.script;
  }catch(e){ alert('Script generation failed:\\n'+e.message); }
  busy('btn-script',false,'Write script from scenario');
}
async function doClone(){
  const f=$('ref').files[0];
  if(!f){ alert('Choose a reference audio file first (wav or mp3, 5-15 seconds).'); return; }
  busy('btn-clone2',true,'Clone & speak');
  try{
    const fd=new FormData(); fd.append('file',f);
    const up=await fetch('/api/studio/upload',{method:'POST',body:fd}).then(r=>r.json());
    if(up.error) throw new Error(up.error);
    $('reftext').value = up.transcript || $('reftext').value;
    const r=await post('/api/studio/clone',{ref:up.path, ref_text:$('reftext').value,
      ref_lang:up.language||'en', text:$('clonescript').value,
      speed:parseFloat($('cspeed').value), volume_db:parseFloat($('cvol').value)});
    player('cout', r.url);
  }catch(e){ alert('Clone failed:\\n'+e.message); }
  busy('btn-clone2',false,'Clone & speak');
}
async function genChar(){
  busy('btn-char',true,'Generate character');
  try{
    const r=await post('/api/studio/character',{prompt:$('charprompt').value});
    $('charout').textContent=JSON.stringify(r.character,null,2);
    $('saverow').style.display='flex';
    window.__char=r.character;
  }catch(e){ alert('Generation failed:\\n'+e.message); }
  busy('btn-char',false,'Generate character');
}
async function saveChar(){
  const id=$('charid').value.trim();
  if(!/^[a-z0-9-]{3,40}$/.test(id)){ alert('Use a lowercase id like "mia-lin".'); return; }
  try{
    const r=await post('/api/studio/save_character',{id:id,character:window.__char});
    alert('Saved to '+r.path+'\\n\\nNext: build a voice with\\n  bootstrap_timbre.py '+id);
  }catch(e){ alert('Save failed:\\n'+e.message); }
}
document.addEventListener('DOMContentLoaded',()=>{tab('tts');charLang();});
"""


def page(title: str, body: str, js: str = "") -> str:
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{esc(title)}</title><style>{CSS}</style></head><body>{body}'
            f'<script>{JS_COMMON}{js}</script></body></html>')


def topbar(subtitle: str, extra: str = "") -> str:
    return (f'<div style="display:flex;justify-content:space-between;align-items:flex-start;'
            f'gap:14px;flex-wrap:wrap;margin-bottom:6px">'
            f'<div><h1>AI-KOL System</h1><p class="sub">{subtitle}</p></div>'
            f'<div class="nav"><a class="btn" href="/">Dashboard</a>'
            f'<a class="btn" href="/studio">Voice Studio</a>'
            f'<a class="btn" href="/demo">Live demo</a>'
            f'<a class="btn" href="/replies">Reply queue</a>{extra}'
            f'<button class="btn" onclick="toggleTheme()">theme</button></div></div>')


def render_dashboard(st: dict) -> str:
    s = st["summary"]
    gpu = st["gpu"]

    stats = "".join(
        f'<div class="panel pad stat"><div class="n">{v}</div><div class="l">{esc(l)}</div></div>'
        for v, l in [
            (s["kols_total"], "KOL personas"),
            (s["kols_with_dataset"], "with voice dataset"),
            (s["kols_voiced"], "voice fine-tuned"),
            (s.get("kols_avatared", 0), "avatar built (own face)"),
        ])

    svc = ""
    for x in st["services"]:
        cls = "up" if x["up"] else "down"
        state = "running" if x["up"] else "not running"
        svc += (f'<div class="panel pad"><div class="svc"><span class="dot {cls}"></span>'
                f'<span class="nm">{esc(x["name"])}</span>'
                f'<span class="tag {"ok" if x["up"] else "bad"}">{state}</span></div>'
                f'<div class="rl">{esc(x["role"])}</div>'
                f'<div class="mono muted" style="margin-top:5px">:{x["port"]} · {esc(x["detail"])}</div></div>')

    if gpu:
        pct = round(gpu["used_mb"] / gpu["total_mb"] * 100)
        gpu_html = (
            f'<div class="panel pad"><div class="svc"><span class="nm">{esc(gpu["name"])}</span></div>'
            f'<div class="rl">{gpu["used_mb"]:,} / {gpu["total_mb"]:,} MiB used · '
            f'{gpu["total_mb"]-gpu["used_mb"]:,} MiB free · {gpu["util_pct"]}% util · {gpu["temp_c"]}°C</div>'
            f'<div class="bar"><i style="width:{pct}%"></i></div></div>')
    else:
        gpu_html = '<div class="panel pad muted">nvidia-smi unavailable</div>'

    lip = next((x for x in st["services"] if x["key"] == "livetalking"), {})
    steps = [
        ("1 · Persona", f'{s["kols_total"]} defined',
         "profile.json + character.md per KOL", "ok" if s["kols_total"] else "bad"),
        ("2 · Images", f'{s["kols_with_images"]}/{s["kols_total"]} have seeds',
         "face-lock LoRA still pending", "warn"),
        ("3 · Voice", f'{s["kols_voiced"]} fine-tuned',
         "GPT-SoVITS v2Pro, ZH+EN", "ok" if s["kols_voiced"] else "warn"),
        ("4 · Lip-sync", f'{s.get("kols_avatared", 0)} avatar built',
         "own face + own voice, wav2lip", "ok" if s.get("kols_avatared") else "warn"),
    ]
    steps_html = "".join(
        f'<div class="step"><div class="t"><span>{esc(t)}</span>'
        f'<span class="tag {c}">{esc(v)}</span></div><div class="d">{esc(d)}</div></div>'
        for t, v, d, c in steps)

    rows = ""
    for k in st["kols"]:
        v = k["voice"]
        if v["sovits"] and v["gpt"]:
            vtag = '<span class="tag ok">fine-tuned</span>'
        elif v["clips"]:
            vtag = '<span class="tag warn">dataset ready</span>'
        elif v["engine"]:
            vtag = '<span class="tag">planned</span>'
        else:
            vtag = '<span class="muted">—</span>'
        mins = v["minutes"]
        mins_txt = f'{mins:.1f}' if isinstance(mins, (int, float)) and mins else ("?" if v["clips"] else "—")
        langs = " ".join(f'{a}&nbsp;{b}' for a, b in (v.get("langs") or {}).items()) or "—"
        av = k.get("avatar") or {}
        atag = (f'<span class="tag ok">{esc(av["avatar_id"])}</span>' if av.get("built")
                else '<span class="muted">—</span>')
        rows += (
            f'<tr><td><a href="/kol/{esc(k["id"])}" style="font-weight:600;text-decoration:none">'
            f'{esc(k["name"])}</a>'
            f'<div class="mono muted">{esc(k["id"])}</div></td>'
            f'<td><span class="tag">{esc(k["status"] or "—")}</span></td>'
            f'<td class="num">{k["images"] or "—"}</td>'
            f'<td class="num">{k["videos"] or "—"}</td>'
            f'<td>{vtag}</td>'
            f'<td class="num">{v["clips"] or "—"}</td>'
            f'<td class="num">{mins_txt}</td>'
            f'<td class="mono">{langs}</td>'
            f'<td>{atag}</td>'
            f'<td><a class="tag" href="/kol/{esc(k["id"])}">browse data →</a></td></tr>')

    qc = ""
    for k in st["kols"]:
        rej = k["voice"]["rejected"]
        if not rej:
            continue
        items = " ".join(f'<span class="tag warn">{esc(a)} {b}</span>' for a, b in rej.items())
        qc += (f'<div class="panel pad"><div style="font-weight:600">{esc(k["name"])}</div>'
               f'<div class="rl">{k["voice"]["clips"]} accepted of {k["voice"]["candidates"]} candidates</div>'
               f'<div style="margin-top:7px;display:flex;gap:5px;flex-wrap:wrap">{items}</div></div>')
    qc_section = f'<h2>Dataset QC — rejected clips by reason</h2><div class="grid g3">{qc}</div>' if qc else ""

    body = f"""<div class="wrap">
{topbar(f'{esc(st["generated_at"])} · refresh in <span id="cd">15</span>s · <a href="/api/state">JSON</a>')}
<h2>Pipeline</h2><div class="steps">{steps_html}</div>
<h2>Overview</h2><div class="grid g4">{stats}</div>
<h2>Services &amp; GPU</h2><div class="grid g3">{svc}{gpu_html}</div>
<h2>KOL roster <span class="muted" style="text-transform:none;letter-spacing:0">— click a name to browse its data</span></h2>
<div class="panel scroll"><table>
<thead><tr><th>KOL</th><th>Status</th><th class="num">Imgs</th><th class="num">Vids</th>
<th>Voice</th><th class="num">Clips</th><th class="num">Min</th><th>Langs</th>
<th>Avatar</th><th></th></tr></thead>
<tbody>{rows}</tbody></table></div>
{qc_section}
<footer>Reads <span class="mono">kols/*/profile.json</span>,
<span class="mono">voice/dataset/manifest.json</span>, weight dirs and live service ports on every
request — nothing here is cached or hardcoded.<br>
Repo: <span class="mono">{esc(st["repo"])}</span></footer>
</div>"""
    return page("AI-KOL System — tracker", body, JS_REFRESH)


def render_kol(d: dict) -> str:
    v = d["voice"] or {}
    name = d["name"] + (f' ({d["name_zh"]})' if d.get("name_zh") else "")

    meta = []
    for label, val in [("Handle", d.get("handle")), ("Engine", v.get("engine")),
                       ("Version", v.get("gsv_version")), ("Voice status", v.get("status")),
                       ("Source", v.get("source")), ("Bootstrap timbre", v.get("timbre"))]:
        if val:
            meta.append(f'<div><span class="muted">{esc(label)}</span><br>'
                        f'<span class="mono">{esc(val)}</span></div>')
    meta_html = (f'<div class="panel pad" style="display:grid;gap:12px;'
                 f'grid-template-columns:repeat(auto-fit,minmax(160px,1fr))">'
                 f'{"".join(meta)}</div>') if meta else ""

    ref_html = ""
    if d["ref"]["src"]:
        ref_html = (f'<h2>Reference clip <span class="muted" style="text-transform:none;'
                    f'letter-spacing:0">— the prompt GPT-SoVITS speaks from</span></h2>'
                    f'<div class="panel pad"><audio controls preload="none" '
                    f'src="/media?path={urllib.parse.quote(d["ref"]["src"])}" style="width:100%"></audio>'
                    f'<div style="margin-top:8px">{esc(d["ref"]["text"] or "")}</div></div>')

    imgs = ""
    if d["images"]:
        cells = "".join(
            f'<a href="/media?path={urllib.parse.quote(p)}" target="_blank" title="{esc(Path(p).name)}">'
            f'<img loading="lazy" src="/media?path={urllib.parse.quote(p)}" alt=""></a>'
            for p in d["images"][:48])
        more = (f'<p class="muted" style="margin:8px 0 0">showing 48 of {len(d["images"])}</p>'
                if len(d["images"]) > 48 else "")
        imgs = f'<h2>Images ({len(d["images"])})</h2><div class="thumbs">{cells}</div>{more}'

    vids = ""
    if d["videos"]:
        items = "".join(
            f'<div class="panel pad"><div class="mono muted" style="margin-bottom:6px">'
            f'{esc(Path(p).name)}</div>'
            f'<video controls preload="metadata" src="/media?path={urllib.parse.quote(p)}"></video></div>'
            for p in d["videos"][:6])
        vids = f'<h2>Videos ({len(d["videos"])})</h2><div class="grid g3">{items}</div>'

    clips = ""
    if d["clips"]:
        rows = "".join(
            f'<div class="clip"><span class="tag">{esc(c["lang"])}</span>'
            f'<audio controls preload="none" src="/media?path={urllib.parse.quote(c["src"])}"></audio>'
            f'<div class="tx">{esc(c["text"])}</div></div>' for c in d["clips"])
        clips = (f'<h2>Training clips <span class="muted" style="text-transform:none;letter-spacing:0">'
                 f'— {len(d["clips"])} sampled evenly from {d["clips_total"]}</span></h2>'
                 f'<div class="cliplist">{rows}</div>')

    empty = ""
    if not (imgs or vids or clips or ref_html):
        empty = ('<div class="panel pad muted">No media yet for this KOL — no images, '
                 'videos, or voice dataset on disk.</div>')

    body = f"""<div class="wrap">
{topbar(f'<a href="/">← roster</a> · <span class="mono">{esc(d["id"])}</span> · <a href="/api/kol/{esc(d["id"])}">JSON</a>')}
<h2 style="margin-top:18px">{esc(name)}</h2>
<p class="sub" style="margin:-6px 0 12px">{esc(d.get("archetype") or "")}</p>
{meta_html}
{ref_html}
{clips}
{imgs}
{vids}
{empty}
<footer>Media is served read-only from inside the repo.</footer>
</div>"""
    return page(f'{d["name"]} — AI-KOL', body)


def render_replies(st: dict, kol_id: str) -> str:
    """Review screen for the approve-before-send queue."""
    import reply_queue as rq

    items = rq.load_all(kol_id)
    counts = rq.stats(kol_id)
    mode = rq.policy_mode(kol_id)
    voiced = [k["id"] for k in st["kols"] if k["voice"]["sovits"]] or [kol_id]

    opts = "".join(f'<option value="{esc(k)}"{" selected" if k == kol_id else ""}>{esc(k)}</option>'
                   for k in [k["id"] for k in st["kols"]])

    badge = {"pending": "warn", "approved": "ok", "rejected": "", "blocked": "bad"}
    cards = ""
    for r in items[:40]:
        stt = r.get("status", "pending")
        text = r.get("final_text") or r.get("draft") or ""
        vio = r.get("violations") or []
        when = datetime.fromtimestamp(r.get("created", 0)).strftime("%m-%d %H:%M") \
            if r.get("created") else ""
        actions = ""
        if stt in ("pending", "blocked"):
            actions = (
                f'<div class="nav" style="margin-top:8px">'
                f'<button class="btn pri" onclick="decide(\'{esc(kol_id)}\',\'{esc(r["id"])}\',\'edit\',false)">'
                f'Approve</button>'
                f'<button class="btn" onclick="decide(\'{esc(kol_id)}\',\'{esc(r["id"])}\',\'edit\',true)">'
                f'Approve &amp; speak</button>'
                f'<button class="btn" onclick="decide(\'{esc(kol_id)}\',\'{esc(r["id"])}\',\'reject\',false)">'
                f'Reject</button></div>')
        body_field = (f'<textarea data-id="{esc(r["id"])}" rows="3">{esc(text)}</textarea>'
                      if stt in ("pending", "blocked")
                      else f'<div style="margin-top:6px">{esc(text)}</div>')
        vio_html = (f'<div class="tag bad" style="margin-top:6px">rule check: '
                    f'{esc(", ".join(vio))} — edit before approving</div>') if vio else ""
        cards += (
            f'<div class="panel pad" style="margin-bottom:10px">'
            f'<div class="svc" style="justify-content:space-between">'
            f'<div><span class="tag {badge.get(stt, "")}">{esc(stt)}</span> '
            f'<span class="mono muted">{esc(r["id"])}</span> '
            f'<span class="muted" style="font-size:12px">{esc(when)}</span></div></div>'
            f'<div style="margin-top:8px"><span class="muted" style="font-size:12px">'
            f'follower asked</span><div>{esc(r.get("follower", ""))}</div></div>'
            f'<div style="margin-top:8px"><span class="muted" style="font-size:12px">'
            f'drafted reply</span>{body_field}</div>'
            f'{vio_html}{actions}</div>')

    if not cards:
        cards = ('<div class="panel pad muted">No drafts yet. Paste a follower comment above '
                 'to generate one.</div>')

    stat_cards = "".join(
        f'<div class="panel pad stat"><div class="n">{counts.get(k, 0)}</div>'
        f'<div class="l">{esc(k)}</div></div>'
        for k in ("pending", "blocked", "approved", "rejected"))

    body = f"""<div class="wrap">
{topbar('Approve-before-send — the AI drafts, a human decides')}
<div class="panel pad" style="margin-top:14px;border-color:var(--accent)">
  <b>policy_mode: {esc(mode)}</b> — nothing here reaches a follower until someone approves it.
  <div class="muted" style="font-size:12px;margin-top:4px">
  Tested: a 7B model given these rules still denied being AI, invented a price, and fell for a
  jailbreak. Drafts are rule-checked, and an <i>edited</i> reply is re-checked too — a human can
  paste in a price by accident just as easily.</div>
</div>
<h2>New draft</h2>
<div class="panel pad">
  <div class="nav" style="margin-bottom:8px">
    <select id="kol" class="btn" onchange="location.href='/replies?kol='+this.value">{opts}</select>
    <span class="muted" style="font-size:12px">voice trained: {esc(", ".join(voiced))}</span>
  </div>
  <textarea id="msg" rows="2" placeholder="Paste what the follower said…"></textarea>
  <div class="nav" style="margin-top:8px">
    <button class="btn pri" id="mkbtn" onclick="makeDraft()">Draft reply</button>
  </div>
</div>
<h2>Queue</h2>
<div class="grid g4">{stat_cards}</div>
<div style="margin-top:14px">{cards}</div>
<footer>Append-only log at <span class="mono">kols/{esc(kol_id)}/replies/queue.jsonl</span> —
every draft and decision is recorded, so the review trail is auditable.<br>
"Approve &amp; speak" needs a live avatar session: open the demo and press Connect first.</footer>
</div>"""
    return page("Reply queue — AI-KOL", body, JS_REPLIES)


def render_studio(st: dict) -> str:
    """TTS / voice-clone / character-creation studio."""
    import voice_studio as vsx

    gsv = next((x for x in st["services"] if x["key"] == "gpt_sovits"), {})
    olm = next((x for x in st["services"] if x["key"] == "ollama"), {})

    warn = ""
    if not gsv.get("up"):
        warn = ('<div class="panel pad" style="border-color:var(--bad)">'
                '<b style="color:var(--bad)">Voice engine offline.</b> Synthesis and cloning '
                'both need GPT-SoVITS api_v2 on :9880.<pre class="mono" '
                'style="white-space:pre-wrap;margin:8px 0 0">cd GPT-SoVITS; '
                '.\\.venv\\Scripts\\python.exe api_v2.py -a 127.0.0.1 -p 9880 '
                '-c GPT_SoVITS/configs/tts_infer.yaml</pre></div>')
    if not olm.get("up"):
        warn += ('<div class="panel pad" style="border-color:var(--warn);margin-top:8px">'
                 '<b style="color:var(--warn)">Ollama offline.</b> Writing a script from a '
                 'scenario and generating a character both need it; typing a script directly '
                 'still works.</div>')

    opts, samples = "", {}
    for c in vsx.characters():
        tag = "fine-tuned" if c["kind"] == "finetuned" else "zero-shot"
        opts += (f'<option value="{esc(c["id"])}" data-lang="{c["lang"]}">'
                 f'{esc(c["name"])} — {vsx.LANGS[c["lang"]]} ({tag})</option>')
        samples[c["id"]] = c["sample"]

    cards = "".join(
        f'<div class="panel pad"><div style="font-weight:600">{esc(c["name"])}</div>'
        f'<div class="rl">{esc(c["blurb"])}</div>'
        f'<div style="margin-top:6px"><span class="tag">{esc(vsx.LANGS[c["lang"]])}</span> '
        f'<span class="tag {"ok" if c["kind"]=="finetuned" else ""}">'
        f'{"fine-tuned" if c["kind"]=="finetuned" else "zero-shot"}</span></div></div>'
        for c in vsx.characters())

    default_script = vsx.CHARACTERS[0]["sample"]

    body = f"""<div class="wrap">
{topbar('Voice Studio — text to speech, voice cloning, character creation')}
{warn}
<div class="nav" style="margin:14px 0">
  <button class="btn pri" id="btn-tts" onclick="tab('tts')">Text to speech</button>
  <button class="btn" id="btn-clone" onclick="tab('clone')">Voice clone</button>
  <button class="btn" id="btn-character" onclick="tab('character')">Character</button>
</div>

<div id="tab-tts">
  <h2>Characters <span class="muted" style="text-transform:none;letter-spacing:0">— 3 English,
  2 Taiwan Mandarin</span></h2>
  <div class="grid g3">{cards}</div>
  <h2>Script</h2>
  <div class="panel pad">
    <div class="grid" style="grid-template-columns:2fr 1fr 1fr 1fr;gap:10px;align-items:end">
      <div><div class="muted" style="font-size:12px">Character</div>
        <select id="character" class="btn" style="width:100%" onchange="charLang()">{opts}</select></div>
      <div><div class="muted" style="font-size:12px">Language</div>
        <select id="lang" class="btn" style="width:100%">
          <option value="auto">auto (mixes)</option><option value="en">English</option>
          <option value="zh">Taiwan Mandarin</option></select></div>
      <div><div class="muted" style="font-size:12px">Speed <span id="sv">1.00</span>×</div>
        <input id="speed" type="range" min="0.6" max="1.5" step="0.05" value="1"
               style="width:100%" oninput="document.getElementById('sv').textContent=(+this.value).toFixed(2)"></div>
      <div><div class="muted" style="font-size:12px">Volume <span id="vv">0</span> dB</div>
        <input id="vol" type="range" min="-12" max="9" step="1" value="0" style="width:100%"
               oninput="document.getElementById('vv').textContent=this.value"></div>
    </div>
    <div style="margin-top:12px">
      <div class="muted" style="font-size:12px">Scenario — describe the situation and let her
        write the script, or skip and type it yourself</div>
      <div class="grid" style="grid-template-columns:1fr 110px 220px;gap:8px;align-items:end">
        <input id="scenario" class="btn" style="width:100%;text-align:left"
               placeholder="e.g. unboxing a new sunscreen, honest pros and cons">
        <div><div class="muted" style="font-size:12px">Target sec</div>
          <input id="secs" class="btn" style="width:100%" type="number" value="18" min="5" max="60"></div>
        <button class="btn" id="btn-script" onclick="makeScript()">Write script from scenario</button>
      </div>
    </div>
    <div style="margin-top:12px">
      <div class="muted" style="font-size:12px">Script to speak</div>
      <textarea id="script" rows="4">{esc(default_script)}</textarea>
    </div>
    <div class="nav" style="margin-top:10px">
      <button class="btn pri" id="btn-say" onclick="speak()">Speak</button>
    </div>
    <div id="out" style="margin-top:12px"></div>
  </div>
</div>

<div id="tab-clone" style="display:none">
  <h2>Voice clone <span class="muted" style="text-transform:none;letter-spacing:0">— zero-shot,
  no training needed</span></h2>
  <div class="panel pad">
    <div class="muted" style="font-size:12px">Reference audio — 5 to 15 seconds of clean speech,
      one speaker, no music. The transcript is filled in automatically.</div>
    <input id="ref" type="file" accept="audio/*" class="btn" style="width:100%;margin-top:6px">
    <div style="margin-top:10px">
      <div class="muted" style="font-size:12px">Reference transcript (auto-filled after upload;
        it must match the audio or the clone degrades)</div>
      <textarea id="reftext" rows="2" placeholder="filled in from the uploaded audio"></textarea>
    </div>
    <div style="margin-top:10px">
      <div class="muted" style="font-size:12px">Script to speak in that voice</div>
      <textarea id="clonescript" rows="3">This serum is genuinely worth the money, and I do not say that often.</textarea>
    </div>
    <div class="grid" style="grid-template-columns:1fr 1fr;gap:10px;margin-top:10px">
      <div><div class="muted" style="font-size:12px">Speed <span id="csv">1.00</span>×</div>
        <input id="cspeed" type="range" min="0.6" max="1.5" step="0.05" value="1" style="width:100%"
               oninput="document.getElementById('csv').textContent=(+this.value).toFixed(2)"></div>
      <div><div class="muted" style="font-size:12px">Volume <span id="cvv">0</span> dB</div>
        <input id="cvol" type="range" min="-12" max="9" step="1" value="0" style="width:100%"
               oninput="document.getElementById('cvv').textContent=this.value"></div>
    </div>
    <div class="nav" style="margin-top:10px">
      <button class="btn pri" id="btn-clone2" onclick="doClone()">Clone &amp; speak</button>
    </div>
    <div id="cout" style="margin-top:12px"></div>
    <p class="muted" style="font-size:12px;margin:12px 0 0">Only clone a voice you have the right
      to use. A fine-tuned voice (20-30 min of audio) sounds markedly better than zero-shot —
      see tools/voice_crawl for that path.</p>
  </div>
</div>

<div id="tab-character" style="display:none">
  <h2>Create a character</h2>
  <div class="panel pad">
    <div class="muted" style="font-size:12px">Describe the KOL you want. Age, market, product
      area, personality, language.</div>
    <textarea id="charprompt" rows="3">A 26-year-old Taiwanese fitness and healthy-food KOL who sells protein snacks, cheerful and science-minded, speaks Taiwan Mandarin</textarea>
    <div class="nav" style="margin-top:10px">
      <button class="btn pri" id="btn-char" onclick="genChar()">Generate character</button>
    </div>
    <pre id="charout" class="mono panel pad" style="margin-top:12px;white-space:pre-wrap;
      background:var(--bg);max-height:340px;overflow:auto"></pre>
    <div class="nav" id="saverow" style="display:none;margin-top:10px;align-items:center">
      <input id="charid" class="btn" placeholder="kol id e.g. mia-lin" style="text-align:left">
      <button class="btn" onclick="saveChar()">Save as a KOL profile</button>
      <span class="muted" style="font-size:12px">creates kols/&lt;id&gt;/profile.json</span>
    </div>
  </div>
  <h2>Existing characters</h2>
  <div class="panel scroll"><table><thead><tr><th>KOL</th><th>Voice</th><th>Avatar</th></tr></thead>
  <tbody>{"".join(
      f'<tr><td><a href="/kol/{esc(k["id"])}">{esc(k["name"])}</a></td>'
      f'<td>{"<span class=tag-ok>fine-tuned</span>" if k["voice"]["sovits"] else ("dataset only" if k["voice"]["clips"] else "—")}</td>'
      f'<td>{esc(k["avatar"]["avatar_id"]) if k["avatar"]["built"] else "—"}</td></tr>'
      for k in st["kols"])}</tbody></table></div>
</div>

<footer>Synthesis runs on the local GPT-SoVITS server; nothing is sent to a third party.
Renders are written to <span class="mono">kols/_studio/out/</span>.</footer>
</div>"""
    return page("Voice Studio — AI-KOL", body, JS_STUDIO)


def render_demo(st: dict) -> str:
    lt = next((x for x in st["services"] if x["key"] == "livetalking"), {})
    gsv = next((x for x in st["services"] if x["key"] == "gpt_sovits"), {})
    voiced = st["summary"]["voiced_ids"]

    warn = ""
    if not lt.get("up") or not gsv.get("up"):
        missing = []
        if not lt.get("up"):
            missing.append("LiveTalking (:8010)")
        if not gsv.get("up"):
            missing.append("GPT-SoVITS api_v2 (:9880)")
        warn = (f'<div class="panel pad" style="border-color:var(--bad)">'
                f'<b style="color:var(--bad)">Not ready:</b> {esc(", ".join(missing))} '
                f'{"is" if len(missing)==1 else "are"} not running.<br>'
                f'<span class="muted">Start the voice first, then the avatar — LiveTalking calls '
                f'GPT-SoVITS for every utterance, so without it the avatar would speak in a '
                f'generic voice instead of the cloned one.</span>'
                f'<pre class="mono" style="white-space:pre-wrap;margin:10px 0 0">'
                f'cd GPT-SoVITS; .\\.venv\\Scripts\\python.exe api_v2.py -a 127.0.0.1 -p 9880 -c GPT_SoVITS/configs/tts_infer.yaml\n'
                f'.\\tools\\livetalking\\run_livetalking.ps1 {esc(voiced[0] if voiced else "lena-chen")}</pre></div>')

    presets = [
        "大家好，我是 Lena。今天分享一個好物 real talk。",
        "Honestly, this is my favourite thing I have tried all month.",
        "這罐精華我用了三週，真的有感，但敏感肌要小心。",
    ]
    chips = " ".join(
        f'<button class="btn" onclick="preset({json.dumps(p, ensure_ascii=False)})">{esc(p[:34])}…</button>'
        for p in presets)

    body = f"""<div class="wrap">
{topbar('Live avatar demo — type text, hear the cloned voice, watch the lip-sync')}
{warn}
<div class="grid" style="grid-template-columns:minmax(300px,1fr) minmax(320px,1.1fr);margin-top:14px">
  <div class="panel pad">
    <div class="svc" style="margin-bottom:10px">
      <span class="nm">Avatar stream</span><span id="state" class="tag">disconnected</span>
    </div>
    <video id="vid" autoplay playsinline></video>
    <div class="nav" style="margin-top:10px">
      <button class="btn pri" id="btnConnect" onclick="connect()">Connect</button>
      <button class="btn" id="btnStop" onclick="stop()" disabled>Disconnect</button>
    </div>
    <p class="muted" style="font-size:12px;margin:10px 0 0">
      Audio is unmuted on purpose — the whole point is to hear the cloned voice.
      Video and audio arrive peer-to-peer over WebRTC; only signalling passes through this page.</p>
  </div>
  <div class="panel pad">
    <div class="nm" style="font-weight:600;margin-bottom:8px">Say something</div>
    <textarea id="txt">大家好，我是 Lena。今天分享一個好物 real talk。</textarea>
    <div class="nav" style="margin-top:10px">
      <button class="btn pri" id="btnSpeak" onclick="speak()" disabled>Speak</button>
    </div>
    <div class="muted" style="font-size:12px;margin:12px 0 6px">Presets (mixed ZH/EN is intentional —
      it exercises per-segment language detection):</div>
    <div class="nav">{chips}</div>
    <div class="muted" style="font-size:12px;margin:14px 0 6px">Log</div>
    <div id="log" class="panel pad mono" style="background:var(--bg)"></div>
  </div>
</div>
<footer>Connect performs the WebRTC handshake that <span class="mono">/human</span> needs — the same
flow <span class="mono">tools/livetalking/verify_lipsync.py</span> automates headlessly.<br>
The face is LiveTalking's stock demo avatar; the <i>voice</i> is the fine-tuned KOL voice.</footer>
</div>"""
    return page("Live avatar demo — AI-KOL", body, JS_DEMO)


# -------------------------------------------------------------------- handler

class Handler(BaseHTTPRequestHandler):
    server_version = "AIKOLDash/1.1"

    def log_message(self, *args):  # keep the console clean
        pass

    def _send(self, body: bytes, ctype: str, status: int = 200, extra: dict | None = None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, status: int = 200):
        self._send(json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8"),
                   "application/json; charset=utf-8", status)

    def _html(self, html: str, status: int = 200):
        self._send(html.encode("utf-8"), "text/html; charset=utf-8", status)

    # -- media ------------------------------------------------------------
    def _serve_media(self, query: str):
        rel_path = urllib.parse.parse_qs(query).get("path", [""])[0]
        target = resolve_media(rel_path)
        if not target:
            self._html('<p>not found or not an allowed media path</p>', 404)
            return
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Accept-Ranges", "none")
        self.send_header("Cache-Control", "public, max-age=300")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    # -- LiveTalking signalling proxy -------------------------------------
    def _proxy_lt(self, path: str):
        """Forward a signalling POST to LiveTalking so the page stays single-origin."""
        allowed = {"/lt/offer": "/offer", "/lt/human": "/human",
                   "/lt/interrupt_talk": "/interrupt_talk", "/lt/is_speaking": "/is_speaking"}
        upstream = allowed.get(path)
        if not upstream:
            self._json({"error": "unsupported proxy path"}, 404)
            return
        length = int(self.headers.get("Content-Length") or 0)
        payload = self.rfile.read(length) if length else b"{}"
        req = urllib.request.Request(LIVETALKING + upstream, data=payload,
                                     headers={"Content-Type": "application/json"},
                                     method="POST")
        try:
            # /offer negotiates a session and can take a few seconds on first call.
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read()
                if upstream == "/offer":
                    _remember_session(body)
                self._send(body, resp.headers.get("Content-Type",
                                                  "application/json"), resp.status)
        except urllib.error.HTTPError as exc:
            self._send(exc.read() or b"{}", "application/json", exc.code)
        except Exception as exc:
            self._json({"error": f"LiveTalking unreachable: {type(exc).__name__}",
                        "hint": "start it with tools/livetalking/run_livetalking.ps1 <kol_id>"}, 502)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n))
        except Exception:
            return {}

    def _reply_api(self, path: str):
        import reply_queue as rq
        b = self._body()
        kol = b.get("kol_id") or "lena-chen"
        try:
            if path == "/api/reply/draft":
                msg = (b.get("message") or "").strip()
                if not msg:
                    self._json({"error": "message is required"}, 400)
                    return
                self._json(rq.create_draft(kol, msg))
            elif path == "/api/reply/decide":
                action = b.get("action") or "approve"
                sid = None
                if b.get("speak"):
                    sid = live_session()
                rec = rq.decide(kol, b.get("id", ""), action,
                                final_text=b.get("text"),
                                reviewer=b.get("reviewer", "dashboard"),
                                note=b.get("note", ""), sessionid=sid)
                if b.get("speak") and not sid:
                    rec["speak_detail"] = ("approved, but not spoken: no avatar session yet. "
                                           "Open /demo and press Connect, then approve again.")
                self._json(rec)
            else:
                self._json({"error": "unknown reply endpoint"}, 404)
        except KeyError as exc:
            self._json({"error": str(exc)}, 404)
        except Exception as exc:
            self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)

    def _studio_upload(self):
        """Accept a reference-audio upload and auto-transcribe it.

        Parsed by hand rather than with cgi/multipart libs: cgi is removed in 3.13 and this
        only ever handles one small file field, so a boundary split is enough.
        """
        import voice_studio as vsx

        ctype = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in ctype or "boundary=" not in ctype:
            self._json({"error": "expected multipart/form-data"}, 400)
            return
        boundary = ctype.split("boundary=", 1)[1].strip().strip('"').encode()
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        part = next((p for p in raw.split(b"--" + boundary)
                     if b"filename=" in p.split(b"\r\n\r\n")[0]), None)
        if not part:
            self._json({"error": "no file field found"}, 400)
            return
        head, _, rest = part.partition(b"\r\n\r\n")
        data = rest.rsplit(b"\r\n", 1)[0]
        # The quotes bound the match, so scanning the whole header block is safe — unlike
        # splitting on ";", which also swallowed the following Content-Type line (and on
        # Windows its ":" was then read as a drive separator, mangling the name).
        m = re.search(r'filename\s*=\s*"([^"]*)"', head.decode("utf-8", "replace"))
        name = Path(m.group(1)).name if m and m.group(1) else "upload.bin"
        name = re.sub(r"[^A-Za-z0-9._-]", "_", name)[:60] or "upload.bin"
        if len(data) < 2000:
            self._json({"error": "file looks empty or too short"}, 400)
            return

        vsx.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        src = vsx.UPLOAD_DIR / f"{int(time.time())}_{name}"
        src.write_bytes(data)
        # Normalise to what GPT-SoVITS wants; browsers hand over mp3/m4a/webm freely.
        sys.path.insert(0, str(REPO / "tools" / "voice_crawl"))
        import ffmpeg_util
        wav = src.with_suffix(".ref.wav")
        try:
            ffmpeg_util.to_mono_wav(src, wav, 32000, loudnorm=True)
        except Exception as exc:
            self._json({"error": f"could not decode that audio: {exc}"}, 400)
            return
        try:
            transcript, lang = vsx.transcribe(wav)
        except Exception as exc:
            transcript, lang = "", "en"
            logging_note = f" (transcription failed: {type(exc).__name__})"
        else:
            logging_note = ""
        self._json({"path": str(wav), "transcript": transcript, "language": lang,
                    "note": f"uploaded {len(data)/1024:.0f} KB{logging_note}"})

    def _studio_api(self, path: str):
        import voice_studio as vsx
        b = self._body()
        try:
            if path == "/api/studio/say":
                out = vsx.synthesize(b.get("character", "sofia-hsu"),
                                     (b.get("text") or "").strip(),
                                     speed=float(b.get("speed", 1.0)),
                                     volume_db=float(b.get("volume_db", 0.0)),
                                     lang=b.get("lang") or None)
                self._json({"url": "/media?path=" + urllib.parse.quote(rel(out)),
                            "file": rel(out)})
            elif path == "/api/studio/clone":
                out = vsx.synthesize("_clone", (b.get("text") or "").strip(),
                                     speed=float(b.get("speed", 1.0)),
                                     volume_db=float(b.get("volume_db", 0.0)),
                                     ref_audio=b.get("ref"), ref_text=b.get("ref_text", ""),
                                     ref_lang=b.get("ref_lang", "en"))
                self._json({"url": "/media?path=" + urllib.parse.quote(rel(out)),
                            "file": rel(out)})
            elif path == "/api/studio/script":
                self._json({"script": vsx.write_script(
                    b.get("character", "sofia-hsu"), (b.get("scenario") or "").strip(),
                    seconds=int(b.get("seconds", 18)))})
            elif path == "/api/studio/character":
                self._json({"character": vsx.create_character((b.get("prompt") or "").strip())})
            elif path == "/api/studio/save_character":
                p = vsx.save_character(b.get("character") or {}, b.get("id", ""))
                self._json({"path": rel(p)})
            else:
                self._json({"error": "unknown studio endpoint"}, 404)
        except FileExistsError as exc:
            self._json({"error": str(exc)}, 409)
        except Exception as exc:
            self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)

    def do_POST(self):
        path = self.path.split("?")[0].rstrip("/") or "/"
        if path.startswith("/lt/"):
            self._proxy_lt(path)
        elif path.startswith("/api/reply/"):
            self._reply_api(path)
        elif path == "/api/studio/upload":
            self._studio_upload()
        elif path.startswith("/api/studio/"):
            self._studio_api(path)
        else:
            self._json({"error": "not found"}, 404)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path.rstrip("/") or "/"
        try:
            if path == "/media":
                self._serve_media(parsed.query)
            elif path == "/api/state":
                self._json(collect())
            elif path.startswith("/api/kol/"):
                d = kol_detail(path.rsplit("/", 1)[-1])
                self._json(d or {"error": "unknown kol"}, 200 if d else 404)
            elif path.startswith("/kol/"):
                d = kol_detail(path.rsplit("/", 1)[-1])
                if d:
                    self._html(render_kol(d))
                else:
                    self._html('<p>unknown KOL — <a href="/">back to roster</a></p>', 404)
            elif path == "/replies":
                kol = urllib.parse.parse_qs(parsed.query).get("kol", ["lena-chen"])[0]
                self._html(render_replies(collect(), kol))
            elif path == "/api/reply/queue":
                import reply_queue as rq
                kol = urllib.parse.parse_qs(parsed.query).get("kol", ["lena-chen"])[0]
                self._json({"kol_id": kol, "policy_mode": rq.policy_mode(kol),
                            "stats": rq.stats(kol), "items": rq.load_all(kol)})
            elif path == "/studio":
                self._html(render_studio(collect()))
            elif path == "/demo":
                self._html(render_demo(collect()))
            elif path == "/":
                self._html(render_dashboard(collect()))
            else:
                self._html('<p>not found — <a href="/">dashboard</a></p>', 404)
        except Exception as exc:
            self._html(f"<pre>dashboard error: {esc(type(exc).__name__)}: {esc(exc)}</pre>", 500)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8770)
    args = ap.parse_args()

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    base = f"http://{args.host}:{args.port}"
    print(f"AI-KOL dashboard  ->  {base}")
    print(f"  live demo       ->  {base}/demo")
    print(f"  JSON API        ->  {base}/api/state")
    print("Ctrl+C to stop.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
