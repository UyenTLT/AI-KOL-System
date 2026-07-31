"""Robust ffmpeg/ffprobe discovery + thin wrappers.

`shutil.which` alone is not enough on Windows: winget/scoop/choco write the binary
into the *persisted* user PATH, so any shell started before the install (or any
subprocess inheriting that stale environment) will not see it. We fall back to the
known install roots before giving up.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

_CACHE: dict[str, str] = {}

# Known install roots, in probe order. Globs are resolved lazily.
_FALLBACK_GLOBS = (
    r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg*\**\bin",
    r"%LOCALAPPDATA%\Microsoft\WinGet\Links",
    r"%USERPROFILE%\scoop\shims",
    r"%ProgramData%\chocolatey\bin",
    r"C:\ffmpeg\bin",
)


def _candidates(name: str):
    exe = f"{name}.exe" if os.name == "nt" else name

    env_override = os.environ.get("FFMPEG_BIN")
    if env_override:
        yield Path(env_override) / exe

    found = shutil.which(name)
    if found:
        yield Path(found)

    for pattern in _FALLBACK_GLOBS:
        expanded = os.path.expandvars(pattern)
        if "%" in expanded:  # unexpanded var -> not this platform
            continue
        head, _, tail = expanded.partition("*")
        base = Path(head).parent if not Path(head).is_dir() else Path(head)
        if not base.is_dir():
            continue
        if "*" in expanded:
            for match in base.glob(Path(expanded).relative_to(base).as_posix()):
                yield match / exe
        else:
            yield Path(expanded) / exe


def resolve(name: str) -> str:
    """Return an absolute path to `ffmpeg`/`ffprobe`, or raise with a fix hint."""
    if name in _CACHE:
        return _CACHE[name]
    for cand in _candidates(name):
        if cand.is_file():
            _CACHE[name] = str(cand)
            return _CACHE[name]
    raise FileNotFoundError(
        f"{name} not found. Install it (`winget install Gyan.FFmpeg`), then either open a "
        f"new shell or set FFMPEG_BIN=<dir containing {name}>."
    )


def run(args: list[str], *, desc: str = "ffmpeg") -> subprocess.CompletedProcess:
    """Run an ffmpeg-family command, raising with stderr attached on failure."""
    proc = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()[-12:]
        raise RuntimeError(f"{desc} failed (exit {proc.returncode}):\n" + "\n".join(tail))
    return proc


def duration_seconds(path: Path) -> float:
    """Media duration via ffprobe, in seconds."""
    proc = run(
        [
            resolve("ffprobe"), "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        desc="ffprobe",
    )
    return float(proc.stdout.strip())


def to_mono_wav(src: Path, dst: Path, sample_rate: int = 32000, loudnorm: bool = True) -> Path:
    """Decode any input to mono WAV at `sample_rate`, optionally EBU R128 normalized.

    Consistent loudness across source episodes materially improves GPT-SoVITS
    training stability, so `loudnorm` is on by default.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    args = [resolve("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error", "-i", str(src)]
    if loudnorm:
        args += ["-af", "loudnorm=I=-23:TP=-2:LRA=11"]
    args += ["-ac", "1", "-ar", str(sample_rate), "-c:a", "pcm_s16le", str(dst)]
    run(args, desc="ffmpeg decode")
    return dst
