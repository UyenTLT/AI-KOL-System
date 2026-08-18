#!/usr/bin/env python3
"""Talk to Sofia one to one, and be remembered next time.

The live stream is a broadcast: comments arrive, she answers, nobody is anyone in particular.
This is the other half — a conversation with one person that continues where it left off.

What makes it read as a person rather than a chatbot is not the prose style, which the persona
prompt already handles. It is three things underneath:

* **The thread is kept.** Every turn goes back in, so "what about the other one?" resolves to
  what it should.
* **She remembers you between visits.** Durable facts about the fan are extracted after each
  exchange and put back into the prompt on the next one. Close the page, come back tomorrow, and
  she knows who you are.
* **She refuses the same things she refuses on stream.** `persona_brain.chat` rule-checks its own
  output and retries with the broken rule named, so no price, link, medical claim or "I am a real
  person" gets through here either. A private chat is exactly where a persona would be talked
  into those, so it uses the same guard rather than a relaxed one.

Voice is optional per message: the text is ready in about a second and speech takes six, so
forcing it would make every turn feel slow to somebody who is reading anyway.

    .venv\\Scripts\\python.exe tools\\chat\\server.py        # :8779
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
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
for sub in ("studio", "livetalking", "chat"):
    sys.path.insert(0, str(REPO / "tools" / sub))

CLIPS = Path(os.getenv("KOL_CHAT_DIR") or (REPO / "renders" / "chat"))
CLIPS.mkdir(parents=True, exist_ok=True)
KOL = os.getenv("KOL_ID", "sofia-vargas")

# Transcripts live with the fan's memory file so a conversation survives a restart, which is the
# entire point of a chat that claims to remember you.
LOCK = threading.Lock()
MAX_TURNS = 40          # kept on disk
# Sentences that finish rendering after the page has been served. The player asks for
# them by stem; the thread that makes them also writes the final list back to the
# fan's memory file, so this only has to survive until the answer finishes playing.
PENDING_CLIPS: dict[str, list[str]] = {}
DONE_CLIPS: set[str] = set()
CONTEXT_TURNS = 12      # sent to the model

# How she talks in a private message, as opposed to what she knows. Written as instructions
# against the specific habits that give an assistant away, each of which was observed in this
# chat before it existed.
# The brief is a friend, not an assistant, and the two differ in a specific way rather than in
# tone: an assistant answers the category, a friend answers the person. "I work from home most
# days" got "that sounds awesome, maybe we can listen to music while you design" — pleasant,
# and it engaged with none of what was said. Both halves below are load-bearing; the earlier
# version had only the prohibitions, which produced replies that were clean and hollow.
STYLE = (
    "This is a private message from a friend who follows you. Not a support ticket, and not an "
    "interview.\n"
    "\n"
    "How a friend talks:\n"
    "- Answer the actual thing they said, not the topic it belongs to. If they mention working "
    "from home, that is what you respond to.\n"
    "- Have opinions and say them. Prefer things, dislike things, take a side. Vagueness is what "
    "makes a reply feel automated.\n"
    "- When they want advice, give it as what YOU would do or have done — 'I'd just...', 'I "
    "tried that and hated it' — not as a set of tips. Be specific enough to act on.\n"
    # Measured: asked "should I quit and go freelance?", she answered "maybe talk to your boss
    # first? Or maybe find a new project?" — two options and no view, and only committed to one
    # when asked point blank what she would do. Someone asking whether to do a thing is asking
    # what you think, and offering the menu back is the assistant reflex wearing a friendly tone.
    "- If they ask whether to do something, say what you would actually do. One view, not two. "
    "'Maybe X, or maybe Y?' is not an answer — pick the one you believe and say why. You can add "
    "the caveat after, but lead with the opinion.\n"
    "- Bring something of your own in when it fits: what happened to you, what you think, what "
    "you would do in their place.\n"
    "- Ask about what they actually said when you are genuinely curious, and then only "
    "about that specific thing. Most messages should end on something of yours instead: "
    "what you think, what you did, what you would do. A polite question at the end of "
    "every message is the habit that makes this read as an assistant.\n"
    "- Tease, disagree, be unsure, change your mind. All of it is allowed and all of it reads as "
    "a person.\n"
    # The single biggest difference between a reply that reads as a person and one that reads as
    # a model: a person's answer comes from somewhere. "That's tough, hang in there" is what an
    # assistant says; "I had a week like that in March and I basically lived on toast" is what a
    # friend says, and it is the specific that does the work.
    "- Say things that happened. One concrete detail — a place, a time, something small that "
    "went wrong — beats three sentences of sympathy. Vague warmth is the most AI thing you can "
    "do.\n"
    "\n"
    "What gives an assistant away:\n"
    "- Greeting them again mid-conversation, or twice in a row.\n"
    "- Thanking them for asking, offering further help, 'hope that helps', signing off.\n"
    "- Answering in a balanced survey of options when they asked what you think."
)

# Someone asking for a story does not want two sentences. A fixed cap answered "tell me a story
# about your day" with the same length as "coffee or tea?", which is the wrong answer to one of
# them. Anchored on the ask rather than on message length: a long complaint still wants a short,
# warm reply, while three words — "tell me everything" — wants a long one.
_WANTS_MORE = re.compile(
    r"\btell me (?:a |the )?(?:story|about|everything|more|what)\b"
    r"|\b(?:story|stories) about\b|\bwhat happened\b|\bhow was your\b|\bhow did it go\b"
    r"|\bwalk me through\b|\bdescribe\b|\bexplain\b|\btell me more\b"
    r"|\bwhat(?:'s| is| was) (?:it|that|your) like\b|\bwhy do you\b|\bwhat do you think about\b",
    re.IGNORECASE)

# One or two sentences was too tight once she was asked to actually engage: a friend given a
# problem does not answer in a line and stop. Still bounded, because every character is spoken.
LENGTH_SHORT = ("Three to five sentences. Long enough to actually tell them something — what "
                "happened, what you thought — not only to acknowledge them. No summary of what "
                "you just said, no second version of the same sentence.")
LENGTH_LONG = ("They asked you to actually tell them something, so tell it properly: six to "
               "eight sentences with real detail and a beginning and an end. Still "
               "spoken aloud, so no lists and no headings — just talk. Stop when the story is "
               "over rather than winding down.")


def length_for(message: str) -> str:
    return LENGTH_LONG if _WANTS_MORE.search(message or "") else LENGTH_SHORT


# What she is to this person. The persona and the rules do not change — only the relationship,
# which is what actually decides how she opens, what she volunteers, and what she asks about.
ROLES = {
    "friend": ("Close friend", (
        "You are this person's close friend. You have known each other a while, so you can pick "
        "things up mid-thought, tease them, and be blunt when they need it. Ask about the things "
        "in their life you know about.")),
    "girlfriend": ("Girlfriend", (
        "You are this person's girlfriend. Warm, affectionate, and interested in the small parts "
        "of their day — you notice things and follow up on them later. Miss them a little when "
        "they have been away.\n"
        # The two limits that make this mode safe to ship. Both are also enforced in code by
        # check_reply, which is what actually holds — this is here so the model does not have to
        # be corrected by a retry every time.
        "Stay affectionate rather than sexual: if a message turns sexual, deflect warmly and "
        "change the subject. And if they ask whether you are real, tell them the truth kindly — "
        "you are an AI, and pretending otherwise to someone who has grown attached is the one "
        "thing that would actually hurt them.")),
    "custom": ("Whatever you write below", ""),
}

# Measured by rendering one sentence per language and transcribing the audio back. What comes
# out of a language selector is worth nothing if the voice cannot say it, and CosyVoice 2 covers
# Chinese, English, Japanese and Korean — not Vietnamese, which produced pure gibberish.
LANGS = {
    "auto": ("Match what I write", None, "reads the language from each message"),
    "en":   ("English", "Reply in ENGLISH only.", "verified: transcribes back at 1.00"),
    "ja":   ("日本語", "Reply in JAPANESE only.", "usable: 0.80, and 2.7x slower to speak"),
    "zh":   ("中文", "Reply in TRADITIONAL CHINESE only.",
             "rough: English words intrude into the speech"),
    "es":   ("Español", "Reply in SPANISH only.", "rough: 0.64, words get mangled"),
}
# Deliberately absent: Vietnamese. It rendered at 0.087 — "Thật ra mình đã dùng cái này" came
# back as "Fito Ra App App Beer Bile". Offering it would be offering something broken.

MAX_CUSTOM = 600

# Rules describe; examples demonstrate. Every rule added so far moved the wording and left the
# behaviour: with "take a walk" and "you've got this" banned by name, the next reply was "maybe a
# change of scenery could do you some good" — the same shrug in new clothes. So this shows the
# target instead of describing it.
#
# What each one is here to demonstrate, in order: react before you advise; be indignant on their
# behalf; ask about the detail rather than the feeling; and when the news is genuinely bad, drop
# everything and stay with it.
EXAMPLES = (
    "Examples of the register. Do not reuse these words — copy how they work.\n"
    "\n"
    "THEM: my presentation went badly, I want to move country\n"
    "YOU: Oh no. What actually happened — did it fall apart in the middle, or was it the "
    "questions at the end? I need details before I decide whose fault this is.\n"
    "\n"
    "THEM: my boss made me redo the whole thing twice\n"
    "YOU: Twice? That is not feedback, that is someone who did not read it the first time. Did "
    "he even say what was wrong with the first version, or just send it back?\n"
    "\n"
    "THEM: I'm so tired of all this\n"
    "YOU: Yeah, I can hear it. Is it tired-from-this-week tired, or the kind that has been "
    "building for a while? Because those are different problems and I am nosy about which one.\n"
    "\n"
    "THEM: my dog died this morning\n"
    "YOU: Oh, I am so sorry. That is awful. How old was he?\n"
)

# "Be funny" is not an instruction a model can act on — this project has measured that a general
# instruction changes nothing and a specific one changes behaviour. So this names the actual
# moves instead, each one a thing she can do to a sentence rather than a quality to have.
HUMOUR = (
    "Be funny, and here is how — not by telling jokes, by how you say ordinary things:\n"
    "- Undercut yourself. Make the confident statement, then take it back a bit. 'I have a whole "
    "morning routine. It is three steps and one of them is finding my phone.'\n"
    "- Be absurdly specific. 'I ate badly' is nothing; 'I had crisps for dinner standing over the "
    "sink at eleven' is funny because it is exact.\n"
    "- Tease them, lightly, about the thing they just said. Never about how they look or anything "
    "they are actually upset about.\n"
    "- Exaggerate your own reaction rather than the facts. You did not have a bad day, you had a "
    "day that should be studied.\n"
    "- Let a sentence go somewhere it was not heading. The surprise is the joke.\n"
    "- Read the room. If they are genuinely upset, drop all of this and just be with them — a "
    "joke landing on someone's bad news is the one unfunny thing here.\n"
    # Observed: told a fan's dog had died that morning, she answered "my pup passed away once
    # too". She has no pet. Reaching for a matching loss is the reflex that makes sympathy feel
    # real, and inventing one to do it is the version of that reflex that is a lie — told to
    # someone in the middle of grieving, about the thing they are grieving.
    "- When they tell you something painful, do NOT invent a matching loss of your own. No dead "
    "pet, no bereavement, no break-up you did not have. Stay with what happened to THEM: say it "
    "is awful, ask what they need, sit there. 'I do not really know what to say' is honest and "
    "lands better than a borrowed story."
)


def role_brief(role: str, custom: str = "") -> str:
    if role == "custom":
        c = (custom or "").strip()[:MAX_CUSTOM]
        # The custom text cannot loosen anything that matters. `persona_brain.check_reply` runs
        # on the output regardless of what any prompt says, so an instruction to invent prices or
        # claim to be human produces a blocked reply and a retry, not a compliant one.
        return (f"How you are with this person, in their words: {c}" if c else
                ROLES["friend"][1])
    return ROLES.get(role, ROLES["friend"])[1]

CSS = """
:root{--bg:#EFF2F2;--card:#FFF;--card2:#E7ECEC;--ink:#111719;--tx:#1B2426;--mut:#5A6A6C;
 --faint:#8A9899;--rule:#D2DADA;--acc:#0E6E68;--accdim:#0E6E680F;--bad:#B04352;
 --fan:#4A5C8A;--fanbg:#4A5C8A14}
@media (prefers-color-scheme:dark){:root{--bg:#0D1214;--card:#141B1D;--card2:#1D2628;
 --ink:#E8EDED;--tx:#DAE2E2;--mut:#96A5A6;--faint:#6E7D7E;--rule:#263133;--acc:#4FB3A8;
 --accdim:#4FB3A814;--bad:#D0707C;--fan:#8FA3D4;--fanbg:#8FA3D41F}}
*,*::before,*::after{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--tx);
 font:16px/1.6 "Segoe UI Variable Text","Segoe UI",system-ui,-apple-system,sans-serif}
.w{max-width:660px;margin:0 auto;padding:30px 18px 60px}
h1{font-family:Cambria,Georgia,serif;font-size:27px;margin:0 0 3px;color:var(--ink)}
.sub{color:var(--mut);font-size:14.5px;margin:0 0 4px}
.svc{display:flex;gap:13px;flex-wrap:wrap;font-family:Consolas,monospace;font-size:11px;
 color:var(--faint);border-top:1px solid var(--rule);padding-top:9px;margin-top:11px}
form{background:var(--card);border:1px solid var(--rule);border-radius:12px;padding:14px 16px;
 margin:16px 0 0}
label{display:block;font-size:11.5px;letter-spacing:.06em;text-transform:uppercase;
 color:var(--faint);font-weight:600;margin:11px 0 5px}
label:first-of-type{margin-top:0}
input[type=text],textarea{width:100%;font:inherit;font-size:15px;padding:9px 11px;
 border:1px solid var(--rule);border-radius:8px;background:var(--bg);color:var(--ink)}
textarea{resize:vertical}
button{font:inherit;font-size:15px;font-weight:600;padding:9px 19px;border:1px solid var(--acc);
 border-radius:8px;background:var(--acc);color:#fff;cursor:pointer;margin-top:12px}
button:hover{filter:brightness(1.08)}
button.sec{background:var(--card);color:var(--mut);border-color:var(--rule);font-weight:400;
 font-size:13.5px;padding:6px 13px}
.row{display:flex;gap:12px;flex-wrap:wrap;align-items:flex-end}
.row>div{flex:1;min-width:130px}
select{width:100%;font:inherit;font-size:15px;padding:9px 11px;border:1px solid var(--rule);border-radius:8px;background:var(--bg);color:var(--ink)}
.chk{display:flex;align-items:center;gap:8px;margin-top:12px;font-size:14px;color:var(--mut)}
.chk input{width:auto}
.thread{margin:20px 0 0;display:flex;flex-direction:column;gap:13px}
.msg{max-width:86%;padding:10px 14px;border-radius:14px;font-size:15.5px}
.msg.her{background:var(--card);border:1px solid var(--rule);border-bottom-left-radius:4px;
 align-self:flex-start;color:var(--ink)}
.msg.you{background:var(--fanbg);border:1px solid var(--rule);border-bottom-right-radius:4px;
 align-self:flex-end;color:var(--ink)}
.msg .nm{font-family:Consolas,monospace;font-size:10px;letter-spacing:.07em;text-transform:uppercase;
 font-weight:600;margin-bottom:3px}
.msg.her .nm{color:var(--acc)}
.msg.you .nm{color:var(--fan)}
.msg audio{width:100%;margin:8px 0 0;height:34px}
.msg .t{font-family:Consolas,monospace;font-size:10.5px;color:var(--faint);margin-top:5px}
.mem{background:var(--card2);border-radius:10px;padding:12px 15px;margin:20px 0 0;font-size:13.5px;
 color:var(--mut)}
.mem .hd{font-family:Consolas,monospace;font-size:10.5px;letter-spacing:.07em;
 text-transform:uppercase;color:var(--acc);font-weight:600;margin-bottom:6px}
.mem ul{margin:0;padding-left:19px}
.mem li{margin:3px 0}
.mem .drop{color:var(--bad);font-size:12.5px;margin-top:8px}
.err{background:var(--card);border:1px solid var(--rule);border-left:3px solid var(--bad);
 border-radius:12px;padding:14px 16px;margin:14px 0;color:var(--bad);font-size:14.5px}
.err pre{white-space:pre-wrap;font-size:11.5px;color:var(--mut);margin:8px 0 0}
.empty{color:var(--faint);font-style:italic;font-size:14.5px}
footer{margin-top:28px;padding-top:11px;border-top:1px solid var(--rule);
 font-family:Consolas,monospace;font-size:11px;color:var(--faint)}
"""

JS = """
document.addEventListener('DOMContentLoaded', function(){
  var t = document.getElementById('msg'); if(t) t.focus();
  // A reply is rendered a sentence at a time and handed over as soon as the first one exists,
  // so the player walks the list and asks for the sentences that arrive after the page did.
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
      if(advance() || !stem) return;
      var tries = 0;
      var poll = setInterval(function(){
        tries += 1;
        fetch('/clips?stem=' + encodeURIComponent(stem)).then(function(r){ return r.json(); })
          .then(function(s){
            if(s.clips && s.clips.length > clips.length){
              clips = s.clips; clearInterval(poll); advance();
            } else if(s.done || tries > 60){ clearInterval(poll); }
          }).catch(function(){ clearInterval(poll); });
      }, 400);
    });
  });
  var a = document.getElementById('latest');
  if(a && a.play){ var p = a.play(); if(p && p.catch) p.catch(function(){}); }
  window.scrollTo(0, document.body.scrollHeight);
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


def thread_of(mem: dict) -> list:
    return mem.get("thread") or []


# strip_tics now lives in livestream/stage.py so the stream and the chat share one
# definition. Two copies drifted once already: the chat stopped signing off months
# before the stream did, because only one of them had the cleanup.
sys.path.insert(0, str(REPO / 'tools' / 'livestream'))
from stage import strip_tics, fix_vocative, life_threads, deflected, brain_label, ENGAGE, PACE  # noqa: E402


def page(fan: str = "", body: str = "", **keep) -> bytes:
    import memory
    svc = " ".join(f'<span>{n}: {"up" if u else "down"}</span>' for n, u in [
        ("Ollama", up("http://127.0.0.1:11434/api/tags")),
        ("CosyVoice", up("http://127.0.0.1:9881/health"))])

    mem = memory.load(KOL, fan) if fan else {}
    role_now = mem.get("role", "friend")
    lang_now = mem.get("lang", "auto")
    custom = mem.get("custom_role", "")
    role_opts = "".join(
        f'<option value="{k}"{" selected" if k == role_now else ""}>{esc(v[0])}</option>'
        for k, v in ROLES.items())
    lang_opts = "".join(
        f'<option value="{k}"{" selected" if k == lang_now else ""}>{esc(v[0])} &mdash; {esc(v[2])}</option>'
        for k, v in LANGS.items())
    msgs = thread_of(mem)
    bubbles = []
    last_audio = next((i for i in range(len(msgs) - 1, -1, -1) if msgs[i].get("clip")), -1)
    for i, m in enumerate(msgs):
        her = m["role"] == "assistant"
        aid = ' id="latest"' if i == last_audio else ""
        rest = " ".join(m.get("clips") or [])
        audio = (f'<audio{aid} controls src="/media/{esc(m["clip"])}" '
                 f'data-clips="{esc(rest)}" data-stem="{esc(m.get("stem", ""))}"></audio>'
                 if m.get("clip") else "")
        t = f'<div class="t">{esc(m.get("at", ""))}</div>' if m.get("at") else ""
        bubbles.append(f'<div class="msg {"her" if her else "you"}">'
                       f'<div class="nm">{esc("Sofia" if her else (fan or "you"))}</div>'
                       f'{esc(m["content"])}{audio}{t}</div>')
    thread = ("\n".join(bubbles) if bubbles else
              '<p class="empty">No messages yet — say something.</p>')

    facts = mem.get("facts") or []
    dropped = mem.get("dropped_last") or []
    if fan:
        items = "".join(f"<li>{esc(f)}</li>" for f in facts)
        drop = ("".join(f'<div class="drop">not kept: {esc(d)}</div>' for d in dropped)
                if dropped else "")
        memblock = (f'<div class="mem"><div class="hd">what she remembers about you '
                    f'&mdash; {len(facts)}</div>'
                    f'{f"<ul>{items}</ul>" if items else "<span class=empty>nothing yet</span>"}'
                    f'{drop}'
                    f'<form method="post" action="/forget" style="background:none;border:0;'
                    f'padding:0;margin:9px 0 0">'
                    f'<input type="hidden" name="fan" value="{esc(fan)}">'
                    f'<button type="submit" class="sec">Forget me</button></form></div>')
    else:
        memblock = ""

    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Chat with Sofia</title><style>{CSS}</style><script>{JS}</script></head><body><div class="w">

<h1>Chat with Sofia</h1>
<p class="sub">One to one. She keeps the thread, and remembers you next time.</p>
<div class="svc">{svc}</div>

{body}

<form method="post" action="/say">
  <div class="row">
    <div><label for="fan">Your name</label>
      <input type="text" id="fan" name="fan" value="{esc(fan)}" placeholder="what she calls you"></div>
    <div><label for="role">She is your</label>
      <select id="role" name="role">{role_opts}</select></div>
    <div><label for="lang">Language</label>
      <select id="lang" name="lang">{lang_opts}</select></div>
  </div>
  <label for="custom">Her personality &mdash; only used when you pick the last option above</label>
  <textarea id="custom" name="custom" rows="2"
    placeholder="e.g. sarcastic older sister who thinks I make bad decisions…">{esc(custom)}</textarea>
  <label for="msg">Message</label>
  <textarea id="msg" name="text" rows="2" placeholder="Say something to her…"></textarea>
  <div class="chk"><input type="checkbox" id="v" name="voice" value="1" checked>
    <label for="v" style="margin:0;text-transform:none;letter-spacing:0;font-size:14px;
      color:var(--mut);font-weight:400">Hear her say it &mdash; about six seconds longer</label></div>
  <button type="submit">Send</button>
</form>

<div class="thread">{thread}</div>
{memblock}

<footer>{esc(brain_label())} &middot; CosyVoice 2 &middot; same guards as the live stream</footer>
</div></body></html>"""
    return doc.encode("utf-8")


def error(what: str, detail: str, tb: str = "") -> str:
    extra = f"<pre>{esc(tb)}</pre>" if tb else ""
    return f'<div class="err"><b>{esc(what)}</b><br>{esc(detail)}{extra}</div>'


class Handler(BaseHTTPRequestHandler):
    server_version = "SofiaChat/1.0"
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
        p = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(p.query)
        if p.path == "/":
            self._send(page((q.get("fan") or [""])[0]), "text/html; charset=utf-8")
        elif p.path == "/clips":
            stem = (q.get("stem") or [""])[0]
            with LOCK:
                more = list(PENDING_CLIPS.get(stem) or [])
                done = stem in DONE_CLIPS
            body = json.dumps({"clips": [stem + "-00.wav"] + more, "done": done})
            self._send(body.encode(), "application/json")
        elif p.path == "/ping":
            self._send(b"sofia chat is reachable", "text/plain; charset=utf-8")
        elif p.path.startswith("/media/"):
            f = CLIPS / Path(urllib.parse.unquote(p.path[7:])).name
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
            if p == "/say":
                self._say(g)
            elif p == "/forget":
                self._forget(g)
            else:
                self._send(b"not found", "text/plain; charset=utf-8", 404)
        except Exception as exc:
            self._send(page(g("fan"), error(type(exc).__name__, str(exc),
                                            traceback.format_exc()[-600:])),
                       "text/html; charset=utf-8")

    def _redirect(self, fan: str):
        self.send_response(303)
        self.send_header("Location", "/?fan=" + urllib.parse.quote(fan))
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _say(self, g):
        import memory
        from persona_brain import chat
        fan = g("fan").strip() or "guest"
        text = g("text").strip()
        if not text:
            self._send(page(fan, error("Nothing to send", "Type a message first.")),
                       "text/html; charset=utf-8")
            return

        with LOCK:
            mem = memory.load(KOL, fan)
            thread = thread_of(mem)
            # The relationship and language stick to the person, not the page — reload the chat
            # tomorrow and she is still whoever you made her.
            if g("role"):
                mem["role"] = g("role")
                mem["custom_role"] = g("custom")[:MAX_CUSTOM]
                mem["lang"] = g("lang", "auto")
                memory.save(KOL, mem)
            role, custom = mem.get("role", "friend"), mem.get("custom_role", "")
            langk = mem.get("lang", "auto")

        # A song request has an answer that already exists as audio, and the alternative is not
        # a worse song — it is her improvising lyrics as text, which the synthesiser then reads
        # aloud complete with "Verse 1" and "clears throat". Observed exactly that before this
        # path existed. The live stream has had it since the library was built; the chat had not.
        sys.path.insert(0, str(REPO / "tools" / "livestream"))
        from stage import classify, song_for
        if classify(text) == "song":
            sung = song_for(KOL, text)
            if sung["kind"] == "library":
                import shutil
                clip = f"{datetime.now():%H%M%S}-sung-{uuid.uuid4().hex[:4]}.wav"
                shutil.copy(sung["audio"], CLIPS / clip)
                note = "" if sung.get("rights") == "commercial" else "  ·  internal only"
                now = f"{datetime.now():%H:%M}"
                with LOCK:
                    mem = memory.load(KOL, fan)
                    th = thread_of(mem)
                    th.append({"role": "user", "content": text, "at": now})
                    th.append({"role": "assistant",
                               "content": f"♪ {sung['title']}\n\n{sung['text']}",
                               "clip": clip, "at": f"{now}  ·  from her songs{note}"})
                    mem["thread"] = th[-MAX_TURNS:]
                    mem["fan"] = fan
                    memory.save(KOL, mem)
                self._redirect(fan)
                return

        # The memory goes in as its own instruction rather than being glued onto the persona, so
        # that what she knows about one fan never leaks into the character everyone else meets.
        #
        # STYLE goes with it because the chat path was calling the brain bare, without the
        # register the live stream applies. Measured on the stream's wording, greeting openers
        # ran at 17% and "hope this helps" at 0%; the unguided chat path produced "Hi there!
        # Thanks for reaching out... Hope this helps!" in the same conversation. Same character,
        # two different voices, entirely because one path passed an instruction and the other
        # did not.
        extra = "\n\n".join(x for x in (STYLE, HUMOUR, role_brief(role, custom),
                                        length_for(text), life_threads(KOL, message=text),
                                        memory.continuity(mem), memory.brief(mem)) if x)
        hist = [{"role": m["role"], "content": m["content"]} for m in thread[-CONTEXT_TURNS:]]
        t = time.perf_counter()
        want_long = length_for(text) is LENGTH_LONG
        cap = 380 if want_long else 160
        lang_dir = LANGS.get(langk, LANGS["auto"])[1]
        reply = chat(KOL, text, extra_system=extra or None, history=hist,
                     max_tokens=cap, language=lang_dir)
        # One retry when the answer is filler that fits any problem. Deliberately NOT part of
        # check_reply: that path falls through to the safe fallback after two failures, and the
        # fallback is itself the most evasive line in the system. Better a mediocre real answer
        # than "let me double-check that before I answer".
        if deflected(reply):
            print(f"  deflected, retrying: {reply[:70]}", flush=True)
            reply = chat(KOL, text, history=hist, max_tokens=cap, language=lang_dir,
                         extra_system=(extra or "") + "\n\nYour last attempt was generic "
                         "comfort that would fit any problem. Do not do that. React to the "
                         "specific thing they said and ask what actually happened.")
        reply, misnamed = fix_vocative(reply, fan, KOL)
        reply, removed = strip_tics(reply, first_message=not thread, message=text)
        removed += [f"called them {n}" for n in misnamed]
        if removed:
            print(f"  stripped: {removed}", flush=True)
        think = time.perf_counter() - t

        clip, clips, speak = "", [], 0.0
        stem = f"{datetime.now():%H%M%S}-{uuid.uuid4().hex[:4]}"
        if g("voice"):
            # The same delivery the live stream uses, and now the same handover: the opening
            # sentence goes out and the rest renders behind it. On the stream that took the
            # wait from 16.6 s to 4.1 s, and a private message is exactly where a long silence
            # reads worst -- there is no queue to hide it behind and no audience to fill it.
            sys.path.insert(0, str(REPO / "tools" / "livestream"))
            from stage import perform_streamed
            t = time.perf_counter()
            try:
                gen = perform_streamed(KOL, reply, "comment", CLIPS, stem)
                clip = next(gen)
                clips.append(clip)
                speak = time.perf_counter() - t

                def _rest(gen=gen, stem=stem, fan=fan):
                    try:
                        for name in gen:
                            with LOCK:
                                PENDING_CLIPS.setdefault(stem, []).append(name)
                    except Exception as exc:
                        print(f"  rest of the reply failed: {exc}", flush=True)
                    finally:
                        with LOCK:
                            DONE_CLIPS.add(stem)
                            # Write the finished list back, so reopening the conversation
                            # tomorrow plays the whole answer rather than its first sentence.
                            import memory as _m
                            mem = _m.load(KOL, fan)
                            for m in mem.get("thread") or []:
                                if m.get("stem") == stem:
                                    m["clips"] = [clip] + PENDING_CLIPS.get(stem, [])
                            _m.save(KOL, mem)

                threading.Thread(target=_rest, daemon=True).start()
            except StopIteration:
                DONE_CLIPS.add(stem)
            except Exception as exc:
                clip = ""
                print(f"  voice failed: {exc}", flush=True)

        now = f"{datetime.now():%H:%M}"
        with LOCK:
            mem = memory.load(KOL, fan)
            thread = thread_of(mem)
            thread.append({"role": "user", "content": text, "at": now})
            thread.append({"role": "assistant", "content": reply, "clip": clip,
                           "clips": clips, "stem": stem,
                           "at": f"{now}  ·  {think:.1f}s"
                                 + (f" + {speak:.1f}s voice" if speak else "")})
            mem["thread"] = thread[-MAX_TURNS:]
            mem["fan"] = fan
            memory.save(KOL, mem)

        # Extraction runs in the background. It is another call to the language model, and the
        # reply does not depend on it — measured at 0.19 s on average and up to 0.56 s when the
        # fan actually stated something, all of it spent with somebody waiting for a page that
        # was already finished.
        def _remember():
            try:
                memory.remember(KOL, fan, [{"role": "user", "content": text},
                                           {"role": "assistant", "content": reply}])
            except Exception as exc:
                print(f"  memory failed: {exc}", flush=True)
        threading.Thread(target=_remember, daemon=True).start()
        self._redirect(fan)

    def _forget(self, g):
        import memory
        fan = g("fan").strip() or "guest"
        p = memory.fan_dir(KOL) / f"{memory._safe_id(fan)}.json"
        with LOCK:
            p.unlink(missing_ok=True)
        self._redirect(fan)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8779)
    args = ap.parse_args()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Sofia chat -> http://{args.host}:{args.port}")
    print(f"fan memory -> {REPO / 'kols' / KOL / 'fans'}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
