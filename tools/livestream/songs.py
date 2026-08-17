#!/usr/bin/env python3
"""A library of songs she can actually perform, in her own voice.

The live stream can already answer a song request, but not by singing: CosyVoice and GPT-SoVITS
have no pitch or melody control, and asking them to sing *narrows* the pitch range from 17.50
semitones to 10.06. What comes out is slower, steadier speech — recitation.

Singing needs two things this module joins together. Something that can carry a melody produces
the vocal, and the RVC model trained on 2026-08-07 replaces the timbre with hers. That split
works because RVC keeps the source's pitch contour: measured 15.20 semitones in, 14.40 out.

So a song is a file somebody put in `kols/<id>/songs/raw/`, converted once and cached. Where
that file came from is deliberately not this module's business — Suno, a session singer, a
public-domain recording. What matters is that it sings and that its rights are recorded, which
is why every entry carries `origin` and `licence_note` and why `prepare_all` refuses an entry
missing them.

Two constraints carried over from the verification, both enforced here rather than documented
and hoped for:

* **Pitch.** Her training corpus is speech at roughly 195-220 Hz. Identity falls from 0.6448 at
  no shift to 0.5476 at +10 semitones, so `pitch_shift` is clamped to the measured safe range
  and says when it clamps.
* **Conversion is slow relative to a live turn.** A conversation turn is 6-9 seconds; a
  three-minute song takes about a minute to convert. So conversion happens ahead of time via
  `prepare_all`, never while someone is waiting.

    python tools/livestream/songs.py sofia-vargas --prepare
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools" / "tts_train"))

SAFE_PITCH = 5      # matches rvc_pipeline.SAFE_PITCH; see the module docstring

# What a song may be used for. This is a required field rather than an optional note because the
# distinction is invisible once the audio exists: a track from a free generator tier and one
# from a paid tier are the same file with the same waveform, and the difference only surfaces
# when someone publishes the wrong one. Suno's free tier grants no commercial rights; its paid
# tiers do. Recording that at import time is the only moment the answer is actually known.
RIGHTS = {
    "internal_only": "demo, review and testing only — must not be published or monetised",
    "commercial": "cleared for published, monetised content",
}


def song_dir(kol_id: str) -> Path:
    return REPO / "kols" / kol_id / "songs"


def manifest_path(kol_id: str) -> Path:
    return song_dir(kol_id) / "songs.json"


def library(kol_id: str) -> list[dict]:
    """Every song on file, whether or not it has been converted yet."""
    p = manifest_path(kol_id)
    if not p.is_file():
        return []
    return json.loads(p.read_text(encoding="utf-8")).get("songs", [])


def ready(kol_id: str, *, publishable: bool = False) -> list[dict]:
    """The ones that exist in her voice right now.

    `publishable=True` keeps only what is cleared for published content. Anything used on a
    stream that goes out, or in a clip that gets posted, should be selected through that filter —
    the default is deliberately permissive because the live demo is internal.
    """
    out = []
    for s in library(kol_id):
        c = s.get("converted")
        if not (c and (song_dir(kol_id) / c).is_file()):
            continue
        if publishable and s.get("rights") != "commercial":
            continue
        out.append(s)
    return out


def internal_only(kol_id: str) -> list[dict]:
    """What is in the library but must not be published — the list worth checking before a launch."""
    return [s for s in library(kol_id) if s.get("rights") != "commercial"]


_WORD = re.compile(r"[a-zA-ZÀ-ỹ]{3,}")

# Words that appear in almost every song request and carry no preference. Left in, "sing me
# something" matches whichever entry happens to have "song" in its keywords.
_STOP = {"sing", "song", "please", "can", "you", "for", "me", "something", "the", "and",
         "hat", "bai", "cho", "minh", "toi", "mot"}


def match(request: str, entries: list[dict]) -> dict | None:
    """Pick the song a request is asking for, or nothing.

    Returning None is a real answer: a request that matches nothing should be met with an
    honest "I do not have one like that" and the recitation fallback, not with whichever track
    happened to sort first.
    """
    if not entries:
        return None
    words = {w.lower() for w in _WORD.findall(request or "")} - _STOP
    # No distinguishing words at all means "sing me something" — a request with no preference,
    # not a request nothing satisfies. Returning None there sent the bare ask to the recitation
    # fallback while three finished songs sat in the library, which is the wrong answer to the
    # most common way anyone asks. Preference is the manifest's order.
    if not words:
        return entries[0]
    best, score = None, 0
    for s in entries:
        pool = {w.lower() for w in
                (s.get("keywords") or []) + (s.get("mood") or []) + [s.get("title", "")]
                for w in _WORD.findall(str(w))}
        hit = len(words & pool)
        if hit > score:
            best, score = s, hit
    return best


# Her speaking register, measured: median 182.3 Hz. The model was trained on speech and knows
# only this band, which is the constraint a sung line runs into.
HER_BAND = (165.0, 235.0)


def clamp_pitch(p) -> tuple[int, str | None]:
    """Bound a manual shift. Note what this does NOT decide — see `check_register`.

    An earlier version of this treated ±5 semitones as the safety rule outright. That was the
    wrong quantity: the measurement it came from shifted a source that already sat in her
    register, so it described how far you may move *from* her range, not what the result should
    land on. A real song exposed the difference — its vocal was already +8.4 above her, so the
    correcting shift was -8, and clamping that to -5 would have blocked the one move that helped.
    The shift size is only a sanity bound now; the register check is the real rule.
    """
    try:
        p = int(p or 0)
    except (TypeError, ValueError):
        return 0, "pitch_shift was not a number; used 0"
    if abs(p) <= 12:
        return p, None
    c = 12 if p > 0 else -12
    return c, f"pitch_shift {p:+d} clamped to {c:+d}: a full octave is already implausible"


def vocal_median_hz(path: Path) -> float | None:
    """Median fundamental of a vocal stem, using the project's octave-safe tracker."""
    try:
        sys.path.insert(0, str(REPO / "tools" / "voice_eval"))
        import prosody
        f = prosody.feats(prosody.load_any(path))
        return float(f["f0_med"]) if f else None
    except Exception:
        return None


def check_register(vocal: Path, pitch: int = 0) -> dict:
    """Say whether the converted vocal will land somewhere the model actually knows.

    This is the check that matters, and it is about the *result*, not the shift. Measured on two
    real generated songs whose vocals sat at 297 and 311 Hz — around +8.5 and +9.2 semitones
    above her — conversion reached only 0.4826 and 0.4915 against 0.6448 on material in her
    range. Shifting them into her band recovered most of it (0.5294 and 0.6057), which is what
    identifies the register as the cause.

    The catch is that the fix is not available after the fact. Shifting the vocal alone leaves it
    in a different key from the backing it has to sit over, so a song in too high a key has to be
    generated again lower rather than corrected here.
    """
    import math
    med = vocal_median_hz(vocal)
    if med is None:
        return {"median_hz": None, "ok": True, "advice": None}
    landed = med * (2 ** (pitch / 12.0))
    lo, hi = HER_BAND
    if lo <= landed <= hi:
        return {"median_hz": med, "landed_hz": landed, "ok": True, "advice": None}
    off = 12 * math.log2(landed / ((lo + hi) / 2))
    want = int(round(12 * math.log2(((lo + hi) / 2) / med)))
    return {
        "median_hz": med, "landed_hz": landed, "ok": False, "suggested_pitch": want,
        "advice": (f"the vocal lands at {landed:.0f} Hz, {off:+.1f} semitones from her register "
                   f"({lo:.0f}-{hi:.0f} Hz), so it will be transposed {want:+d} — the voice by "
                   f"RVC and the backing by resampling, together, so they stay in the same key. "
                   f"Generated vocals land here almost every time: three tracks measured 297, "
                   f"311 and 290 Hz, and asking the generator for a lower register moved it by "
                   f"7 Hz across three attempts. Set auto_key to false on the entry to skip it.")}


def split_stems(src: Path, workdir: Path) -> tuple[Path, Path]:
    """Separate a finished song into its vocal and everything else.

    A track downloaded from a generator is a mix. Putting the mix through RVC converts the
    drums and guitars along with the singer, because RVC has no idea which part of the signal
    is a voice — it just remaps what it is given. Separating first is what makes the
    instrumental survive intact.
    """
    import subprocess
    workdir.mkdir(parents=True, exist_ok=True)
    # encoding is not optional here. Demucs prints a progress bar containing characters the
    # Windows default codepage cannot decode, and without this the reader thread dies on a
    # UnicodeDecodeError — which costs nothing while demucs succeeds and costs the entire error
    # message the moment it does not.
    subprocess.run([sys.executable, "-m", "demucs", "--two-stems=vocals", "-n", "htdemucs",
                    "-o", str(workdir), "--filename", "{stem}.{ext}", str(src)],
                   check=True, capture_output=True, text=True,
                   encoding="utf-8", errors="replace")
    out = workdir / "htdemucs"
    vocals, rest = out / "vocals.wav", out / "no_vocals.wav"
    if not vocals.is_file() or not rest.is_file():
        raise RuntimeError("demucs did not produce both stems")
    return vocals, rest


def shift_audio(src: Path, dst: Path, semitones: int) -> Path:
    """Transpose audio without changing its length, for the backing track.

    Resample to move the pitch, then stretch the timeline back. On instruments this is fine —
    what it also does, drag the formants with the pitch, has no meaning for a guitar. On a voice
    it is audibly wrong, which is why the vocal is shifted by RVC instead: measured, a vocal
    transposed this way and then converted scored 0.4566 against the speaker, where letting RVC
    do the shift scored 0.6056.
    """
    import subprocess
    if semitones == 0:
        shutil_copy(src, dst)
        return dst
    ratio = 2 ** (semitones / 12.0)
    dst.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src),
                    "-af", f"asetrate=44100*{ratio:.6f},aresample=44100,atempo={1/ratio:.6f}",
                    "-ar", "44100", str(dst)],
                   check=True, capture_output=True, text=True,
                   encoding="utf-8", errors="replace")
    return dst


def shutil_copy(src: Path, dst: Path) -> None:
    import shutil
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(src, dst)


def soften(src: Path, dst: Path) -> Path:
    """Take the edge off the converted vocal before it goes back over the backing.

    Chosen by measurement rather than by ear alone. Energy in 2-5 kHz is where a voice reads as
    harsh, and the conversion already does most of the work — the Suno source measures 30.1%
    there and the converted vocal 8.5%. A 4 dB dip at 3.2 kHz takes it to 6.5%, a further 24%,
    while speaker similarity moves 0.4866 to 0.4817, which is inside the run-to-run spread this
    engine has anyway.

    A 220 Hz lift was tried alongside it and rejected: 6.3% harshness for 0.4700 similarity,
    paying real identity for a difference the harshness figure barely registers.

    What did NOT help, and is worth recording so it is not tried again: RVC's own `protect` and
    `index_rate`. Six combinations across the plausible range landed between 0.4866 and 0.4949
    similarity and 8.5-8.6% harshness — no signal at all on sung material.
    """
    import subprocess
    dst.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src),
                    "-af", "equalizer=f=3200:width_type=o:width=1.4:g=-4",
                    str(dst)], check=True, capture_output=True, text=True,
                   encoding="utf-8", errors="replace")
    return dst


def remix(vocal: Path, rest: Path, dst: Path) -> Path:
    """Put the converted voice back over the untouched backing."""
    import subprocess
    dst.parent.mkdir(parents=True, exist_ok=True)
    # `amix` alone halves the level of both inputs and would quietly make every song 6 dB
    # softer than its source; normalize=0 keeps them where the stems already sat, and the
    # limiter catches the sums that then exceed full scale.
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(vocal), "-i", str(rest),
                    "-filter_complex",
                    "[0:a][1:a]amix=inputs=2:duration=longest:normalize=0,alimiter=limit=0.94",
                    "-ar", "44100", str(dst)], check=True, capture_output=True, text=True,
                   encoding="utf-8", errors="replace")
    return dst


def prepare(kol_id: str, entry: dict, *, force: bool = False) -> dict:
    """Convert one song into her voice, once. Returns the entry with `converted` filled in.

    `stems` says what the source is. "mix" — the default, and what any generator hands you — is
    separated first so only the singer is converted. "vocal" is for an isolated vocal track and
    skips separation.
    """
    from rvc_pipeline import convert

    d = song_dir(kol_id)
    src = d / entry["source"]
    if not src.is_file():
        raise FileNotFoundError(f"{entry.get('id', '?')}: no source audio at {src}")
    if not entry.get("origin") or not entry.get("licence_note"):
        # The project's standing rule is to settle rights before building on something. A song
        # whose provenance is blank is exactly the thing that gets published and then queried.
        raise ValueError(f"{entry.get('id', '?')}: origin and licence_note are required")
    if entry.get("rights") not in RIGHTS:
        raise ValueError(
            f"{entry.get('id', '?')}: rights must be one of {', '.join(sorted(RIGHTS))}. "
            f"A free generator tier is {'internal_only'!r}; a paid tier with commercial terms "
            f"is {'commercial'!r}. Refusing to convert until this is stated, because after "
            f"conversion the two are indistinguishable files.")

    out_rel = entry.get("converted") or f"sofia/{src.stem}.wav"
    out = d / out_rel
    pitch, note = clamp_pitch(entry.get("pitch_shift"))
    if out.is_file() and not force:
        return {**entry, "converted": out_rel, "note": "already converted", "pitch": pitch}

    if (entry.get("stems") or "mix") == "vocal":
        convert(src, out, kol_id=kol_id, pitch=pitch)
        return {**entry, "converted": out_rel, "note": note, "pitch": pitch, "separated": False}

    work = d / ".work" / src.stem
    vocals, rest = split_stems(src, work)
    reg = check_register(vocals, pitch)

    # Bring the song into her register automatically when it is not already there. Generated
    # vocals land where pop vocals land — three tracks measured at 297, 311 and 290 Hz against
    # her 182 — and asking the generator for a lower key did not move it (three attempts, 7 Hz).
    # So the transposition happens here instead, and it has to be done in two different ways at
    # once: RVC shifts the voice, because it moves the pitch while preserving what makes the
    # timbre hers, and ffmpeg shifts the backing, because resampling is harmless on instruments.
    # Shifting only the vocal would leave it in a different key from its own accompaniment.
    if entry.get("auto_key", True) and not reg["ok"] and reg.get("suggested_pitch"):
        pitch = int(reg["suggested_pitch"])
        note = ((note + "; " if note else "")
                + f"transposed {pitch:+d} semitones: the vocal sat {reg['landed_hz']:.0f} Hz, "
                  f"outside her {HER_BAND[0]:.0f}-{HER_BAND[1]:.0f} Hz register")
        rest = shift_audio(rest, work / "backing_shift.wav", pitch)

    sung = work / "vocals_sofia.wav"
    convert(vocals, sung, kol_id=kol_id, pitch=pitch)
    sung = soften(sung, work / "vocals_soft.wav")
    remix(sung, rest, out)
    return {**entry, "converted": out_rel, "note": note, "pitch": pitch, "separated": True,
            "register": reg}


def prepare_all(kol_id: str, *, force: bool = False) -> list[dict]:
    """Convert everything in the library and write the manifest back."""
    entries = library(kol_id)
    if not entries:
        return []
    done = []
    for e in entries:
        try:
            done.append(prepare(kol_id, e, force=force))
        except Exception as exc:
            done.append({**e, "error": str(exc)})
    p = manifest_path(kol_id)
    data = json.loads(p.read_text(encoding="utf-8"))
    data["songs"] = [{k: v for k, v in e.items() if k not in ("note", "error", "pitch")}
                     for e in done]
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return done


def score(kol_id: str) -> list[dict]:
    """How much each finished song actually sounds like her.

    Worth having because the pipeline can no longer be the problem: every track is separated,
    transposed into her register and converted the same way, and the results still range from
    0.43 to 0.61. What is left is the source voice, which nothing downstream can fix — so the
    useful move is to generate several takes and keep the ones that measure well, rather than
    keep the first one and wonder.

    Read it against 0.6448, which is what her own speech scores through the same measurement.
    """
    import shutil
    sys.path.insert(0, str(REPO / "tools" / "studio"))
    sys.path.insert(0, str(REPO / "tools" / "voice_eval"))
    from voice_studio import _normalise_loudness
    import denoise_ref as D

    d = song_dir(kol_id)
    tmp = d / ".score"
    tmp.mkdir(parents=True, exist_ok=True)

    def level(p: Path, n: str) -> Path:
        q = tmp / n
        shutil.copy(p, q)
        _normalise_loudness(q, -16.0)
        return q

    ref_src = REPO / "kols" / kol_id / "voice" / "ref_human.wav.orig"
    if not ref_src.is_file():
        ref_src = REPO / "kols" / kol_id / "voice" / "ref_human.wav"
    ref = level(ref_src, "ref.wav")

    out = []
    for s in ready(kol_id):
        p = d / s["converted"]
        sim = D.speaker_similarity(ref, level(p, f"{s['id']}.wav"))
        out.append({"id": s["id"], "title": s.get("title"), "similarity": sim,
                    "median_hz": vocal_median_hz(p)})
    return sorted(out, key=lambda x: -(x["similarity"] or 0))


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("kol_id")
    ap.add_argument("--prepare", action="store_true", help="convert every song into her voice")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--match", default=None, help="test what a request would pick")
    ap.add_argument("--score", action="store_true",
                    help="how much each finished song sounds like her")
    args = ap.parse_args()

    if args.score:
        rows = score(args.kol_id)
        print(f"{'song':<36}{'sounds like her':>17}{'median Hz':>11}")
        for r in rows:
            s = r["similarity"]
            mark = "" if s is None else ("   good" if s >= 0.58 else
                                         "   weak — consider regenerating" if s < 0.50 else "")
            print(f"{(r['title'] or r['id'])[:34]:<36}"
                  f"{('%.4f' % s) if s is not None else 'n/a':>17}"
                  f"{(r['median_hz'] or 0):11.0f}{mark}")
        print("\n  her own speech scores 0.6448 through the same measurement — that is the "
              "ceiling,\n  and the gap between songs is the source vocal, not the pipeline.")
        return 0

    if args.match is not None:
        m = match(args.match, ready(args.kol_id))
        print(f"  request: {args.match!r}")
        print(f"  picked : {m['title'] if m else 'nothing — would fall back to recitation'}")
        return 0

    if args.prepare:
        for e in prepare_all(args.kol_id, force=args.force):
            if e.get("error"):
                print(f"  {e.get('id', '?'):<22} FAILED  {e['error'][:80]}")
            else:
                extra = f"  ({e['note']})" if e.get("note") else ""
                print(f"  {e.get('id', '?'):<22} -> {e['converted']}{extra}")
                reg = e.get("register") or {}
                if reg.get("median_hz"):
                    state = "in her register" if reg["ok"] else "OUT OF RANGE"
                    print(f"    vocal {reg['median_hz']:.0f} Hz -> lands "
                          f"{reg.get('landed_hz', 0):.0f} Hz   {state}")
                if reg.get("advice"):
                    print(f"    {reg['advice']}")

    lib = library(args.kol_id)
    rdy = ready(args.kol_id)
    pub = ready(args.kol_id, publishable=True)
    print(f"\n  {len(lib)} in the library, {len(rdy)} ready in her voice, "
          f"{len(pub)} cleared for publishing")
    for s in rdy:
        mark = "" if s.get("rights") == "commercial" else "   INTERNAL ONLY"
        print(f"    {s.get('title', s.get('id'))}  [{', '.join(s.get('mood') or [])}]{mark}")
    blocked = internal_only(args.kol_id)
    if blocked:
        print(f"\n  Not for publication ({len(blocked)}) — demo and review only:")
        for s in blocked:
            print(f"    {s.get('title', s.get('id'))}: {s.get('origin', '')[:70]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
