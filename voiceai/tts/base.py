"""TTS provider interface.

Providers are swapped by config so Stage 0 can score them against each other and
Stage 1/2 can fail over without touching the conversation code.

HONESTY NOTE: the vendor adapters in this package were written from published API
docs and have not been executed against a live endpoint — there are no keys in this
repo yet. Treat the first successful call to each as the real verification, and see
`capability` on each provider for what is documented vs assumed.
"""

from __future__ import annotations

import abc
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SynthResult:
    audio: bytes
    sample_rate: int
    fmt: str
    chars: int
    provider: str
    voice_id: str
    ttfb_ms: float | None = None
    total_ms: float = 0.0
    cost_inr: float = 0.0


@dataclass(frozen=True)
class Capability:
    """What we actually know about a provider, and how we know it."""

    marathi: str  # "yes" | "no" | "unconfirmed"
    cloning: str  # "self-serve" | "enterprise" | "none" | "unconfirmed"
    streaming: bool
    note: str = ""


class TTSProvider(abc.ABC):
    name: str = "base"
    capability: Capability

    @abc.abstractmethod
    def synth(self, text: str, voice_id: str, lang: str, sample_rate: int = 24000) -> SynthResult:
        ...

    def clone(self, sample_path: Path, display_name: str, transcript: str | None = None) -> str:
        raise NotImplementedError(
            f"{self.name} does not expose voice cloning through this adapter "
            f"(cloning status: {self.capability.cloning})"
        )

    def cost_inr(self, chars: int) -> float:
        """Rupees for synthesising `chars` characters. 0.0 means free or unknown."""
        return 0.0

    @staticmethod
    def _elapsed_ms(start: float) -> float:
        return (time.perf_counter() - start) * 1000.0
