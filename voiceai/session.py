"""Turn a finished Conversation into the record schema/answers.schema.json describes.

Every completed call writes exactly one of these. It is the product: the voice is what
gets the voter to talk, this is what the MLA's office actually buys.

The audit fields are not optional extras. `disclosure_played_at` empty means we cannot
show the AI disclosure was given, and `dnd_checked_at` empty means we cannot show the
preference registry was honoured — both are required by docs/02_COMPLIANCE.md, and
`validate()` refuses a production record without them.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import jsonschema

from .config import REPO_ROOT
from .state_machine import Conversation, Outcome

SCHEMA_PATH = REPO_ROOT / "schema" / "answers.schema.json"

_ANSWER_DEFAULTS = {
    "water": "unanswered",
    "roads": "unanswered",
    "lights": "unanswered",
    "scheme_issue": "unanswered",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class CallSession:
    campaign_id: str
    voter_id: str
    lang: str
    politician_id: str = ""
    voice_consent_ref: str = ""
    call_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    started_at: str = field(default_factory=_now)
    ended_at: str | None = None
    disclosure_played_at: str | None = None
    dnd_checked_at: str | None = None
    recording_url: str | None = None
    cost_inr: float = 0.0

    def mark_disclosure_played(self) -> None:
        self.disclosure_played_at = _now()

    def mark_dnd_checked(self) -> None:
        self.dnd_checked_at = _now()

    def finish(self) -> None:
        self.ended_at = _now()

    # -- record --------------------------------------------------------------

    def to_record(self, convo: Conversation) -> dict:
        if self.ended_at is None:
            self.finish()

        answers: dict[str, object] = dict(_ANSWER_DEFAULTS)
        answers.update({k: v for k, v in convo.answers.items() if k in _ANSWER_DEFAULTS})

        if txt := convo.free_text.get("scheme_issue_text"):
            answers["scheme_issue_text"] = txt
        if txt := convo.free_text.get("open_grievance_text"):
            answers["open_grievance_text"] = txt
        if cat := convo.free_text.get("open_grievance_category"):
            # The classifier returns a priority band for the open question; the schema
            # keeps category free-form until a taxonomy exists from real pilot data.
            if cat in ("low", "medium", "high"):
                answers["open_grievance_priority"] = cat
            else:
                answers["open_grievance_category"] = cat

        outcome = convo.outcome
        record = {
            "call_id": self.call_id,
            "campaign_id": self.campaign_id,
            "voter_id": self.voter_id,
            "politician_id": self.politician_id,
            "voice_consent_ref": self.voice_consent_ref,
            "lang": self.lang,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_s": self._duration_s(),
            "disclosure_played_at": self.disclosure_played_at or "",
            "outcome": (
                outcome.value if outcome is not Outcome.IN_PROGRESS else "error"
            ),
            "answers": answers,
            "turns": [
                {
                    "role": t.role,
                    "text": t.text,
                    "from_cache": t.from_cache,
                    **({"latency_ms": t.latency_ms} if t.latency_ms is not None else {}),
                    **(
                        {"stt_confidence": t.stt_confidence}
                        if t.stt_confidence is not None
                        else {}
                    ),
                }
                for t in convo.turns
            ],
            "cost_inr": round(self.cost_inr, 4),
        }
        if self.dnd_checked_at:
            record["dnd_checked_at"] = self.dnd_checked_at
        if self.recording_url:
            record["recording_url"] = self.recording_url
        return record

    def _duration_s(self) -> float:
        try:
            start = datetime.fromisoformat(self.started_at)
            end = datetime.fromisoformat(self.ended_at or self.started_at)
            return round((end - start).total_seconds(), 2)
        except ValueError:
            return 0.0


def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def validate(record: dict, *, production: bool = False) -> None:
    """Schema check, plus the compliance invariants the schema cannot express."""
    jsonschema.validate(record, load_schema())

    if not record.get("disclosure_played_at"):
        raise ValueError(
            "record has no disclosure_played_at — a call without a logged AI disclosure "
            "is not a compliant call (docs/02_COMPLIANCE.md §1.1, §1.8)"
        )
    if production:
        if not record.get("dnd_checked_at"):
            raise ValueError("production record has no dnd_checked_at (§1.4)")
        if not record.get("voice_consent_ref"):
            raise ValueError("production record has no voice_consent_ref (§1.2)")


def write_record(record: dict, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{record['call_id']}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
