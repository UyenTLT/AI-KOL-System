#!/usr/bin/env python3
"""
Talking-KOL web app (echo-mode MVP) -- type text, a KOL "speaks" it.
Local browser UI inspired by livetalking.top. 100% local:
  text -> TTS (macOS `say`) -> portrait + caption + Ken Burns (Pillow+ffmpeg) -> clip in browser.

Lip-sync (real mouth movement) + realtime streaming is the next step -> Wav2Lip / LiveTalking
on an NVIDIA/CUDA machine (see research/local-ai-companion/04,05,08). The generate() backend
here is written to be swappable for that.

Run (needs Pillow + ffmpeg):   ./sd-venv/bin/python tools/talking_web/server.py
Then open:                      http://localhost:7860
Self-test one clip:            ./sd-venv/bin/python tools/talking_web/server.py --selftest
"""
import os, sys, json, re, glob, tempfile, subprocess, hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
FONT = "/System/Library/Fonts/PingFang.ttc"
OUTDIR = os.path.join(os.path.dirname(__file__), "_out")
os.makedirs(OUTDIR, exist_ok=True)
W, H, FPS = 1080, 1920, 30
_EMOJI = re.compile("[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0000FE0F]")

def sh(a): return subprocess.run(a, capture_output=True, text=True)

def kols():
    idx = json.load(open(f"{ROOT}/kols/index.json"))
    out = []
    for k in idx["kols"]:
        imgs = [i for i in sorted(glob.glob(f"{ROOT}/kols/{k['id']}/images/soul_v1_training/*.png"))
                if os.path.getsize(i) > 20000]
        if imgs:
            out.append({"id": k["id"], "name": k["name"], "img": imgs[0]})
    return out

def voice_for(kol_id):
    prof = json.load(open(f"{ROOT}/kols/{kol_id}/profile.json"))
    langs = " ".join(prof["identity"].get("languages", []))
    return "Meijia" if ("Mandarin" in langs or "Chinese" in langs) else "Samantha"

def audio_dur(p):
    r = sh(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", p])
    try: return float(r.stdout.strip())
    except Exception: return 3.0

def caption_png(text, path):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT, 54)
    lines = [text[i:i+15] for i in range(0, len(text), 15)] or [" "]
    lh = 72; tw = max(d.textlength(l, font=font) for l in lines); th = lh * len(lines); pad = 32
    bw, bh = tw + pad * 2, th + pad * 2; x0, y0 = (W - bw) // 2, H - bh - 230
    d.rounded_rectangle([x0, y0, x0 + bw, y0 + bh], radius=28, fill=(0, 0, 0, 150))
    y = y0 + pad
    for l in lines:
        d.text(((W - d.textlength(l, font=font)) // 2, y), l, font=font, fill=(255, 255, 255, 255)); y += lh
    img.save(path)

def generate(kol_id, text):
    """echo-mode backend. Swap this for Wav2Lip/LiveTalking for real lip-sync."""
    text = _EMOJI.sub("", text).strip() or "。"
    ks = {k["id"]: k for k in kols()}
    if kol_id not in ks:
        raise ValueError("unknown kol")
    img = ks[kol_id]["img"]; voice = voice_for(kol_id)
    key = hashlib.md5((kol_id + text).encode()).hexdigest()[:10]
    tmp = tempfile.mkdtemp(); wav = f"{tmp}/a.wav"; cap = f"{tmp}/c.png"
    out = f"{OUTDIR}/{kol_id}_{key}.mp4"
    sh(["say", "-v", voice, "--file-format=WAVE", "--data-format=LEI16@22050", "-o", wav, text])
    dur = max(2.5, audio_dur(wav) + 0.5)
    caption_png(text, cap)
    fc = (f"[0:v]scale={int(W*1.25)}:{int(H*1.25)}:force_original_aspect_ratio=increase,"
          f"crop={int(W*1.25)}:{int(H*1.25)},"
          f"zoompan=z='min(1+0.0008*on,1.12)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={W}x{H}:fps={FPS}[bg];"
          f"[bg][2:v]overlay=0:0[v]")
    sh(["ffmpeg", "-y", "-loop", "1", "-i", img, "-i", wav, "-loop", "1", "-i", cap,
        "-filter_complex", fc, "-map", "[v]", "-map", "1:a", "-t", f"{dur:.2f}", "-r", str(FPS),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", out])
    return os.path.basename(out) if os.path.exists(out) else None

PAGE = """<!doctype html><meta charset=utf-8><title>Talking KOL</title>
<style>
:root{color-scheme:dark}body{margin:0;font-family:system-ui,'PingFang TC';background:#0f0d13;color:#f2ecef;
display:flex;flex-direction:column;align-items:center;padding:28px 16px}
h1{font-size:20px;margin:0 0 4px}.sub{color:#9a8fa0;font-size:13px;margin-bottom:20px}
.card{background:#1b171f;border:1px solid #2f2730;border-radius:16px;padding:18px;width:min(460px,100%)}
select,textarea{width:100%;box-sizing:border-box;background:#0f0d13;color:#f2ecef;border:1px solid #3a3040;
border-radius:10px;padding:11px;font-size:15px;font-family:inherit}textarea{height:88px;resize:vertical;margin-top:10px}
button{width:100%;margin-top:12px;background:#d6437b;color:#fff;border:0;border-radius:10px;padding:13px;
font-size:15px;font-weight:600;cursor:pointer}button:disabled{opacity:.5}
video{width:min(320px,100%);margin-top:18px;border-radius:14px;display:none}
.hint{color:#7c7280;font-size:12px;margin-top:14px;text-align:center;line-height:1.5}
</style>
<h1>🗣️ Talking KOL <span style=color:#d6437b>· echo mode</span></h1>
<div class=sub>Gõ chữ → nhân vật đọc. (Lip-sync realtime = bước sau, cần GPU/LiveTalking)</div>
<div class=card>
<select id=kol></select>
<textarea id=txt placeholder="Nhập câu cho nhân vật nói...">大家好，今天想跟你們分享一個好東西。</textarea>
<button id=go onclick=speak()>▶ Nói</button>
<video id=vid controls playsinline></video>
<div id=tip style="display:none;color:#f0b6cf;font-size:12px;margin-top:8px;text-align:center">🔊 Nếu chưa nghe thấy tiếng, bấm ▶ trên video (trình duyệt chặn tự phát có tiếng).</div>
</div>
<div class=hint>echo mode: gõ → gửi → nhân vật đọc xong.<br>Nâng cấp: Wav2Lip/LiveTalking cho miệng nhép + livestream.</div>
<script>
fetch('/kols').then(r=>r.json()).then(ks=>{el=document.getElementById('kol');
ks.forEach(k=>{o=document.createElement('option');o.value=k.id;o.textContent=k.name;el.appendChild(o)})});
function speak(){const b=document.getElementById('go');b.disabled=true;b.textContent='⏳ đang tạo...';
fetch('/speak',{method:'POST',headers:{'Content-Type':'application/json'},
body:JSON.stringify({kol:document.getElementById('kol').value,text:document.getElementById('txt').value})})
.then(r=>r.json()).then(d=>{b.disabled=false;b.textContent='▶ Nói';
if(d.file){v=document.getElementById('vid');v.muted=false;v.src='/out/'+d.file+'?t='+Date.now();
v.style.display='block';v.load();v.muted=false;v.play().catch(()=>{});document.getElementById('tip').style.display='block'}
else alert('Lỗi tạo video: '+(d.error||''))}).catch(e=>{b.disabled=false;b.textContent='▶ Nói';alert(e)})}
</script>"""

class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        self.send_response(code); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def log_message(self, *a): pass
    def do_GET(self):
        p = urlparse(self.path).path
        if p == "/":
            self._send(200, PAGE.encode(), "text/html; charset=utf-8")
        elif p == "/kols":
            self._send(200, json.dumps([{"id": k["id"], "name": k["name"]} for k in kols()]).encode())
        elif p.startswith("/out/"):
            f = os.path.join(OUTDIR, os.path.basename(p))
            if os.path.exists(f):
                self._send(200, open(f, "rb").read(), "video/mp4")
            else:
                self._send(404, b"not found", "text/plain")
        else:
            self._send(404, b"not found", "text/plain")
    def do_POST(self):
        if urlparse(self.path).path == "/speak":
            n = int(self.headers.get("Content-Length", 0))
            d = json.loads(self.rfile.read(n) or b"{}")
            try:
                f = generate(d.get("kol", ""), d.get("text", ""))
                self._send(200, json.dumps({"file": f}).encode())
            except Exception as e:
                self._send(200, json.dumps({"error": str(e)}).encode())
        else:
            self._send(404, b"not found", "text/plain")

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        ks = kols(); print("KOLs:", [k["id"] for k in ks])
        f = generate(ks[0]["id"], "大家好，這是一個測試。Hi everyone!")
        print("selftest clip:", f, "->", os.path.join(OUTDIR, f) if f else "FAILED")
    else:
        print("Talking KOL web -> http://localhost:7860  (Ctrl+C to stop)")
        ThreadingHTTPServer(("127.0.0.1", 7860), Handler).serve_forever()
