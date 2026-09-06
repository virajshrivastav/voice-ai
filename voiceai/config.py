"""Runtime configuration.

Everything is read from the environment (see .env.example). Nothing here has a
default that costs money or reaches a vendor: with an empty .env the whole package
runs against the `mock` providers, which is how the test suite and the offline demo
work.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
CACHE_DIR = REPO_ROOT / "cache"
SAMPLES_DIR = REPO_ROOT / "samples"
OUT_DIR = REPO_ROOT / "out"

load_dotenv(REPO_ROOT / ".env")


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass(frozen=True)
class SpeakerIdentity:
    """The consented speaker whose voice is cloned.

    `consent_ref` is not decoration. docs/02_COMPLIANCE.md §1.2 requires a signed +
    recorded consent artefact before any clone is used, and `require_consent()` is
    called on every production path.
    """

    name: str = field(default_factory=lambda: _env("SPEAKER_NAME"))
    constituency: str = field(default_factory=lambda: _env("SPEAKER_CONSTITUENCY"))
    office_contact: str = field(default_factory=lambda: _env("OFFICE_CONTACT"))
    consent_ref: str = field(default_factory=lambda: _env("VOICE_CONSENT_REF"))

    def require_consent(self) -> None:
        if not self.consent_ref:
            raise PermissionError(
                "VOICE_CONSENT_REF is empty. No voice may be cloned or synthesised "
                "without a stored consent artefact (docs/02_COMPLIANCE.md §1.2, §3)."
            )


@dataclass(frozen=True)
class Settings:
    lang: str = field(default_factory=lambda: _env("CALL_LANG", "mr-IN"))
    voice_id: str = field(default_factory=lambda: _env("VOICE_ID"))
    tts_provider: str = field(default_factory=lambda: _env("TTS_PROVIDER", "mock"))
    stt_provider: str = field(default_factory=lambda: _env("STT_PROVIDER", "mock"))

    sarvam_api_key: str = field(default_factory=lambda: _env("SARVAM_API_KEY"))
    smallest_api_key: str = field(default_factory=lambda: _env("SMALLEST_API_KEY"))
    cartesia_api_key: str = field(default_factory=lambda: _env("CARTESIA_API_KEY"))

    # "demo" relaxes the answer-bank approval gate so the pipeline can be exercised
    # before an MLA has signed off on the text. It must never be used on a real call.
    mode: str = field(default_factory=lambda: _env("MODE", "demo"))

    speaker: SpeakerIdentity = field(default_factory=SpeakerIdentity)

    @property
    def is_production(self) -> bool:
        return self.mode == "production"

    @property
    def lang_short(self) -> str:
        """`mr-IN` -> `mr`, used for data-file names and provider language codes."""
        return self.lang.split("-")[0]


def load_settings() -> Settings:
    return Settings()
