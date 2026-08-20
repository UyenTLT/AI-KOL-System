#!/usr/bin/env python3
"""Speak long text without waiting for all of it — synthesise sentence by sentence and start
playing the first one while the rest is still rendering.

The engine is not slow; waiting for it is. Measured on this box: a 60-character line takes
3.2 s and a 215-character paragraph takes 10.5 s, and until now nothing was heard until the
last sample of the last word existed.

What makes the fix work is that the real-time factor is **0.56-0.67** — the model produces
audio faster than it can be listened to. Split the text at sentence boundaries and the first
clip is ready in a couple of seconds; every clip after it finishes rendering before the
previous one has finished playing, so the queue never runs dry. Perceived wait drops from the
length of the whole paragraph to the length of its first sentence.

fp16 was tried first and is *slower* here, not faster: 0.66x on a short line, 0.89x on a long
one. The ONNX stages run on CPU on Windows, and the conversion overhead outweighs the gain.

    from stream_speak import speak_streaming
    speak_streaming("sofia-hsu", long_text, on_chunk=..., on_done=...)
"""
from __future__ import annotations

import re
import subprocess
import sys
import threading
import time
import wave
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools" / "studio"))

# Below this, one chunk is faster than the bookkeeping of several.
MIN_SPLIT_CHARS = 110

# Shortest first chunk worth speaking on its own. Below roughly this, the opening sounds
# clipped and the seam is more noticeable than the wait it saves.
MIN_FIRST = 45


def split_sentences(text: str, target: int = 160, first: int = 70) -> list[str]:
    """Break text into speakable pieces at sentence ends — the first one deliberately short.

    Two competing pressures. Long chunks sound better, because every seam is a place the
    delivery can jolt, and per-request overhead is paid once per chunk. Short chunks start
    sooner. The compromise is asymmetric: only the *first* chunk needs to be short, since it is
    the only one anybody waits for — everything after it renders while the previous piece is
    still playing.

    Measured on a 235-character paragraph: merging everything to 140 characters gave two chunks
    and first sound at 6.8 s. Capping the first at ~70 characters and letting the rest run to
    160 brings that down while leaving the bulk of the text in long, natural pieces.

    A clause break is accepted for the first chunk if no sentence ends early enough — a comma is
    a worse seam than a full stop, but a much better one than making the listener wait.
    """
    parts = re.split(r"(?<=[.!?…])\s+|(?<=[。！？])\s*", text.strip())
    parts = [p.strip() for p in parts if p.strip()]
    if not parts:
        return [text.strip()]

    head, rest = parts[0], parts[1:]
    if len(head) > first * 1.6:
        clause = re.split(r"(?<=[,;:，；])\s+", head)
        if len(clause) > 1:
            # Stop at the first clause long enough to stand on its own. Checking the length
            # *before* appending overshoots — a 53-character clause is under the 70 target, so
            # the next one gets added and the chunk lands at 112, which is most of what the
            # split was meant to avoid.
            acc = clause[0]
            for c in clause[1:]:
                if len(acc) >= MIN_FIRST:
                    break
                acc = f"{acc} {c}"
            if len(acc) < len(head):
                rest.insert(0, head[len(acc):].strip())
                head = acc

    out = [head]
    for p in rest:
        if len(out) > 1 and len(out[-1]) + len(p) + 1 <= target:
            out[-1] = f"{out[-1]} {p}"
        else:
            out.append(p)
    return out


def wav_seconds(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as w:
            return w.getnframes() / float(w.getframerate())
    except Exception:
        return 0.0


def play_blocking(path: Path) -> None:
    """Play a clip and return only when it has finished.

    winsound has no queue, so a second SND_ASYNC call cuts the first off mid-word. Sleeping for
    the clip's own length is what keeps consecutive chunks from overlapping.
    """
    try:
        import winsound
        winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)
        time.sleep(wav_seconds(path))
    except Exception:
        import os
        try:
            os.startfile(str(path))  # noqa: S606
            time.sleep(wav_seconds(path))
        except Exception:
            pass


def concat(parts: list[Path], dst: Path) -> Path:
    """Join the chunks into the single file that gets kept."""
    if len(parts) == 1:
        dst.write_bytes(parts[0].read_bytes())
        return dst
    # Absolute paths: ffmpeg resolves entries in a concat list relative to the *list file's*
    # directory, not the working directory, so relative paths silently point at the wrong place.
    lst = dst.with_name(dst.stem + "_concat.txt")
    lst.write_text("\n".join(f"file '{p.resolve().as_posix()}'" for p in parts), encoding="utf-8")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                    "-i", str(lst), "-c", "copy", str(dst)], check=True)
    lst.unlink(missing_ok=True)
    return dst


def speak_streaming(cid: str, text: str, out: Path, *, speed: float = 1.0,
                    ref_audio: str | None = None, ref_text: str | None = None,
                    on_chunk=None, on_done=None, work: Path | None = None) -> Path:
    """Synthesise in pieces, play each as it lands, and leave one joined file behind.

    `on_chunk(index, total, seconds_waited)` fires as each piece starts playing, so a UI can
    show progress instead of a frozen button.
    """
    from voice_studio import synthesize

    chunks = split_sentences(text) if len(text) > MIN_SPLIT_CHARS else [text]
    work = work or out.parent / f".{out.stem}_parts"
    work.mkdir(parents=True, exist_ok=True)

    rendered: list[Path] = []
    ready = threading.Semaphore(0)
    failure: list[BaseException] = []
    started = time.perf_counter()

    def produce() -> None:
        try:
            for i, part in enumerate(chunks):
                p = work / f"{i:02d}.wav"
                synthesize(cid, part, out=p, speed=speed,
                           ref_audio=ref_audio, ref_text=ref_text)
                rendered.append(p)
                ready.release()
        except BaseException as exc:      # noqa: BLE001 - surfaced to the caller below
            failure.append(exc)
            ready.release()

    producer = threading.Thread(target=produce, daemon=True)
    producer.start()

    for i in range(len(chunks)):
        ready.acquire()
        if failure:
            raise failure[0]
        clip = rendered[i]
        if on_chunk:
            on_chunk(i + 1, len(chunks), time.perf_counter() - started)
        play_blocking(clip)

    producer.join(timeout=5)
    if failure:
        raise failure[0]
    result = concat(rendered, out)
    for p in rendered:
        p.unlink(missing_ok=True)
    try:
        work.rmdir()
    except OSError:
        pass
    if on_done:
        on_done(result, time.perf_counter() - started)
    return result


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("kol_id")
    ap.add_argument("text")
    ap.add_argument("-o", "--out", default=None)
    args = ap.parse_args()
    dst = Path(args.out or (REPO / "renders" / "stream.wav"))
    dst.parent.mkdir(parents=True, exist_ok=True)
    speak_streaming(args.kol_id, args.text, dst,
                    on_chunk=lambda i, n, t: print(f"  chunk {i}/{n} playing at {t:.1f}s"),
                    on_done=lambda p, t: print(f"  done in {t:.1f}s -> {p}"))
