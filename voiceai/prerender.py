"""Pre-render cache.

Roughly 90% of a call is text that was written and approved in advance. Synthesising
it live is the single most wasteful thing this system could do: it burns TTS spend on
every one of ~1.5 lakh connected calls, and it puts a network round trip in front of
every turn.

So: at startup, every sentence the guard allows is synthesised once per voice and
written to disk. At call time those turns play from a file. That collapses TTS cost
towards zero and turn latency towards disk-read time, and it is also what makes the
script pre-certifiable — the audio an MCMC would approve is byte-identical to the
audio a voter hears.

Cache key is (voice_id, sha1(text), format), per CLAUDE.md.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from .config import CACHE_DIR
from .guard import SpeechGuard
from .script import normalise
from .tts.base import TTSProvider


def cache_key(text: str) -> str:
    return hashlib.sha1(normalise(text).encode("utf-8")).hexdigest()


@dataclass
class WarmStats:
    voice_id: str
    total: int = 0
    synthesised: int = 0
    reused: int = 0
    failed: int = 0
    chars: int = 0
    cost_inr: float = 0.0
    seconds: float = 0.0
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"{self.voice_id}: {self.synthesised} synthesised, {self.reused} cached, "
            f"{self.failed} failed · {self.chars} chars · ₹{self.cost_inr:.2f} · "
            f"{self.seconds:.1f}s"
        )


class PrerenderCache:
    def __init__(self, voice_id: str, fmt: str = "wav", root: Path | None = None):
        if not voice_id:
            raise ValueError("voice_id is required — the cache is per voice")
        self.voice_id = voice_id
        self.fmt = fmt
        self.root = (root or CACHE_DIR) / voice_id
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, text: str) -> Path:
        return self.root / f"{cache_key(text)}.{self.fmt}"

    def has(self, text: str) -> bool:
        p = self.path_for(text)
        return p.exists() and p.stat().st_size > 0

    def get(self, text: str) -> bytes | None:
        p = self.path_for(text)
        return p.read_bytes() if self.has(text) else None

    def put(self, text: str, audio: bytes) -> Path:
        p = self.path_for(text)
        p.write_bytes(audio)
        return p

    def warm(
        self,
        guard: SpeechGuard,
        tts: TTSProvider,
        lang: str,
        *,
        sample_rate: int = 24000,
        force: bool = False,
        on_progress=None,
    ) -> WarmStats:
        """Synthesise everything the guard allows. Safe to re-run; skips what exists."""
        stats = WarmStats(voice_id=self.voice_id)
        started = time.perf_counter()
        texts = guard.allowed_texts()
        stats.total = len(texts)

        for i, text in enumerate(texts, 1):
            if on_progress:
                on_progress(i, stats.total, text)
            if not force and self.has(text):
                stats.reused += 1
                continue
            try:
                result = tts.synth(text, self.voice_id, lang, sample_rate=sample_rate)
            except Exception as exc:  # noqa: BLE001 - one bad turn must not stop the warm
                stats.failed += 1
                stats.errors.append(f"{guard.source_of(text)}: {exc}")
                continue
            self.put(text, result.audio)
            stats.synthesised += 1
            stats.chars += result.chars
            stats.cost_inr += result.cost_inr

        stats.seconds = time.perf_counter() - started
        self._write_index(guard, stats)
        return stats

    def _write_index(self, guard: SpeechGuard, stats: WarmStats) -> None:
        """Human-readable map from cache file back to the sentence and its source.

        Without this a cache directory is 40 opaque hashes, and nobody can answer
        "which file is the disclosure line?" during an audit.
        """
        index = {
            "voice_id": self.voice_id,
            "lang": guard.lang,
            "format": self.fmt,
            "manifest_sha256": guard.manifest()["sha256"],
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "stats": {
                "total": stats.total,
                "synthesised": stats.synthesised,
                "reused": stats.reused,
                "failed": stats.failed,
            },
            "files": [
                {
                    "file": f"{cache_key(item.text)}.{self.fmt}",
                    "source": item.source,
                    "text": item.text,
                    "cached": self.has(item.text),
                }
                for item in guard.items
            ],
        }
        (self.root / "index.json").write_text(
            json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def coverage(self, guard: SpeechGuard) -> tuple[int, int]:
        """(cached, total). A call must not start unless these are equal."""
        texts = guard.allowed_texts()
        return sum(1 for t in texts if self.has(t)), len(texts)
