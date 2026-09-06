"""Speech-to-text providers."""

from .base import STTProvider, Transcript
from .mock import MockSTT

__all__ = ["STTProvider", "Transcript", "MockSTT", "get_stt"]


def get_stt(name: str, **kwargs) -> STTProvider:
    name = (name or "mock").lower()
    if name == "mock":
        return MockSTT(**kwargs)
    if name == "sarvam":
        from .sarvam import SarvamSTT

        return SarvamSTT(**kwargs)
    raise ValueError(f"unknown STT provider {name!r}; known: mock, sarvam")
