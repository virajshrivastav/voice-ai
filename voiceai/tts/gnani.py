"""Gnani.ai (Vachana) TTS + zero-shot voice clone.

Endpoint shapes read from docs.gnani.ai on 2026-09-09 (their API went public with
self-serve keys at app.gnani.ai/voice; the 2026-09-06 docs said "no public reference"):

    embed: POST https://api.vachana.ai/api/v1/tts/voice-clone/embeddings   (multipart)
           header: X-API-Key-ID: <key>;  field: audio_file (5-30 s of clean speech)
           resp:   {success, data: {voice_clone_embedding: {embedding, shape, dtype}}}
    clone synth: POST https://api.vachana.ai/api/v1/tts/inference
           body:   {text, model: "vachana-vc-v1", audio_config{...}, speaker_embedding{...}}
           resp:   audio bytes in the container requested (wav | mulaw | alaw | mp3 | raw)
    catalog synth: same URL, body {text, voice: <name>, model: "timbre-v2.5",
           language: mr-IN|hi-IN|auto, audio_config{...}}

Gnani has no server-side "voice id" for clones: the clone *is* the embedding, and you
send it with every request. To keep the `voice_id` abstraction the rest of the code
uses, `clone()` stores the embedding on disk and returns a handle (`gnani-emb-<hash>`)
that `synth()` resolves. Anything else passed as `voice_id` is treated as a Timbre
catalog voice name (e.g. "Nalini").

Telephony note: `container: mulaw` forces 8 kHz G.711 straight from the vendor, which
is the true wire format — useful once the transport exists. The bake-off asks for wav
at 24 kHz and degrades it itself so every vendor is judged through the same pipe.

UNVERIFIED as of writing: price (not published), Marathi quality of the clone model
specifically (Timbre lists mr-IN; the VC endpoint has no language field and infers it
from the script), and any political-use clause in their terms.

STATUS: written from the live docs; not yet executed against the endpoint with a key.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import time
from pathlib import Path

import httpx

from ..audio import prepare_reference_clip
from ..config import CACHE_DIR
from .base import Capability, SynthResult, TTSProvider

BASE_URL = "https://api.vachana.ai"
EMBED_PATH = "/api/v1/tts/voice-clone/embeddings"
SYNTH_PATH = "/api/v1/tts/inference"
CLONE_MODEL = "vachana-vc-v1"
CATALOG_MODEL = "timbre-v2.5"
HANDLE_PREFIX = "gnani-emb-"

# Their docs ask for 5-30 s of reference audio. 25 s leaves margin under the cap.
CLONE_CLIP_SECONDS = 25.0

VOICES_DIR = CACHE_DIR / "voices" / "gnani"


class GnaniTTS(TTSProvider):
    name = "gnani"
    capability = Capability(
        marathi="yes",
        cloning="self-serve",
        streaming=True,
        note=(
            "Public API since 2026 with self-serve keys (app.gnani.ai/voice). Zero-shot "
            "clone from 5-30 s -> speaker embedding, then REST/SSE/WebSocket synthesis; "
            "native 8 kHz mu-law output; official Pipecat + LiveKit plugins. IndiaAI "
            "Mission sovereign-model company. Price unpublished; clone quality in Marathi "
            "unverified until the bake-off."
        ),
    )

    def __init__(
        self,
        api_key: str,
        timeout: float = 60.0,
        base_url: str = BASE_URL,
        voices_dir: Path | None = None,
    ):
        if not api_key:
            raise ValueError("GNANI_API_KEY is empty")
        self._client = httpx.Client(
            base_url=base_url, timeout=timeout, headers={"X-API-Key-ID": api_key}
        )
        self._voices_dir = voices_dir or VOICES_DIR

    # -- voice handles -------------------------------------------------------

    def _handle_path(self, voice_id: str) -> Path:
        return self._voices_dir / f"{voice_id}.json"

    def is_clone_handle(self, voice_id: str) -> bool:
        return voice_id.startswith(HANDLE_PREFIX)

    def load_embedding(self, voice_id: str) -> dict:
        path = self._handle_path(voice_id)
        if not path.exists():
            raise FileNotFoundError(
                f"no stored Gnani embedding for {voice_id!r} at {path}. Run clone() on "
                f"this machine first — Gnani clones live as local embedding files, not "
                f"as server-side voice ids."
            )
        return json.loads(path.read_text(encoding="utf-8"))["speaker_embedding"]

    # -- API -----------------------------------------------------------------

    def clone(
        self,
        sample_path: Path,
        display_name: str,
        transcript: str | None = None,
        *,
        lang: str = "mr-IN",
    ) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            clip = prepare_reference_clip(
                sample_path, Path(tmp) / "ref.wav", seconds=CLONE_CLIP_SECONDS
            )
            with clip.open("rb") as fh:
                resp = self._client.post(
                    EMBED_PATH, files={"audio_file": ("reference.wav", fh, "audio/wav")}
                )
        resp.raise_for_status()
        payload = resp.json()
        emb = (payload.get("data") or {}).get("voice_clone_embedding")
        if not emb or "embedding" not in emb:
            raise RuntimeError(f"unexpected Gnani embeddings response: {str(payload)[:300]}")

        digest = hashlib.sha1(str(emb["embedding"]).encode("utf-8")).hexdigest()[:12]
        voice_id = f"{HANDLE_PREFIX}{digest}"
        path = self._handle_path(voice_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "display_name": display_name,
                    "lang": lang,
                    "source_sample": str(sample_path),
                    "speaker_embedding": {
                        "embedding": emb["embedding"],
                        "shape": emb.get("shape", [1, 768]),
                        "dtype": emb.get("dtype", "torch.bfloat16"),
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return voice_id

    def synth(
        self,
        text: str,
        voice_id: str,
        lang: str,
        sample_rate: int = 24000,
        *,
        container: str = "wav",
    ) -> SynthResult:
        audio_config = {
            "sample_rate": sample_rate,
            "num_channels": 1,
            "sample_width": 2,
            "encoding": "linear_pcm",
            "container": container,
        }
        if self.is_clone_handle(voice_id):
            body = {
                "text": text,
                "model": CLONE_MODEL,
                "audio_config": audio_config,
                "speaker_embedding": self.load_embedding(voice_id),
            }
        else:
            body = {
                "text": text,
                "voice": voice_id,
                "model": CATALOG_MODEL,
                "language": lang if lang in _TIMBRE_LANGS else "auto",
                "audio_config": audio_config,
            }

        start = time.perf_counter()
        resp = self._client.post(
            SYNTH_PATH, json=body, headers={"Content-Type": "application/json"}
        )
        ttfb = self._elapsed_ms(start)
        resp.raise_for_status()
        if resp.headers.get("content-type", "").startswith("application/json"):
            raise RuntimeError(f"Gnani returned JSON instead of audio: {resp.text[:300]}")
        return SynthResult(
            audio=resp.content,
            sample_rate=8000 if container in ("mulaw", "alaw") else sample_rate,
            fmt=container,
            chars=len(text),
            provider=self.name,
            voice_id=voice_id,
            ttfb_ms=ttfb,
            total_ms=self._elapsed_ms(start),
            cost_inr=self.cost_inr(len(text)),
        )

    def cost_inr(self, chars: int) -> float:
        # No published price as of 2026-09-09. 0.0 means unknown, not free — the
        # bake-off report says so explicitly.
        return 0.0


_TIMBRE_LANGS = {
    "auto", "hi-IN", "en-IN", "ta-IN", "te-IN", "kn-IN", "ml-IN", "mr-IN", "pa-IN",
    "bn-IN", "gu-IN", "hi-en",
}
