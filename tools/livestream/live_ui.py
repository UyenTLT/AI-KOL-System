#!/usr/bin/env python3
"""A live-room UI for Sofia, in the shape viewers already recognise.

The plain form page at `/` is a control surface: it exposes the register, the voice candidate,
the timings. This is the opposite — it is what a viewer sees, and nothing else. One host tile,
a wall of empty seats, a scrolling chat, and a box to type in.

It reuses the pipeline wholesale rather than reimplementing it. A comment posted here lands in
the same PENDING queue, is answered by the same worker, is rendered by the same voice, and is
served from the same /media. The only new server surface is a JSON feed, because a live room
cannot reload the page on every message the way the form page does.

Deliberately one room and one host. Multi-seat is drawn but not wired: the seats are there to
make the room read as a room, and pretending they are occupied by KOLs who have no brain
running behind them would be a demo that lies.
"""
from __future__ import annotations

LIVE_CSS = """
*{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}
body{background:#1a0b2e;color:#fff;font:15px/1.5 -apple-system,"Segoe UI",Roboto,"Noto Sans TC",sans-serif;
 min-height:100vh;overflow-x:hidden}
.room{max-width:430px;margin:0 auto;min-height:100vh;position:relative;
 background:
  radial-gradient(120% 60% at 50% 0%,#4b2a8a 0%,rgba(75,42,138,0) 60%),
  radial-gradient(90% 50% at 80% 25%,#7a2f9e 0%,rgba(122,47,158,0) 55%),
  linear-gradient(180deg,#2a1152 0%,#1a0b2e 45%,#12082a 100%);
 display:flex;flex-direction:column}
/* ---- top bar ---- */
.top{display:flex;align-items:center;gap:8px;padding:10px 12px 6px}
.host{display:flex;align-items:center;gap:8px;background:rgba(0,0,0,.32);border-radius:999px;
 padding:3px 10px 3px 3px;backdrop-filter:blur(6px)}
.host img{width:34px;height:34px;border-radius:50%;object-fit:cover;border:2px solid #ff5fa2}
.host b{font-size:13px;font-weight:600;display:block;line-height:1.15}
.host span{font-size:10.5px;color:#c9b6e8}
.follow{background:linear-gradient(90deg,#ff4f9a,#b44bff);border:0;color:#fff;font-size:11.5px;
 font-weight:700;border-radius:999px;padding:5px 12px;cursor:pointer}
.follow.done{background:rgba(255,255,255,.16);color:#d9c9f5}
.watchers{margin-left:auto;display:flex;align-items:center;gap:-6px}
.watchers i{width:26px;height:26px;border-radius:50%;display:inline-block;margin-left:-7px;
 border:1.5px solid rgba(255,255,255,.35);background:#5b3a8f;font-style:normal;font-size:11px;
 line-height:23px;text-align:center;color:#e7d9ff}
.count{background:rgba(0,0,0,.34);border-radius:999px;padding:4px 9px;font-size:11.5px;margin-left:6px}
.tabs{display:flex;gap:14px;padding:2px 14px 8px;font-size:11.5px;color:#cbb7ec}
.tabs b{color:#fff;font-weight:600;position:relative}
.tabs b:after{content:"";position:absolute;left:0;right:0;bottom:-5px;height:2px;border-radius:2px;
 background:linear-gradient(90deg,#ff4f9a,#b44bff)}
/* ---- stage ---- */
.stage{text-align:center;padding:8px 0 2px}
.orb{width:92px;height:92px;margin:0 auto;border-radius:50%;position:relative;
 background:radial-gradient(circle at 38% 32%,#8ee9ff,#3aa8ff 45%,#2b6ef0 100%);
 box-shadow:0 0 0 6px rgba(80,180,255,.16),0 0 34px rgba(80,180,255,.5);
 display:flex;align-items:center;justify-content:center;font-size:34px}
.orb.live{animation:breathe 1.6s ease-in-out infinite}
@keyframes breathe{0%,100%{box-shadow:0 0 0 6px rgba(255,80,160,.18),0 0 30px rgba(255,80,160,.45)}
 50%{box-shadow:0 0 0 14px rgba(255,80,160,.06),0 0 52px rgba(255,80,160,.75)}}
.statepill{display:inline-block;margin-top:10px;font-size:12px;font-weight:600;padding:5px 14px;
 border-radius:999px;background:rgba(255,255,255,.12);color:#e9dcff}
.statepill.live{background:linear-gradient(90deg,#ff4f9a,#b44bff)}
.dots i{display:inline-block;width:5px;height:5px;border-radius:50%;background:#fff;margin:0 1.5px;
 opacity:.35;animation:blink 1.2s infinite}
.dots i:nth-child(2){animation-delay:.2s}.dots i:nth-child(3){animation-delay:.4s}
@keyframes blink{0%,80%,100%{opacity:.3}40%{opacity:1}}
.tagline{font-size:12.5px;color:#c3adea;margin-top:7px}
/* ---- seats ---- */
.seats{display:grid;grid-template-columns:repeat(4,1fr);gap:10px 4px;padding:14px 10px 6px}
.seat{text-align:center}
.seat .pic{width:52px;height:52px;margin:0 auto;border-radius:50%;background:rgba(255,255,255,.07);
 border:1px dashed rgba(255,255,255,.22);display:flex;align-items:center;justify-content:center;
 font-size:19px;color:rgba(255,255,255,.4);overflow:hidden;position:relative}
.seat.host .pic{border:2px solid #ff5fa2;background:#3a1c6b}
.seat.host .pic img{width:100%;height:100%;object-fit:cover}
.seat.host.talking .pic{animation:ring 1.3s ease-in-out infinite}
@keyframes ring{0%,100%{box-shadow:0 0 0 0 rgba(255,95,162,.65)}70%{box-shadow:0 0 0 11px rgba(255,95,162,0)}}

/* ---- speaking: driven by the waveform, not by a timer ----
   --lvl is written from the analyser every frame, 0..1. Everything below reads it, so the
   glow, the scale and the bars all move with the same signal the viewer is hearing rather
   than to a loop that happens to look busy. */
.seat.host{--lvl:0}
.seat.host.speaking .pic{
 animation:none;
 transform:scale(calc(1 + var(--lvl) * .13));
 box-shadow:0 0 calc(10px + var(--lvl) * 34px) rgba(255,95,162,calc(.35 + var(--lvl) * .5)),
            0 0 0 calc(2px + var(--lvl) * 5px) rgba(255,95,162,calc(.18 + var(--lvl) * .35));
 transition:transform .06s linear,box-shadow .06s linear}
/* Two rings that ride out and fade, sized by level. Pure decoration, but sized by real audio
   so they stop dead when she stops rather than finishing a cycle after the sound ends. */
.seat.host.speaking .pic:before,.seat.host.speaking .pic:after{
 content:"";position:absolute;inset:-4px;border-radius:50%;pointer-events:none;
 border:1.5px solid rgba(255,120,180,calc(var(--lvl) * .75));
 transform:scale(calc(1 + var(--lvl) * .55));transition:transform .09s ease-out}
.seat.host.speaking .pic:after{
 inset:-9px;border-color:rgba(150,110,255,calc(var(--lvl) * .5));
 transform:scale(calc(1 + var(--lvl) * .85))}
/* A small equaliser under the host tile. Five bars, five frequency buckets. */
.eq{height:14px;display:flex;align-items:flex-end;justify-content:center;gap:2px;margin-top:3px;
 opacity:0;transition:opacity .2s}
.seat.host.speaking .eq{opacity:1}
.eq b{width:3px;border-radius:2px;background:linear-gradient(180deg,#ff8fc0,#b44bff);
 height:calc(2px + var(--b) * 12px);transition:height .07s linear}
/* The orb keeps the slow breathe while THINKING and switches to the level while SPEAKING. */
.orb.speaking{animation:none;
 transform:scale(calc(1 + var(--olvl,0) * .09));
 box-shadow:0 0 calc(20px + var(--olvl,0) * 46px) rgba(255,80,160,calc(.4 + var(--olvl,0) * .5));
 transition:transform .06s linear,box-shadow .06s linear}
.seat em{display:block;font-style:normal;font-size:10.5px;color:#bda8e2;margin-top:5px;
 white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.seat .no{position:absolute;left:3px;top:3px;font-size:9px;background:rgba(0,0,0,.45);
 border-radius:4px;padding:0 3px;color:#e2d3ff}
/* ---- chat ---- */
.chat{flex:1;overflow-y:auto;padding:6px 12px 4px;display:flex;flex-direction:column;gap:7px;
 min-height:150px;max-height:38vh}
.msg{font-size:13px;line-height:1.45;max-width:88%}
.msg .nm{color:#ffcf5a;font-weight:600}
.msg.sys{color:#c0a9e6;font-size:11.5px}
.msg.her{background:rgba(255,255,255,.09);border-radius:12px;padding:7px 11px;align-self:flex-start;
 border-left:2px solid #ff5fa2}
.msg.her .nm{color:#ff8fc0}
.msg.me .nm{color:#8fe3ff}
/* ---- bottom ---- */
.bar{display:flex;align-items:center;gap:8px;padding:9px 11px 13px;
 background:linear-gradient(180deg,rgba(0,0,0,0),rgba(0,0,0,.4) 40%)}
.bar input{flex:1;background:rgba(255,255,255,.12);border:0;border-radius:999px;padding:10px 15px;
 color:#fff;font-size:14px;outline:none}
.bar input::placeholder{color:#b7a2dc}
.bar button{border:0;border-radius:999px;padding:10px 15px;font-size:14px;cursor:pointer;
 background:linear-gradient(90deg,#ff4f9a,#b44bff);color:#fff;font-weight:700}
.bar .ic{background:rgba(255,255,255,.12);padding:9px 11px;font-size:16px}
.err{background:#5b1730;color:#ffd7e2;font-size:12px;padding:7px 12px;text-align:center}
"""

LIVE_JS = """
var feedSeen = 0, lastStem = '', player = new Audio();
// Comments already painted locally, so the feed does not print them twice.
var mine = {};
player.autoplay = true;

function esc(s){ var d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

function add(kind, name, text){
  var c = document.getElementById('chat');
  var d = document.createElement('div');
  d.className = 'msg ' + kind;
  d.innerHTML = (name ? '<span class="nm">' + esc(name) + '</span> ' : '') + esc(text);
  c.appendChild(d);
  c.scrollTop = c.scrollHeight;
}

// ---- the speaking effect ----
//
// Two different states that were previously one. `answering` comes from the server and is true
// while the reply is being WRITTEN and RENDERED; it goes false the moment the clip exists --
// which is precisely when she starts talking. Driving the avatar from it meant the animation
// stopped at the instant the voice began, which is backwards.
//
// So: thinking is the server's flag, speaking is the audio element's own state, and the
// intensity comes from the waveform through an AnalyserNode. A fixed CSS pulse was the easy
// version and it is worse in a specific way -- it keeps bouncing through her pauses, so the
// avatar looks like it is animating AT the audio instead of WITH it.
var actx = null, analyser = null, freqs = null, rafId = 0;

function initAnalyser(){
  if(actx) return true;
  try {
    var AC = window.AudioContext || window.webkitAudioContext;
    if(!AC) return false;
    actx = new AC();
    // createMediaElementSource can only ever be called ONCE for a given element; calling it
    // again throws and silently kills playback. `player` is reused for every clip, so this
    // runs once and the node stays connected for the life of the page.
    var src = actx.createMediaElementSource(player);
    analyser = actx.createAnalyser();
    analyser.fftSize = 128;
    analyser.smoothingTimeConstant = 0.72;   // enough to stop it juddering on consonants
    freqs = new Uint8Array(analyser.frequencyBinCount);
    src.connect(analyser);
    analyser.connect(actx.destination);      // still has to reach the speakers
    return true;
  } catch(e){ actx = null; return false; }
}

var BARS = null;
function meter(){
  var seat = document.getElementById('seat0'), orb = document.getElementById('orb');
  if(analyser){
    analyser.getByteFrequencyData(freqs);
    var n = freqs.length, sum = 0;
    for(var i = 0; i < n; i++) sum += freqs[i];
    // Speech sits low in the spectrum, so a flat mean under-reads badly. Weighting the
    // bottom third is what makes the glow track her voice rather than the room tone.
    var lo = 0, cut = Math.max(1, Math.floor(n / 3));
    for(var j = 0; j < cut; j++) lo += freqs[j];
    var lvl = Math.min(1, ((sum / n) * 0.4 + (lo / cut) * 0.6) / 110);
    seat.style.setProperty('--lvl', lvl.toFixed(3));
    orb.style.setProperty('--olvl', lvl.toFixed(3));
    if(BARS){
      for(var b = 0; b < BARS.length; b++){
        var idx = Math.floor((b + 0.5) * (cut / BARS.length));
        BARS[b].style.setProperty('--b', (freqs[idx] / 255).toFixed(3));
      }
    }
  }
  rafId = requestAnimationFrame(meter);
}

function speaking(on){
  var seat = document.getElementById('seat0'), orb = document.getElementById('orb');
  seat.classList.toggle('speaking', on);
  orb.classList.toggle('speaking', on);
  if(on){
    if(!rafId) meter();
  } else {
    if(rafId){ cancelAnimationFrame(rafId); rafId = 0; }
    // Settle to rest rather than freezing on whatever the last frame happened to be.
    seat.style.setProperty('--lvl', 0);
    orb.style.setProperty('--olvl', 0);
    if(BARS) for(var b = 0; b < BARS.length; b++) BARS[b].style.setProperty('--b', 0);
  }
}

// One <audio>, reused. A new answer replaces whatever is playing rather than queueing behind
// it -- the same rule as the form page: interrupting is one voice stopping and another
// starting, which is what a live room does when the next question arrives.
function play(clip){
  try { player.pause(); } catch(e){}
  initAnalyser();
  // Browsers start an AudioContext suspended until a gesture. Without this the analyser
  // returns silence and the avatar sits still through an answer that is audibly playing.
  if(actx && actx.state === 'suspended') actx.resume().catch(function(){});
  player.src = '/media/' + clip;
  var q = player.play();
  if(q && q.catch) q.catch(function(){});   // autoplay may need a gesture first
}

function talking(on){
  // THINKING only. The pulse ring and the pill; the waveform effect is separate and is driven
  // by the audio element below.
  document.getElementById('seat0').classList.toggle('talking', on);
  document.getElementById('orb').classList.toggle('live', on);
  var pill = document.getElementById('pill');
  pill.classList.toggle('live', on);
  if(!player.paused && !player.ended && player.src){
    pill.innerHTML = 'Sofia 正在說話 <span class="dots"><i></i><i></i><i></i></span>';
    return;
  }
  pill.innerHTML = on
    ? 'Sofia 正在回覆 <span class="dots"><i></i><i></i><i></i></span>'
    : '點擊下方輸入框，跟 Sofia 說話';
}

function pump(){
  fetch('/feed?since=' + feedSeen).then(function(r){ return r.json(); }).then(function(s){
    talking(!!s.answering);
    (s.events || []).forEach(function(e){
      feedSeen = e.i + 1;
      // The comment was already put on screen the moment it was sent. Without this check the
      // feed would print it a second time when the answer finally lands.
      if(e.fan_text){
        var key = (e.who || 'guest') + '|' + e.fan_text;
        if(mine[key]) { delete mine[key]; }
        else { add('', e.who || 'guest', e.fan_text); }
      }
      // Her answer leaves NOTHING in the feed. No transcript, no bubble, no label -- she is
      // heard and not read, which is the whole point of a live room.
      //
      // The usual objection to this is autoplay: browsers refuse to start audio until the
      // page has had a gesture, and with no bubble there would be nothing to press. It does
      // not apply here, because of the order things happen in. She only ever speaks in answer
      // to a comment, so the viewer has always clicked 送出 before the first clip exists, and
      // that click is the gesture. `send()` resumes the AudioContext explicitly so the unlock
      // is deliberate rather than incidental.
      if(e.clip && e.stem !== lastStem){ lastStem = e.stem; play(e.clip); }
    });
  }).catch(function(){});
}

function send(){
  var box = document.getElementById('say');
  var t = (box.value || '').trim();
  if(!t) return;
  var who = document.getElementById('who').value.trim() || 'guest';
  box.value = '';
  // Show it NOW. The event only reaches /feed once the whole answer has been written and
  // rendered, which is ten to forty seconds -- so until this, pressing send did nothing
  // visible and the room looked broken. The comment is the viewer's own text; there is
  // nothing to wait for a server round trip to confirm.
  add('me', who, t);
  mine[who + '|' + t] = true;
  // This click is the browser's gesture requirement satisfied. Doing the unlock here, on the
  // action that always precedes her first clip, is what lets the answer play with nothing in
  // the feed to press.
  initAnalyser();
  if(actx && actx.state === 'suspended') actx.resume().catch(function(){});
  // Stop her mid-answer the moment a new question is asked. Asking IS the interruption.
  try { player.pause(); } catch(e){}
  fetch('/say', {method:'POST', headers:{'Content-Type':'application/x-www-form-urlencoded'},
                 body:'who=' + encodeURIComponent(who) + '&text=' + encodeURIComponent(t)})
    .then(function(){ talking(true); }).catch(function(){});
}

document.addEventListener('DOMContentLoaded', function(){
  BARS = document.querySelectorAll('#eq b');
  // The audio element is the source of truth for "is she talking", not the server flag.
  player.addEventListener('playing', function(){ speaking(true);  talking(false); });
  player.addEventListener('pause',   function(){ speaking(false); talking(false); });
  player.addEventListener('ended',   function(){ speaking(false); talking(false); });
  player.addEventListener('emptied', function(){ speaking(false); });
  document.getElementById('sendbtn').addEventListener('click', send);
  document.getElementById('say').addEventListener('keydown', function(e){
    if(e.key === 'Enter') send();
  });
  document.getElementById('followbtn').addEventListener('click', function(){
    this.textContent = '已關注'; this.classList.add('done');
  });
  add('sys', '', '歡迎來到 Sofia 的房間 — 打字跟她說話，她會唸出來回你');
  setInterval(pump, 500);
  pump();
});
"""


def live_page(kol_name: str = "Sofia Hsu", handle: str = "@sofiahsu",
              # 256px square, ~100 KB. The full render is 8.5 MB for a 34-pixel circle, which
              # every viewer would download on every page load.
              avatar: str = "/img/avatar_256.png", seats: int = 8) -> bytes:
    """The viewer's page. Everything dynamic arrives from /feed, so this is served once."""
    tiles = [f'<div class="seat host" id="seat0"><div class="pic">'
             f'<span class="no">1</span><img src="{avatar}" alt=""></div>'
             f'<div class="eq" id="eq"><b></b><b></b><b></b><b></b><b></b></div>'
             f'<em>{kol_name}</em></div>']
    for n in range(2, seats + 1):
        tiles.append(f'<div class="seat"><div class="pic"><span class="no">{n}</span>+</div>'
                     f'<em>虛位以待</em></div>')
    html = f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<title>{kol_name} — LIVE</title><style>{LIVE_CSS}</style></head><body>
<div class="room">
  <div class="top">
    <div class="host">
      <img src="{avatar}" alt="">
      <div><b>{kol_name}</b><span>{handle} · 1.2萬 粉絲</span></div>
      <button class="follow" id="followbtn">+ 關注</button>
    </div>
    <div class="watchers"><i>A</i><i>M</i><i>K</i></div>
    <div class="count">🔴 LIVE</div>
  </div>
  <div class="tabs"><b>聊天室</b><span>排行榜</span><span>玩法介紹</span><span>公告</span></div>

  <div class="stage">
    <div class="orb live" id="orb">🎤</div>
    <div class="statepill live" id="pill">Sofia 正在回覆 <span class="dots"><i></i><i></i><i></i></span></div>
    <div class="tagline">半個詞彙量，兩倍的意見</div>
  </div>

  <div class="seats">{''.join(tiles)}</div>
  <div class="chat" id="chat"></div>

  <div class="bar">
    <input id="who" value="guest" style="flex:0 0 74px;text-align:center" aria-label="your name">
    <input id="say" placeholder="說點什麼…" aria-label="comment">
    <button class="ic" title="gift">🎁</button>
    <button id="sendbtn">送出</button>
  </div>
</div>
<script>{LIVE_JS}</script></body></html>"""
    return html.encode("utf-8")
