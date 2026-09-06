"""Cloned-voice, two-way constituent outreach calls (Marathi/Hindi).

Read docs/00_CONTEXT.md first. The short version of what lives here:

    config.py         env-driven settings; empty .env == everything runs on mocks
    script.py         fixed turn text, loaded from data/script.<lang>.yaml
    answer_bank.py    the approved replies, with an approval + tamper gate
    guard.py          SpeechGuard — the closed set of sentences the voice may utter
    state_machine.py  the conversation, transport-free and testable without audio
    classify.py       the only thing the LLM is allowed to do: return a label
    prerender.py      synthesise the whole allowed set once per voice, play from disk
    session.py        the record that schema/answers.schema.json describes
    costs.py          per-minute and per-sweep cost model
    audio.py          telephony degradation — judge every voice at 8 kHz, never clean
    tts/, stt/        swappable vendors behind one interface
"""

from .config import Settings, load_settings
from .guard import SpeechGuard, UnapprovedSpeechError

__all__ = ["Settings", "load_settings", "SpeechGuard", "UnapprovedSpeechError", "build"]

__version__ = "0.1.0"


def build(lang: str | None = None, settings: Settings | None = None):
    """Load script + answer bank + guard for a language. The one entry point that
    everything else (bake-off, browser bot, telephony bot) starts from."""
    from .answer_bank import load_answer_bank
    from .script import load_script

    settings = settings or load_settings()
    lang = lang or settings.lang
    script = load_script(lang, settings.speaker)
    bank = load_answer_bank(lang, settings.speaker)
    if settings.is_production:
        bank.require_approved()
        settings.speaker.require_consent()
    return script, bank, SpeechGuard(script, bank)
