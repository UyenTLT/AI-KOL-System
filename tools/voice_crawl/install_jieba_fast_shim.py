#!/usr/bin/env python3
"""Install a `jieba_fast` shim that forwards to plain `jieba`.

Why: GPT-SoVITS imports `jieba_fast` unconditionally in GPT_SoVITS/text/chinese.py,
chinese2.py and tone_sandhi.py with no fallback -- so Chinese text processing dies
without it. `jieba_fast` is a C-optimised drop-in for `jieba` with the same public
API, and building it on Windows needs the full MSVC toolchain (~6 GB) for what is
purely a speed optimisation.

This creates a small package that re-exports `jieba`, so GPT-SoVITS imports succeed
and ZH synthesis works. The only cost is slower word segmentation, which is
negligible next to model inference.

Run against the GPT-SoVITS venv:
    GPT-SoVITS\\.venv\\Scripts\\python.exe tools\\voice_crawl\\install_jieba_fast_shim.py
"""
from __future__ import annotations

import sys
import sysconfig
from pathlib import Path

INIT = '''"""Shim: forward `jieba_fast` to `jieba`.

Installed by tools/voice_crawl/install_jieba_fast_shim.py because jieba_fast is a
C extension that cannot build without MSVC on Windows. jieba exposes the same
public API, so GPT-SoVITS behaves identically (segmentation is just slower).
"""
import sys as _sys

import jieba as _jieba
from jieba import *  # noqa: F401,F403

# Names GPT-SoVITS touches directly; `from x import *` skips some of these.
from jieba import (  # noqa: F401
    setLogLevel, cut, lcut, cut_for_search, lcut_for_search,
    load_userdict, add_word, del_word, suggest_freq, Tokenizer, dt,
)

import jieba.posseg as _posseg
import jieba.analyse as _analyse

posseg = _posseg
analyse = _analyse

# Make `import jieba_fast.posseg as psg` resolve without a real submodule file.
_sys.modules[__name__ + ".posseg"] = _posseg
_sys.modules[__name__ + ".analyse"] = _analyse

__all__ = [n for n in dir(_jieba) if not n.startswith("_")]
'''

POSSEG = '''"""Shim submodule: `jieba_fast.posseg` -> `jieba.posseg`."""
from jieba.posseg import *  # noqa: F401,F403
from jieba.posseg import cut, lcut, POSTokenizer, dt  # noqa: F401
'''

ANALYSE = '''"""Shim submodule: `jieba_fast.analyse` -> `jieba.analyse`."""
from jieba.analyse import *  # noqa: F401,F403
'''


def main() -> int:
    try:
        import jieba  # noqa: F401
    except ImportError:
        print("ERROR: plain `jieba` is not installed in this interpreter.\n"
              "Install requirements first, then re-run this script.", file=sys.stderr)
        return 1

    site = Path(sysconfig.get_paths()["purelib"])
    pkg = site / "jieba_fast"

    try:
        import jieba_fast  # noqa: F401
        real = Path(jieba_fast.__file__).parent
        if not (real / ".shim").exists():
            print(f"A real jieba_fast is already installed at {real}; leaving it alone.")
            return 0
    except ImportError:
        pass

    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text(INIT, encoding="utf-8")
    (pkg / "posseg.py").write_text(POSSEG, encoding="utf-8")
    (pkg / "analyse.py").write_text(ANALYSE, encoding="utf-8")
    (pkg / ".shim").write_text("forwards to jieba\n", encoding="utf-8")
    print(f"installed jieba_fast shim -> {pkg}")

    # Prove it works the way GPT-SoVITS actually uses it.
    import importlib
    for mod in ("jieba_fast", "jieba_fast.posseg", "jieba_fast.analyse"):
        importlib.import_module(mod)
    import jieba_fast
    import jieba_fast.posseg as psg
    jieba_fast.setLogLevel(60)
    words = list(jieba_fast.cut("今天天氣真的很好，我決定出門走走。"))
    tagged = [(w.word, w.flag) for w in psg.cut("這罐精華我用了三週")]
    print("  jieba_fast.cut     ->", "/".join(words))
    print("  jieba_fast.posseg  ->", tagged[:5])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
