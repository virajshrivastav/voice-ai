"""Sarvam Bulbul TTS.

Endpoint shape read from docs.sarvam.ai on 2026-09-06:
    POST https://api.sarvam.ai/text-to-speech
    header: api-subscription-key
    body:   {text, language_code, model, speaker, speech_sample_rate, output_audio_codec}
    resp:   {request_id, audios: [base64]}

IMPORTANT — the `speaker` field is an enum of ~44 catalog voices. There is no
voice-id or clone parameter in the public API, which is the concrete evidence behind
the finding in docs/01_EVIDENCE_CHECK.md that Sarvam cloning is enterprise-gated.
`clone()` therefore raises with instructions rather than pretending.

Sarvam is still the strongest STT for 8 kHz Indic telephony (see voiceai/stt/sarvam.py),
so the expected shape of the system is Sarvam ears + someone else's mouth, until and
unless Sarvam grants clone access.
"""

from __future__ import annotations

import base64
import time
from pathlib import Path

import httpx

from .base import Capability, SynthResult, TTSProvider

ENDPOINT = "https://api.sarvam.ai/text-to-speech"

SUPPORTED_LANGS = {
    "bn-IN", "en-IN", "gu-IN", "hi-IN", "kn-IN", "ml-IN",
    "mr-IN", "od-IN", "pa-IN", "ta-IN", "te-IN",
}

# ₹30 per 10k characters for bulbul:v3 (sarvam.ai/api-pricing, read 2026-09-06).
INR_PER_CHAR = 30.0 / 10_000


class SarvamTTS(TTSProvider):
    name = "sarvam"
    capability = Capability(
        marathi="yes",
        cloning="enterprise",
        streaming=True,
        note=(
            "Catalog voices only through the public API. Cloning is consent-based and "
            "gated behind enterprise onboarding; no published price as of 2026-09-06."
        ),
    )

    def __init__(self, api_key: str, model: str = "bulbul:v3", timeout: float = 30.0):
        if not api_key:
            raise ValueError("SARVAM_API_KEY is empty")
        self._client = httpx.Client(
            timeout=timeout,
            headers={"api-subscription-key": api_key, "Content-Type": "application/json"},
        )
        self.model = model

    def synth(self, text: str, voice_id: str, lang: str, sample_rate: int = 24000) -> SynthResult:
        if lang not in SUPPORTED_LANGS:
            raise ValueError(f"sarvam does not list {lang}; supported: {sorted(SUPPORTED_LANGS)}")
        start = time.perf_counter()
        resp = self._client.post(
            ENDPOINT,
            json={
                "text": text,
                "language_code": lang,
                "model": self.model,
                # `voice_id` here is a catalog speaker name, not a clone id.
                "speaker": voice_id,
                "speech_sample_rate": sample_rate,
                "output_audio_codec": "wav",
            },
        )
        ttfb = self._elapsed_ms(start)
        resp.raise_for_status()
        payload = resp.json()
        audio = base64.b64decode(payload["audios"][0])
        return SynthResult(
            audio=audio,
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
        raise NotImplementedError(
            "Sarvam voice cloning is not exposed in the public API (the TTS body takes a "
            "`speaker` enum of catalog voices). It is consent-based and enterprise-gated: "
            "email Sarvam using the script in docs/00_CONTEXT.md §11 and add the adapter "
            "once they grant access and document the endpoint."
        )

    def cost_inr(self, chars: int) -> float:
        return chars * INR_PER_CHAR
