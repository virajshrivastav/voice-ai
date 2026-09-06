"""Approved answer bank.

The product decision this implements: when a voter asks something back, the agent
never writes a reply. It picks an id out of a file that a human has approved, and
plays the pre-rendered audio for that id. The LLM's entire authority is "return one
of these ids, or NONE".

Two gates protect that:
  * `require_approved()` — the bank must be signed off, and the signed-off text must
    still hash to what was approved. Edit an answer after approval and it fails closed.
  * `SpeechGuard` (guard.py) — sits at the synthesis boundary, so even a bug here
    cannot get novel text into the speaker's cloned voice.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .config import DATA_DIR, SpeakerIdentity
from .script import normalise


class BankNotApprovedError(PermissionError):
    """Raised when a production path touches an unapproved or tampered answer bank."""


@dataclass(frozen=True)
class AnswerBankEntry:
    id: str
    intent: str
    text: str
    triggers: tuple[str, ...] = ()
    tags: frozenset[str] = field(default_factory=frozenset)

    @property
    def ends_call(self) -> bool:
        return "ends_call" in self.tags

    @property
    def is_optout(self) -> bool:
        return "optout" in self.tags


class AnswerBank:
    def __init__(self, raw: dict, speaker: SpeakerIdentity):
        self.lang: str = raw["lang"]
        self.version: int = raw.get("version", 0)
        self.approval: dict = raw.get("approval", {}) or {}

        placeholder = raw.get("office_contact_placeholder")
        self._subs: dict[str, str] = {}
        if placeholder:
            self._subs[placeholder] = speaker.office_contact or placeholder

        self.entries: dict[str, AnswerBankEntry] = {}
        for e in raw.get("entries", []):
            entry = AnswerBankEntry(
                id=e["id"],
                intent=e["intent"],
                text=self._fill(e["text"]),
                triggers=tuple(t.lower() for t in e.get("triggers", []) or []),
                tags=frozenset(e.get("tags", []) or []),
            )
            if entry.id in self.entries:
                raise ValueError(f"duplicate answer bank id: {entry.id}")
            self.entries[entry.id] = entry

        fb = raw.get("fallback") or {}
        self.fallback_id: str = fb.get("id", "no_matched_answer")
        self.fallback_text: str = self._fill(fb.get("text", ""))
        if not self.fallback_text:
            raise ValueError(f"answer bank {self.lang} has no fallback text")

    def _fill(self, text: str) -> str:
        out = text
        for placeholder, value in self._subs.items():
            out = out.replace(placeholder, value)
        return normalise(out)

    # -- approval ------------------------------------------------------------

    def content_hash(self) -> str:
        """Hash over the id+text pairs actually loaded, excluding placeholder fill.

        Computed on the raw approved text so that changing the office phone number
        does not invalidate a sign-off, but changing an answer does.
        """
        payload = "\n".join(f"{eid}\x1f{self.entries[eid].text}" for eid in sorted(self.entries))
        payload += f"\n{self.fallback_id}\x1f{self.fallback_text}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @property
    def is_approved(self) -> bool:
        return self.approval.get("status") == "approved"

    def require_approved(self) -> None:
        if not self.is_approved:
            raise BankNotApprovedError(
                f"answer bank {self.lang} is `{self.approval.get('status')}`. A named person "
                "in the MLA's office must approve this exact text before it is spoken in "
                "his voice (docs/02_COMPLIANCE.md §1.6). Run in MODE=demo to bypass for "
                "development only."
            )
        if not self.approval.get("approved_by"):
            raise BankNotApprovedError(
                f"answer bank {self.lang} is marked approved but `approved_by` is empty."
            )
        recorded = self.approval.get("approved_text_sha256")
        actual = self.content_hash()
        if recorded and recorded != actual:
            raise BankNotApprovedError(
                f"answer bank {self.lang} changed after approval "
                f"(approved {recorded[:12]}…, now {actual[:12]}…). Re-approve it."
            )

    # -- retrieval -----------------------------------------------------------

    def control_candidates(self, utterance: str) -> list[AnswerBankEntry]:
        """Entries tagged `control` — "wrong number", "I don't live here", "call me
        later", "say that again".

        These are neither questions nor answers, so neither the interrogative check nor
        the classifier catches them, and without a dedicated pass "मी इथे राहत नाही,
        चुकीचा नंबर आहे" gets recorded as an answer to the water question and the call
        carries on. Deliberately keyword-only and checked on every utterance: a person
        telling you that you have the wrong number must not depend on a model call.
        """
        return [e for e in self.keyword_candidates(utterance) if "control" in e.tags]

    def keyword_candidates(self, utterance: str) -> list[AnswerBankEntry]:
        """Cheap first pass. Returns entries whose triggers appear in the utterance,
        best (most trigger hits, then longest trigger) first.

        Deliberately not the only path: triggers miss paraphrase, which is why the
        LLM classifier exists. But a hit here skips an LLM call entirely.
        """
        u = normalise(utterance).lower()
        scored: list[tuple[int, int, AnswerBankEntry]] = []
        for entry in self.entries.values():
            hits = [t for t in entry.triggers if t in u]
            if hits:
                scored.append((len(hits), max(len(t) for t in hits), entry))
        scored.sort(key=lambda s: (s[0], s[1]), reverse=True)
        return [e for _, _, e in scored]

    def intent_menu(self) -> str:
        """The only thing the classifier LLM ever sees as its output space."""
        lines = [f"{e.id}: {e.intent}" for e in self.entries.values()]
        lines.append("NONE: none of the above, or you are not sure")
        return "\n".join(lines)

    def resolve(self, entry_id: str | None) -> AnswerBankEntry | None:
        """Look up an id returned by the classifier. Unknown ids resolve to None,
        which sends the caller to the fallback — a model that hallucinates an id
        cannot produce speech."""
        if not entry_id:
            return None
        return self.entries.get(entry_id.strip())

    def all_texts(self) -> list[str]:
        return [e.text for e in self.entries.values()] + [self.fallback_text]


def load_answer_bank(
    lang: str, speaker: SpeakerIdentity, data_dir: Path | None = None
) -> AnswerBank:
    short = lang.split("-")[0]
    path = (data_dir or DATA_DIR) / f"answer_bank.{short}.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return AnswerBank(raw, speaker)
