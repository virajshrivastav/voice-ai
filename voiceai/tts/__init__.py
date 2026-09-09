"""TTS provider registry.

`get_tts("mock")` always works with no key. Everything else needs a key and is
constructed lazily so importing this package never touches the network.
"""

from __future__ import annotations

from .base import Capability, SynthResult, TTSProvider
from .mock import MockTTS

__all__ = [
    "Capability",
    "SynthResult",
    "TTSProvider",
    "MockTTS",
    "get_tts",
    "available_providers",
    "PROVIDER_CAPABILITIES",
]

# Kept importable without constructing anything, so `bakeoff --list` and the docs can
# show what each vendor can do before any account exists.
PROVIDER_CAPABILITIES: dict[str, Capability] = {
    "mock": MockTTS.capability,
    "smallest": Capability(
        marathi="yes",
        cloning="self-serve",
        streaming=True,
        note=(
            "9 Marathi voices, instant clone from 5-15s, ~200ms TTFB in-region, "
            "self-serve. Prohibited Use Policy: no candidate impersonation, political "
            "advertising needs prior written approval — ask before a pilot."
        ),
    ),
    "sarvam": Capability(
        marathi="yes",
        cloning="enterprise",
        streaming=True,
        note="Catalog voices via public API; cloning requires enterprise onboarding.",
    ),
    "gnani": Capability(
        marathi="yes",
        cloning="self-serve",
        streaming=True,
        note=(
            "Public API (docs.gnani.ai, self-serve keys at app.gnani.ai/voice, verified "
            "2026-09-09): zero-shot clone from 5-30 s -> embedding, REST/SSE/WebSocket "
            "synthesis, native 8 kHz mu-law, official Pipecat + LiveKit plugins. IndiaAI "
            "Mission sovereign-model firm. Price unpublished; Marathi clone quality "
            "unverified until the bake-off."
        ),
    ),
    "cartesia": Capability(
        marathi="unconfirmed",
        cloning="self-serve",
        streaming=True,
        note="Instant clone needs the Pro plan; Marathi coverage unconfirmed as of 2026-09-06.",
    ),
    "indicf5": Capability(
        marathi="yes",
        cloning="self-serve",
        streaming=False,
        note=(
            "AI4Bharat, MIT on the model card, free and self-hosted, Marathi zero-shot "
            "cloning. Needs a GPU and HuggingFace access approval; not streaming, so it "
            "suits pre-rendered turns rather than live ones."
        ),
    ),
}


def available_providers() -> list[str]:
    return sorted(PROVIDER_CAPABILITIES)


def get_tts(name: str, **kwargs) -> TTSProvider:
    name = (name or "mock").lower()

    if name == "mock":
        return MockTTS(**kwargs)

    if name == "smallest":
        from .smallest import SmallestTTS

        return SmallestTTS(**kwargs)

    if name == "sarvam":
        from .sarvam import SarvamTTS

        return SarvamTTS(**kwargs)

    if name == "gnani":
        from .gnani import GnaniTTS

        return GnaniTTS(**kwargs)

    if name == "cartesia":
        raise NotImplementedError(
            "Cartesia adapter not written. Instant Voice Clone requires their Pro plan "
            "and Marathi support is unconfirmed (docs/01_EVIDENCE_CHECK.md #13, #14) — "
            "confirm both at signup before spending the effort."
        )

    if name == "indicf5":
        raise NotImplementedError(
            "IndicF5 adapter not written: it needs a GPU, and this build is API-only for "
            "now. When a GPU is available, wrap ai4bharat/IndicF5 (MIT, Marathi zero-shot "
            "cloning from reference audio + its transcript) behind TTSProvider. Note the "
            "HuggingFace repo is access-gated and the GitHub repo has been dormant since "
            "September 2025."
        )

    raise ValueError(f"unknown TTS provider {name!r}; known: {available_providers()}")
