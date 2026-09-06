"""STT provider interface.

This is the part of the system most likely to fail in the field. Best-in-class Indic
telephony ASR sits around 19% WER (Sarvam Saaras v3 on IndicVoices); open-source Indic
models are 22-30% on telephony audio. Roughly one word in five is wrong on a good day,
before you add a Marathwada accent, a tractor in the background, and a 2G handset.

Two consequences the whole design leans on:
  * `confidence` is load-bearing. A low-confidence transcript must trigger a
    clarification, not a recorded answer.
  * The agent must never repeat the voter's words back in the MLA's voice. If it
    mishears "पाणी येत नाही" and says something confident about it, that is a wrong
    statement in a real politician's voice. The answer bank exists so it never has to.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Transcript:
    text: str
    language_code: str | None = None
    confidence: float = 1.0
    provider: str = ""
    latency_ms: float = 0.0
    raw: dict | None = None

    @property
    def is_low_confidence(self) -> bool:
        return self.confidence < 0.4


class STTProvider(abc.ABC):
    name: str = "base"

    @abc.abstractmethod
    def transcribe(self, audio_path: Path, lang: str) -> Transcript:
        ...

    def cost_inr(self, seconds: float) -> float:
        return 0.0
