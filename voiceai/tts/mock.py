"""Offline TTS provider.

Generates a valid WAV of a plausible duration for the text, with a faint tone so the
file is not silent and pipeline bugs are audible. No network, no key, deterministic —
this is what makes the whole system testable before any vendor account exists.
"""

from __future__ import annotations

import hashlib
import math
import struct
import time
from pathlib import Path

from .base import Capability, SynthResult, TTSProvider

# Devanagari speaking rate for a phone call, from the ~500 chars/min figure in
# docs/00_CONTEXT.md §4.
CHARS_PER_SECOND = 500 / 60


def _wav(samples: list[int], sample_rate: int) -> bytes:
    data = b"".join(struct.pack("<h", s) for s in samples)
    header = b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
    header += b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16)
    header += b"data" + struct.pack("<I", len(data))
    return header + data


class MockTTS(TTSProvider):
    name = "mock"
    capability = Capability(
        marathi="yes",
        cloning="self-serve",
        streaming=False,
        note="Not real speech. Timing and byte sizes are realistic; audio is a tone.",
    )

    def __init__(self, latency_ms: float = 0.0):
        self._latency_ms = latency_ms

    def synth(self, text: str, voice_id: str, lang: str, sample_rate: int = 24000) -> SynthResult:
        start = time.perf_counter()
        if self._latency_ms:
            time.sleep(self._latency_ms / 1000.0)

        seconds = max(0.35, len(text) / CHARS_PER_SECOND)
        # Pitch keyed on voice_id so two "voices" are distinguishable by ear.
        seed = int(hashlib.sha1(voice_id.encode()).hexdigest()[:6], 16)
        freq = 110 + (seed % 120)
        n = int(seconds * sample_rate)
        samples = [int(3000 * math.sin(2 * math.pi * freq * i / sample_rate)) for i in range(n)]

        return SynthResult(
            audio=_wav(samples, sample_rate),
            sample_rate=sample_rate,
            fmt="wav",
            chars=len(text),
            provider=self.name,
            voice_id=voice_id,
            ttfb_ms=self._latency_ms or 1.0,
            total_ms=self._elapsed_ms(start),
            cost_inr=0.0,
        )

    def clone(self, sample_path: Path, display_name: str, transcript: str | None = None) -> str:
        digest = hashlib.sha1(f"{sample_path.name}:{display_name}".encode()).hexdigest()[:10]
        return f"mock_{digest}"
