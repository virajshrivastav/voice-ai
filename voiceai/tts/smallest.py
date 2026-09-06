"""Smallest.ai Lightning v3.1 TTS + instant voice clone.

This is the only vendor in the stack that documents SELF-SERVE Marathi voice cloning,
which is why Stage 0 is built to run on it first rather than waiting on Sarvam.

Endpoint shapes read from docs.smallest.ai / waves-docs.smallest.ai on 2026-09-06:
    synth: POST https://api.smallest.ai/waves/v1/lightning-v3.1/get_speech
           header: Authorization: Bearer <key>
           body:   {text, voice_id, sample_rate, output_format}
           resp:   raw audio bytes
    clone: POST https://waves-api.smallest.ai/api/v1/lightning-large/add_voice
           header: Authorization: Bearer <key>
           multipart: displayName, file
           resp:   JSON containing a voice id

UNVERIFIED: the documented add_voice path sits on a different host and still says
`lightning-large`. If Smallest has since moved cloning under a v3.1 path, override it
with SMALLEST_CLONE_URL rather than editing this file.
"""

from __future__ import annotations

import time
from pathlib import Path

import httpx

from .base import Capability, SynthResult, TTSProvider

SYNTH_URL = "https://api.smallest.ai/waves/v1/lightning-v3.1/get_speech"
CLONE_URL = "https://waves-api.smallest.ai/api/v1/lightning-large/add_voice"

# ~$14.5 per 1M characters at ₹84/USD (docs/01_EVIDENCE_CHECK.md #11 — secondary
# source, re-confirm on the pricing page at signup).
INR_PER_CHAR = (14.5 * 84) / 1_000_000


class SmallestTTS(TTSProvider):
    name = "smallest"
    capability = Capability(
        marathi="yes",
        cloning="self-serve",
        streaming=True,
        note=(
            "9 Marathi voices; instant clone from 5-15s of clean speech via API and "
            "console; ~200ms TTFB in-region, 500-800ms from a distant client. "
            "Cloning requires explicit consent under their ToS."
        ),
    )

    def __init__(
        self,
        api_key: str,
        timeout: float = 30.0,
        synth_url: str = SYNTH_URL,
        clone_url: str = CLONE_URL,
    ):
        if not api_key:
            raise ValueError("SMALLEST_API_KEY is empty")
        self._client = httpx.Client(
            timeout=timeout, headers={"Authorization": f"Bearer {api_key}"}
        )
        self._synth_url = synth_url
        self._clone_url = clone_url

    def synth(self, text: str, voice_id: str, lang: str, sample_rate: int = 24000) -> SynthResult:
        start = time.perf_counter()
        resp = self._client.post(
            self._synth_url,
            json={
                "text": text,
                "voice_id": voice_id,
                "sample_rate": sample_rate,
                "output_format": "wav",
            },
            headers={"Content-Type": "application/json"},
        )
        ttfb = self._elapsed_ms(start)
        resp.raise_for_status()
        return SynthResult(
            audio=resp.content,
            sample_rate=sample_rate,
            fmt="wav",
            chars=len(text),
            provider=self.name,
            voice_id=voice_id,
            ttfb_ms=ttfb,
            total_ms=self._elapsed_ms(start),
            cost_inr=self.cost_inr(len(text)),
        )

    def clone(self, sample_path: Path, display_name: str, transcript: str | None = None) -> str:
        """Instant clone. `transcript` is unused here — Smallest does not require the
        reference transcript that IndicF5-style models do."""
        with sample_path.open("rb") as fh:
            resp = self._client.post(
                self._clone_url,
                data={"displayName": display_name},
                files={"file": (sample_path.name, fh, "audio/wav")},
            )
        resp.raise_for_status()
        payload = resp.json()
        for key in ("voiceId", "voice_id", "id"):
            if key in payload:
                return str(payload[key])
            if isinstance(payload.get("data"), dict) and key in payload["data"]:
                return str(payload["data"][key])
        raise RuntimeError(f"could not find a voice id in Smallest clone response: {payload}")

    def cost_inr(self, chars: int) -> float:
        return chars * INR_PER_CHAR
