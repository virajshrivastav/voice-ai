"""SpeechGuard — the hard guarantee.

Every path to the cloned voice goes through `assert_speakable()`. If a string is not
in the closed set built from the call script plus the approved answer bank, it is
never synthesised. A bug in the state machine, a hallucinated id from the classifier,
or a prompt injection carried in a voter's own words all fail the same way: the guard
refuses, and the caller falls back to approved text.

This is also the artefact you hand a Media Certification and Monitoring Committee.
`manifest()` is the complete, finite list of sentences the MLA's voice can utter —
which is what makes pre-certification of an interactive system possible at all
(docs/02_COMPLIANCE.md, ECI section).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from .answer_bank import AnswerBank
from .script import CallScript, normalise


class UnapprovedSpeechError(PermissionError):
    """Something tried to synthesise text that no human approved."""


@dataclass(frozen=True)
class SpeechItem:
    text: str
    source: str  # script:OPEN, ack:0, clarification:Q1, bank:water_tanker, bank:fallback


class SpeechGuard:
    def __init__(self, script: CallScript, bank: AnswerBank):
        if script.lang != bank.lang:
            raise ValueError(
                f"script is {script.lang} but answer bank is {bank.lang} — refusing to "
                "mix languages in one guard"
            )
        self.lang = script.lang
        items: list[SpeechItem] = []

        for tid, turn in script.turns.items():
            items.append(SpeechItem(turn.text, f"script:{tid}"))
        for i, ack in enumerate(script.acknowledgements):
            items.append(SpeechItem(ack, f"ack:{i}"))
        for tid, turn in script.turns.items():
            if turn.short and script.clarification_template:
                items.append(SpeechItem(script.clarification_for(tid), f"clarification:{tid}"))
        for entry in bank.entries.values():
            items.append(SpeechItem(entry.text, f"bank:{entry.id}"))
        items.append(SpeechItem(bank.fallback_text, f"bank:{bank.fallback_id}"))

        self.items: tuple[SpeechItem, ...] = tuple(items)
        self._allowed: dict[str, str] = {}
        for item in items:
            # Same sentence from two sources is fine; first source wins for reporting.
            self._allowed.setdefault(item.text, item.source)

    # -- enforcement ---------------------------------------------------------

    def is_allowed(self, text: str) -> bool:
        return normalise(text) in self._allowed

    def source_of(self, text: str) -> str | None:
        return self._allowed.get(normalise(text))

    def assert_speakable(self, text: str) -> str:
        """Returns the normalised text, or raises. Call this immediately before TTS."""
        t = normalise(text)
        if t not in self._allowed:
            preview = t[:80] + ("…" if len(t) > 80 else "")
            raise UnapprovedSpeechError(
                f"refusing to synthesise unapproved text in a cloned voice: {preview!r}. "
                f"Allowed set has {len(self._allowed)} sentences for {self.lang}."
            )
        return t

    # -- artefacts -----------------------------------------------------------

    def allowed_texts(self) -> list[str]:
        """Everything the pre-render cache needs to synthesise, in a stable order."""
        return [item.text for item in self.items]

    def manifest(self) -> dict:
        """Certification artefact: every sentence, its source, and a hash of the set."""
        entries = [{"source": i.source, "text": i.text} for i in self.items]
        payload = json.dumps(entries, ensure_ascii=False, sort_keys=True)
        return {
            "lang": self.lang,
            "count": len(entries),
            "sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
            "entries": entries,
        }

    def __len__(self) -> int:
        return len(self._allowed)
