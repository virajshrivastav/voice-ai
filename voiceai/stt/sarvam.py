"""Sarvam Saaras STT.

Endpoint shape read from docs.sarvam.ai on 2026-09-06:
    POST https://api.sarvam.ai/speech-to-text
    header:    api-subscription-key
    multipart: file, model, mode, language_code, with_timestamps
    resp:      {request_id, transcript, language_code, language_probability, timestamps}

Why this vendor for ears even though its mouth is gated: Saaras is explicitly tuned
for 8 kHz Indian telephony, which is the audio we actually get, and it reports ~19%
WER on IndicVoices where general-purpose models are well above that on Indic
languages.

`mode="codemix"` is worth trying early. Voters in Marathwada switch between Marathi,
Hindi and English inside one sentence, and a monolingual decode of that is a good way
to manufacture the exact failure this project cannot afford: a confident wrong
transcript that becomes a recorded grievance.
"""

from __future__ import annotations

import time
from pathlib import Path

import httpx

from .base import STTProvider, Transcript

ENDPOINT = "https://api.sarvam.ai/speech-to-text"

# ₹30/hour, billed per second (docs.sarvam.ai pricing, 2026-09-06). Diarisation is ₹45/hr.
INR_PER_SECOND = 30.0 / 3600


class SarvamSTT(STTProvider):
    name = "sarvam"

    def __init__(
        self,
        api_key: str,
        model: str = "saaras:v3",
        mode: str | None = None,
        timeout: float = 30.0,
    ):
        if not api_key:
            raise ValueError("SARVAM_API_KEY is empty")
        self._client = httpx.Client(timeout=timeout, headers={"api-subscription-key": api_key})
        self.model = model
        self.mode = mode

    def transcribe(self, audio_path: Path, lang: str) -> Transcript:
        start = time.perf_counter()
        data: dict[str, str] = {"model": self.model, "language_code": lang}
        if self.mode:
            data["mode"] = self.mode
        with audio_path.open("rb") as fh:
            resp = self._client.post(
                ENDPOINT, data=data, files={"file": (audio_path.name, fh, "audio/wav")}
            )
        resp.raise_for_status()
        payload = resp.json()
        return Transcript(
            text=payload.get("transcript", ""),
            language_code=payload.get("language_code"),
            # Sarvam returns language_probability, not a transcript confidence. Treating
            # it as confidence is a stand-in, not the real thing — flagged so nobody
            # mistakes it for a calibrated score.
            confidence=float(payload.get("language_probability") or 1.0),
            provider=self.name,
            latency_ms=(time.perf_counter() - start) * 1000.0,
            raw=payload,
        )

    def cost_inr(self, seconds: float) -> float:
        return seconds * INR_PER_SECOND
