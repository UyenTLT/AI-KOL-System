"""Same idea, but only on questions a viewer would actually ask HER, and with her identity held.

The first pass imported the dataset's situations along with its jokes: she answered a question
about teaching AS a teacher, called herself "the king of raiding the fridge", and replied to one
question entirely in Spanish. The jokes were fine; the inputs were not.

So: keep only questions addressed to a person about their own life, drop the professional and
technical topics a KOL is never asked, and say plainly that she does not take on somebody else's
job. Gender and language are checked afterwards rather than hoped for.
"""
import sys, json, pathlib, random, re
sys.path.insert(0, "tools/llm_train"); sys.path.insert(0, "tools/livestream")
sys.path.insert(0, "tools/livetalking"); sys.path.insert(0, "tools/studio")
for st in (sys.stdout, sys.stderr):
    try: st.reconfigure(errors="replace")
    except Exception: pass
from build_dataset import _client
from persona_brain import (check_reply, speaks_cjk, sanitize_for_speech, build_system_prompt)
from stage import deflected, life_threads

KEEP = {"relationships", "cooking", "travel", "food", "fashion", "home", "health", "sports", "art"}
YOU = re.compile(r"\byour?\b", re.I)
MALE = re.compile(r"\b(king|guy|dude|bro|mr|sir|he|him|his)\b", re.I)
SPANISH = re.compile(r"[¿¡]|\b(pero|que|como|est[aá]s|se[ñn]or|mucho|nada|porque)\b", re.I)

rows = [json.loads(l) for l in
        pathlib.Path("datasets/style/hf-humor-pairs.jsonl").read_text(encoding="utf-8").splitlines()
        if l.strip()]
pool = [r for r in rows if r.get("topic") in KEEP and YOU.search(r["prompt"])]
random.seed(11); random.shuffle(pool)
print(f"  {len(pool)} of {len(rows)} questions are personal AND on a topic a viewer would ask")

MODEL = "sofia-hsu-tuned"
no_cjk = not speaks_cjk("sofia-hsu")
SYS = (build_system_prompt("sofia-hsu") + "\n\n"
       "You are shown a question and a funny answer somebody else wrote. Answer the SAME question "
       "with the same comic move, in your own voice and out of your own life.\n"
       "- Keep what makes it funny: the exaggeration, the undercut, the absurdly exact detail.\n"
       "- Throw away their words, their puns and their examples entirely.\n"
       "- You are Sofia. You are a woman. You do not have their job and you never pretend to -- "
       "if the question assumes a job that is not yours, answer as yourself anyway.\n"
       "- English only. Two or three sentences. Speak it, do not write it.")

kept, shown, refused = [], [], {}
import os
LIMIT = int(os.getenv("HUMOR_LIMIT", "26"))
for i, r in enumerate(pool[:LIMIT]):
    if i and i % 50 == 0:
        print(f"  {i}/{LIMIT}, kept {len(kept)}", flush=True)
    try:
        life = life_threads("sofia-hsu", message=r["prompt"])
    except Exception:
        life = ""
    msgs = [{"role": "system", "content": SYS}]
    if life:
        msgs.append({"role": "system", "content": life})
    msgs.append({"role": "user",
                 "content": f"QUESTION: {r['prompt']}\n\nTHEIR FUNNY ANSWER: {r['answer']}"})
    try:
        c = _client().chat.completions.create(model=MODEL, temperature=0.9, max_tokens=150,
                                              messages=msgs)
        a = sanitize_for_speech((c.choices[0].message.content or "").strip())
    except Exception:
        continue
    why = check_reply(r["prompt"], a, no_cjk=no_cjk)
    if MALE.search(a): why = why + ["calls herself male"]
    if SPANISH.search(a): why = why + ["drifted into Spanish"]
    if deflected(a): why = why + ["generic comfort"]
    if len(a.split()) > 95: why = why + ["too long"]
    if why:
        for w in why: refused[w] = refused.get(w, 0) + 1
        continue
    kept.append({"prompt": r["prompt"], "answer": a})
    shown.append((r["prompt"], a))

print(f"  {len(kept)} of {LIMIT} survived; refused: {refused}\n")
for q, a in shown[:8]:
    print(f"  Q  {q[:92]}")
    print(f"  A  {a[:190]}")
    print()
p = pathlib.Path("datasets/style/sofia-humor-rewritten.jsonl")
with open(p, "w", encoding="utf-8") as fh:
    for r in kept:
        fh.write(json.dumps(r, ensure_ascii=False) + "\n")
print(f"  -> {p}")
