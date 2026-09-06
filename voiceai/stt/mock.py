"""Offline STT.

Replays a scripted list of voter utterances instead of listening. That is what lets
`stage1/dryrun.py` walk a whole conversation, and the tests assert on real transitions,
with no audio and no keys.

`error_rate` deliberately corrupts transcripts so the clarification and low-confidence
paths get exercised — at ~19% WER those paths are not edge cases, they are the normal
operating mode.
"""

from __future__ import annotations

import random
from pathlib import Path

from .base import STTProvider, Transcript


class MockSTT(STTProvider):
    name = "mock"

    def __init__(
        self,
        utterances: list[str] | None = None,
        confidence: float = 0.9,
        error_rate: float = 0.0,
        seed: int = 0,
    ):
        self._utterances = list(utterances or [])
        self._confidence = confidence
        self._error_rate = error_rate
        self._rng = random.Random(seed)
        self._i = 0

    def next_utterance(self) -> Transcript:
        """Used by the dry-run driver, which has no audio files to point at."""
        if self._i >= len(self._utterances):
            return Transcript(text="", confidence=0.0, provider=self.name)
        text = self._utterances[self._i]
        self._i += 1
        confidence = self._confidence
        if self._error_rate and self._rng.random() < self._error_rate:
            text = self._corrupt(text)
            confidence = min(confidence, 0.3)
        return Transcript(text=text, confidence=confidence, provider=self.name)

    def transcribe(self, audio_path: Path, lang: str) -> Transcript:
        return self.next_utterance()

    def _corrupt(self, text: str) -> str:
        words = text.split()
        if len(words) <= 1:
            return ""
        drop = self._rng.randrange(len(words))
        return " ".join(w for i, w in enumerate(words) if i != drop)
