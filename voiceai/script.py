"""Call script loader.

Turn text lives in data/script.<lang>.yaml, which is a transcription of
docs/03_CALL_SCRIPT.md. Loading substitutes the speaker placeholders, so everything
downstream — the pre-render cache, the guard, the state machine — deals in final
spoken text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from .config import DATA_DIR, SpeakerIdentity

_WS = re.compile(r"\s+")
# Devanagari danda and double danda, plus the usual Latin punctuation. Kept explicit
# because str.isalnum() treats danda as punctuation but not every tokeniser does.
_PUNCT = re.compile(r"[।॥.,!?;:\-–—'\"()\[\]]+")

# Two words of slack: "नाही नको" is an opt-out, "पाणी येत नाही" is an answer.
MAX_STANDALONE_TOKENS = 2


def normalise(text: str) -> str:
    """Canonical form used for every text comparison in the system."""
    return _WS.sub(" ", text or "").strip()


def tokens(text: str) -> list[str]:
    return [t for t in _PUNCT.sub(" ", normalise(text).lower()).split() if t]


@dataclass(frozen=True)
class IntentMatcher:
    """Two-tier keyword matching, because the naive version ends calls wrongly.

    `phrases` are unambiguous and match anywhere in the utterance. `standalone` words
    (नाही, नहीं, no) are ordinary negations that appear inside perfectly normal
    answers, so they only count when the utterance is essentially nothing else.
    """

    phrases: tuple[str, ...] = ()
    standalone: frozenset[str] = frozenset()
    fillers: frozenset[str] = frozenset()

    @classmethod
    def from_yaml(cls, raw: dict) -> IntentMatcher:
        return cls(
            phrases=tuple(p.lower() for p in raw.get("phrases", []) or []),
            standalone=frozenset(s.lower() for s in raw.get("standalone", []) or []),
            fillers=frozenset(f.lower() for f in raw.get("fillers", []) or []),
        )

    def matches(self, utterance: str) -> bool:
        text = normalise(utterance).lower()
        if not text:
            return False
        if any(phrase in text for phrase in self.phrases):
            return True
        content = [t for t in tokens(text) if t not in self.fillers]
        if not content or len(content) > MAX_STANDALONE_TOKENS:
            return False
        return all(t in self.standalone for t in content)


@dataclass(frozen=True)
class Turn:
    id: str
    text: str
    kind: str = "fixed"
    field: str | None = None
    short: str | None = None
    disclosure: bool = False
    drafted_here: bool = False


class CallScript:
    """Fixed turns for one language, with placeholders already resolved."""

    def __init__(self, raw: dict, speaker: SpeakerIdentity):
        self.lang: str = raw["lang"]
        self.version: int = raw.get("version", 0)
        self.review: dict = raw.get("review", {})
        self._speaker = speaker

        ph = raw.get("placeholders", {})
        self._subs: dict[str, str] = {}
        if ph.get("speaker_name"):
            self._subs[ph["speaker_name"]] = speaker.name or ph["speaker_name"]
        if ph.get("constituency"):
            self._subs[ph["constituency"]] = speaker.constituency or ph["constituency"]

        self.turns: dict[str, Turn] = {}
        for tid, t in raw["turns"].items():
            self.turns[tid] = Turn(
                id=tid,
                text=self._fill(t["text"]),
                kind=t.get("kind", "fixed"),
                field=t.get("field"),
                short=self._fill(t["short"]) if t.get("short") else None,
                disclosure=bool(t.get("disclosure")),
                drafted_here=bool(t.get("drafted_here")),
            )

        acks = raw.get("acknowledgements", {})
        self.acknowledgements: list[str] = [self._fill(v) for v in acks.get("variants", [])]

        clar = raw.get("clarification", {})
        self.clarification_template: str = clar.get("template", "")

        self.optout = IntentMatcher.from_yaml(raw.get("optout", {}))
        self.affirm = IntentMatcher.from_yaml(raw.get("affirm", {}))

        q = raw.get("question", {}) or {}
        self._question_words = frozenset(w.lower() for w in q.get("words", []) or [])
        self._question_finals = frozenset(w.lower() for w in q.get("final_particles", []) or [])

        self.question_ids: list[str] = [t for t in ("Q1", "Q2", "Q3", "Q4") if t in self.turns]

    def _fill(self, text: str) -> str:
        out = text
        for placeholder, value in self._subs.items():
            out = out.replace(placeholder, value)
        return normalise(out)

    # -- accessors -----------------------------------------------------------

    def turn(self, turn_id: str) -> Turn:
        return self.turns[turn_id]

    def clarification_for(self, turn_id: str) -> str:
        """The one runtime-built string in the system.

        The `{short}` slot is filled only from a `short:` field in this file, never
        from model output, so the set of possible clarifications is finite and known
        at load time.
        """
        short = self.turns[turn_id].short
        if not short:
            raise KeyError(f"turn {turn_id} has no `short` to build a clarification from")
        return normalise(self.clarification_template.format(short=short))

    def all_clarifications(self) -> list[str]:
        return [
            self.clarification_for(tid)
            for tid, t in self.turns.items()
            if t.short and self.clarification_template
        ]

    @property
    def disclosure_turn(self) -> Turn:
        for t in self.turns.values():
            if t.disclosure:
                return t
        raise ValueError(
            f"script {self.lang} has no turn marked `disclosure: true` — the verbal AI "
            "disclosure is mandatory on every call (docs/02_COMPLIANCE.md §1.1)"
        )

    def is_optout(self, utterance: str) -> bool:
        return self.optout.matches(utterance)

    def is_affirmative(self, utterance: str) -> bool:
        return self.affirm.matches(utterance)

    def is_question(self, utterance: str) -> bool:
        """Is the voter asking us something, rather than answering us?

        Decides whether the answer bank gets consulted at all. Marathi and Hindi mark
        yes/no questions with a sentence-final particle (का / क्या) that is a common
        word elsewhere, so it only counts in final position.
        """
        text = normalise(utterance)
        if not text:
            return False
        if "?" in text:
            return True
        toks = tokens(text)
        if not toks:
            return False
        if any(t in self._question_words for t in toks):
            return True
        return toks[-1] in self._question_finals


def load_script(lang: str, speaker: SpeakerIdentity, data_dir: Path | None = None) -> CallScript:
    short = lang.split("-")[0]
    path = (data_dir or DATA_DIR) / f"script.{short}.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return CallScript(raw, speaker)
