#!/usr/bin/env python3
"""
KOL Vlog App (MVP) -- turn a KOL's photos into a vertical 9:16 TikTok/Reels vlog.

Pipeline (100% local, free):
  ① LLM script (Ollama qwen2.5) -> ② voiceover (macOS `say`)
  -> ③ Ken Burns + caption (Pillow + ffmpeg) -> ④ concat -> kols/<id>/videos/vlog_mvp.mp4

Requirements: ffmpeg, Pillow (pip install pillow), Ollama running with a model pulled
              (`ollama pull qwen2.5:7b`), macOS `say` (built-in).

Usage:  python3 tools/vlog_app.py <kol_id> ["topic"]
Example: python3 tools/vlog_app.py lin-wanqing "雨天的慢生活"
"""
import sys, os, json, re, subprocess, glob, tempfile, urllib.request
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
FONT = "/System/Library/Fonts/PingFang.ttc"   # macOS CJK font
MODEL = "qwen2.5:7b"
W, H, FPS = 1080, 1920, 30

_EMOJI = re.compile("[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0000FE0F\U00002190-\U000021FF\U00002B00-\U00002BFF]")

def sh(args):
    return subprocess.run(args, capture_output=True, text=True)

def ollama(system, user, temp=0.7, as_json=False):
    body = {"model": MODEL, "stream": False,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "options": {"temperature": temp}}
    if as_json:
        body["format"] = "json"
    req = urllib.request.Request("http://localhost:11434/api/chat",
        data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=180).read())["message"]["content"].strip()

def strip_emoji(s):
    return _EMOJI.sub("", s).strip()

def audio_dur(path):
    r = sh(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path])
    try:
        return float(r.stdout.strip())
    except Exception:
        return 3.0

def make_caption_png(text, path):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT, 58)
    lines = [text[i:i+14] for i in range(0, len(text), 14)] or [" "]
    line_h = 76
    tw = max(d.textlength(l, font=font) for l in lines)
    th = line_h * len(lines)
    pad = 34
    bw, bh = tw + pad * 2, th + pad * 2
    x0, y0 = (W - bw) // 2, H - bh - 250
    d.rounded_rectangle([x0, y0, x0 + bw, y0 + bh], radius=30, fill=(0, 0, 0, 150))
    y = y0 + pad
    for l in lines:
        w = d.textlength(l, font=font)
        d.text(((W - w) // 2, y), l, font=font, fill=(255, 255, 255, 255))
        y += line_h
    img.save(path)

def make_script(prof, topic, n):
    p = prof["persona"]; ident = prof["identity"]
    sys_p = f"你是{ident['name']}（{ident.get('name_zh','')}）。語氣：{p['voice_tone']}。只用繁體中文，不要夾雜英文。"
    usr = (f"為一支 TikTok 慢生活/日常 vlog 寫 {n} 句旁白，主題：{topic or '今天的日常'}。"
           f"每句是一個鏡頭的字幕，口語、溫柔、短（每句 8-16 字），像日記。"
           '只回 JSON: {"title":"標題(≤12字)","lines":["句1","句2"]}，共 ' + str(n) + " 句。")
    try:
        d = json.loads(ollama(sys_p, usr, as_json=True))
        lines = [strip_emoji(x) for x in d.get("lines", [])][:n]
        title = strip_emoji(d.get("title", "")) or "我的一天"
    except Exception:
        title, lines = "我的一天", ["今天也想好好過。"] * n
    while len(lines) < n:
        lines.append("慢慢來，沒關係。")
    return title, lines

def make_shot(img, text, out, voice, tmp, i):
    wav = f"{tmp}/a{i}.wav"
    sh(["say", "-v", voice, "--file-format=WAVE", "--data-format=LEI16@22050", "-o", wav, text or "。"])
    dur = max(2.8, audio_dur(wav) + 0.6)
    cap = f"{tmp}/c{i}.png"
    make_caption_png(text, cap)
    zoom = "min(1+0.0009*on,1.14)"
    fc = (f"[0:v]scale={int(W*1.25)}:{int(H*1.25)}:force_original_aspect_ratio=increase,"
          f"crop={int(W*1.25)}:{int(H*1.25)},"
          f"zoompan=z='{zoom}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={W}x{H}:fps={FPS}[bg];"
          f"[bg][2:v]overlay=0:0[v]")
    r = sh(["ffmpeg", "-y", "-loop", "1", "-i", img, "-i", wav, "-loop", "1", "-i", cap,
            "-filter_complex", fc, "-map", "[v]", "-map", "1:a", "-t", f"{dur:.2f}", "-r", str(FPS),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-shortest", out])
    if not os.path.exists(out):
        print("   ffmpeg err:", r.stderr[-300:])
    return out

def main():
    kol = sys.argv[1] if len(sys.argv) > 1 else "lin-wanqing"
    topic = sys.argv[2] if len(sys.argv) > 2 else ""
    prof = json.load(open(f"{ROOT}/kols/{kol}/profile.json"))
    langs = " ".join(prof["identity"].get("languages", []))
    voice = "Meijia" if ("Mandarin" in langs or "Chinese" in langs) else "Samantha"
    imgs = [i for i in sorted(glob.glob(f"{ROOT}/kols/{kol}/images/soul_v1_training/*.png"))
            if os.path.getsize(i) > 20000]
    if not imgs:
        print(f"Không có ảnh trong kols/{kol}/images/soul_v1_training/"); return
    n = min(len(imgs), 6); imgs = imgs[:n]
    print(f"🎬 {prof['identity']['name']} | {n} ảnh | giọng {voice}")
    title, lines = make_script(prof, topic, n)
    print(f"   Tiêu đề: {title}")
    for i, l in enumerate(lines):
        print(f"   [{i+1}] {l}")
    tmp = tempfile.mkdtemp()
    shots = []
    for i, (img, line) in enumerate(zip(imgs, lines)):
        print(f"   → shot {i+1}/{n} ...", flush=True)
        s = make_shot(img, line, f"{tmp}/shot{i:02d}.mp4", voice, tmp, i)
        if os.path.exists(s):
            shots.append(s)
    outdir = f"{ROOT}/kols/{kol}/videos"; os.makedirs(outdir, exist_ok=True)
    listf = f"{tmp}/list.txt"
    open(listf, "w").write("\n".join(f"file '{s}'" for s in shots))
    out = f"{outdir}/vlog_mvp.mp4"
    sh(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", listf,
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", out])
    sz = os.path.getsize(out) // 1024 if os.path.exists(out) else 0
    r = sh(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", out])
    print(f"\n✅ Xong: {out}  ({sz} KB, {r.stdout.strip()}s, {len(shots)}/{n} shots)")

if __name__ == "__main__":
    main()
