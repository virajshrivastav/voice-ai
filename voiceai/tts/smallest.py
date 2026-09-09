"""Smallest.ai Lightning v3.1 TTS + instant voice clone.

Endpoint shapes re-read from docs.smallest.ai on 2026-09-09 (the 2026-09-06 version of
this file pointed at `/waves/v1/lightning-v3.1/get_speech` and a `lightning-large`
clone host; both are gone — the model is now a body field):

    synth: POST https://api.smallest.ai/waves/v1/tts
           headers: Authorization: Bearer <key>, Accept: audio/wav (required)
           body:    {text, voice_id, model: lightning_v3.1, language, sample_rate,
                     output_format: wav|pcm|mp3|ulaw|alaw, speed}
           resp:    audio bytes
    clone: POST https://api.smallest.ai/waves/v1/voice-cloning   (multipart)
           fields:  displayName, file (<=5 MB), language, model: lightning-v3.1
           resp:    {message, data: {voiceId, status, modelIds?, samples[]}}

Language codes are ISO 639-1 (`mr`, `hi`), not BCP-47, and the clone's `language`
should match the TTS request's `language` or the vendor warns of silent mismatches.
Note the model spelling differs between the two calls (`lightning_v3.1` vs
`lightning-v3.1`) — that is the vendor's doing, not a typo here.

STATUS: written from the live docs; not yet executed against the endpoint with a key.
The first successful synth is the verification.
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

import httpx

from ..audio import prepare_reference_clip
from .base import Capability, SynthResult, TTSProvider

SYNTH_URL = "https://api.smallest.ai/waves/v1/tts"
CLONE_URL = "https://api.smallest.ai/waves/v1/voice-cloning"
TTS_MODEL = "lightning_v3.1"
CLONE_MODEL = "lightning-v3.1"

# Pricing page 2026-09-09: ~$0.175 per 10K characters on Lightning v3.1 at ₹84/USD.
INR_PER_CHAR = (0.175 * 84) / 10_000

# Vendor caps the clone upload at 5 MB; 45 s of 16 kHz mono PCM is ~1.4 MB and is
# well past the 5-15 s they say they need.
CLONE_CLIP_SECONDS = 45.0


def to_iso639(lang: str) -> str:
    """`mr-IN` -> `mr`. Smallest speaks ISO 639-1."""
    return lang.split("-")[0].lower()


class SmallestTTS(TTSProvider):
    name = "smallest"
    capability = Capability(
        marathi="yes",
        cloning="self-serve",
        streaming=True,
        note=(
            "Lightning v3.1: 10 Indic languages incl. Marathi (9 catalog voices), instant "
            "clone from 5-15 s via API/console, ~200 ms TTFB. Prohibited Use Policy bans "
            "candidate impersonation and political advertising without prior written "
            "approval — get that approval in writing before a pilot."
        ),
    )

    def __init__(
        self,
        api_key: str,
        timeout: float = 60.0,
        synth_url: str = SYNTH_URL,
        clone_url: str = CLONE_URL,
        model: str = TTS_MODEL,
    ):
        if not api_key:
            raise ValueError("SMALLEST_API_KEY is empty")
        self._client = httpx.Client(
            timeout=timeout, headers={"Authorization": f"Bearer {api_key}"}
        )
        self._synth_url = synth_url
        self._clone_url = clone_url
        self._model = model

    def synth(self, text: str, voice_id: str, lang: str, sample_rate: int = 24000) -> SynthResult:
        if sample_rate not in (8000, 16000, 24000, 44100):
            raise ValueError(f"Smallest supports 8000/16000/24000/44100 Hz, not {sample_rate}")
        start = time.perf_counter()
        resp = self._client.post(
            self._synth_url,
            json={
                "text": text,
                "voice_id": voice_id,
                "model": self._model,
                "language": to_iso639(lang),
                "sample_rate": sample_rate,
                "output_format": "wav",
            },
            headers={"Content-Type": "application/json", "Accept": "audio/wav"},
        )
        ttfb = self._elapsed_ms(start)
        resp.raise_for_status()
        if not resp.content or resp.headers.get("content-type", "").startswith("application/json"):
            raise RuntimeError(f"Smallest returned no audio: {resp.text[:200]}")
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

    def clone(
        self,
        sample_path: Path,
        display_name: str,
        transcript: str | None = None,
        *,
        lang: str = "mr-IN",
    ) -> str:
        """Instant clone. Cuts a ≤45 s, 16 kHz mono clip from the sample first so the
        upload stays under the vendor's 5 MB cap. `transcript` is unused — Smallest does
        not need the reference text."""
        with tempfile.TemporaryDirectory() as tmp:
            clip = prepare_reference_clip(
                sample_path, Path(tmp) / "ref.wav", seconds=CLONE_CLIP_SECONDS
            )
            with clip.open("rb") as fh:
                resp = self._client.post(
                    self._clone_url,
                    data={
                        "displayName": display_name,
                        "language": to_iso639(lang),
                        "model": CLONE_MODEL,
                        "accent": "indian",
                    },
                    files={"file": ("reference.wav", fh, "audio/wav")},
                )
        resp.raise_for_status()
        payload = resp.json()
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        for key in ("voiceId", "voice_id", "id"):
            if data.get(key):
                return str(data[key])
        raise RuntimeError(f"could not find a voice id in Smallest clone response: {payload}")

    def cost_inr(self, chars: int) -> float:
        return chars * INR_PER_CHAR
