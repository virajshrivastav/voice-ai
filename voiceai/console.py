"""Make stdout survive Devanagari on Windows.

Every CLI in this repo prints Marathi and Hindi. On Windows the default console
encoding is cp1252, so the first `print()` of a script line dies with
UnicodeEncodeError — the code is fine, the terminal is not. Call `setup()` at the top
of every entry point.
"""

from __future__ import annotations

import sys


def setup() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            # Already UTF-8, or a stream that does not support reconfigure (a pipe in
            # some harnesses). Not worth failing a run over.
            pass
