"""Campaign database.

SQLite for now — zero setup, ships in the stdlib, and a whole pilot's data fits in one
file that can be handed to the MLA's office on a pen drive. The DDL is deliberately
written to move to Postgres without a rewrite: ISO-8601 timestamps as TEXT, no SQLite
type affinity tricks, and `ON CONFLICT DO NOTHING` rather than `INSERT OR IGNORE`.

Schema follows `docs/00_CONTEXT.md §6`. Two things in it are not conveniences:

* `optout` is keyed on the phone number alone, not on (campaign, phone). An opt-out is
  a person saying "stop calling me", not "stop calling me about this campaign", and
  §1.3 of the compliance doc requires it to persist across every campaign forever.
* `call.disclosure_played_at` and `voter.dnd_checked_at` are the evidence that the two
  hard legal obligations were met on that specific call. If they are null, the call is
  not defensible, and `insights` reports them as a compliance exception rather than
  quietly ignoring them.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS politician (
    id                    TEXT PRIMARY KEY,
    name                  TEXT NOT NULL,
    constituency          TEXT NOT NULL,
    office_contact        TEXT,
    voice_id              TEXT,
    consent_ref           TEXT,
    consent_recording_url TEXT,
    consent_date          TEXT,
    created_at            TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS campaign (
    id             TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    politician_id  TEXT NOT NULL REFERENCES politician(id),
    lang           TEXT NOT NULL,
    script_version INTEGER,
    bank_version   INTEGER,
    manifest_sha   TEXT,
    status         TEXT NOT NULL DEFAULT 'draft',
    created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS voter (
    id             TEXT PRIMARY KEY,
    campaign_id    TEXT NOT NULL REFERENCES campaign(id),
    phone          TEXT NOT NULL,
    name           TEXT,
    ward           TEXT,
    tags           TEXT,
    context        TEXT,
    source         TEXT,
    dnd_checked_at TEXT,
    dnd_blocked    INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL,
    UNIQUE (campaign_id, phone)
);
CREATE INDEX IF NOT EXISTS idx_voter_campaign ON voter(campaign_id);
CREATE INDEX IF NOT EXISTS idx_voter_phone    ON voter(phone);
CREATE INDEX IF NOT EXISTS idx_voter_ward     ON voter(campaign_id, ward);

CREATE TABLE IF NOT EXISTS call (
    id                   TEXT PRIMARY KEY,
    campaign_id          TEXT NOT NULL REFERENCES campaign(id),
    voter_id             TEXT NOT NULL REFERENCES voter(id),
    attempt              INTEGER NOT NULL DEFAULT 1,
    outcome              TEXT NOT NULL,
    started_at           TEXT,
    ended_at             TEXT,
    duration_s           REAL,
    disclosure_played_at TEXT,
    dnd_checked_at       TEXT,
    voice_consent_ref    TEXT,
    recording_url        TEXT,
    cost_inr             REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_call_campaign ON call(campaign_id);
CREATE INDEX IF NOT EXISTS idx_call_voter    ON call(voter_id);

CREATE TABLE IF NOT EXISTS turn (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    call_id        TEXT NOT NULL REFERENCES call(id),
    seq            INTEGER NOT NULL,
    role           TEXT NOT NULL,
    text           TEXT NOT NULL,
    source         TEXT,
    from_cache     INTEGER NOT NULL DEFAULT 0,
    latency_ms     REAL,
    stt_confidence REAL
);
CREATE INDEX IF NOT EXISTS idx_turn_call ON turn(call_id);

CREATE TABLE IF NOT EXISTS answer (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    call_id  TEXT NOT NULL REFERENCES call(id),
    voter_id TEXT NOT NULL REFERENCES voter(id),
    field    TEXT NOT NULL,
    label    TEXT,
    raw_text TEXT,
    priority TEXT
);
CREATE INDEX IF NOT EXISTS idx_answer_call  ON answer(call_id);
CREATE INDEX IF NOT EXISTS idx_answer_field ON answer(field, label);

-- Keyed on phone alone, deliberately. See the module docstring.
CREATE TABLE IF NOT EXISTS optout (
    phone       TEXT PRIMARY KEY,
    at          TEXT NOT NULL,
    source      TEXT,
    campaign_id TEXT
);

CREATE TABLE IF NOT EXISTS attempt_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id TEXT NOT NULL,
    voter_id    TEXT NOT NULL,
    at          TEXT NOT NULL,
    outcome     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_attempt_voter ON attempt_log(voter_id);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: Path | str) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


@contextmanager
def session(path: Path | str) -> Iterator[sqlite3.Connection]:
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# -- writers ---------------------------------------------------------------------


def upsert_politician(conn: sqlite3.Connection, **fields) -> str:
    fields.setdefault("created_at", now_iso())
    cols = ", ".join(fields)
    marks = ", ".join("?" for _ in fields)
    updates = ", ".join(f"{c}=excluded.{c}" for c in fields if c != "id")
    conn.execute(
        f"INSERT INTO politician ({cols}) VALUES ({marks}) "
        f"ON CONFLICT(id) DO UPDATE SET {updates}",
        tuple(fields.values()),
    )
    return fields["id"]


def upsert_campaign(conn: sqlite3.Connection, **fields) -> str:
    fields.setdefault("created_at", now_iso())
    cols = ", ".join(fields)
    marks = ", ".join("?" for _ in fields)
    updates = ", ".join(f"{c}=excluded.{c}" for c in fields if c != "id")
    conn.execute(
        f"INSERT INTO campaign ({cols}) VALUES ({marks}) "
        f"ON CONFLICT(id) DO UPDATE SET {updates}",
        tuple(fields.values()),
    )
    return fields["id"]


def insert_voter(conn: sqlite3.Connection, **fields) -> bool:
    """-> True if inserted, False if this (campaign, phone) was already present."""
    fields.setdefault("created_at", now_iso())
    if isinstance(fields.get("context"), dict):
        fields["context"] = json.dumps(fields["context"], ensure_ascii=False)
    if isinstance(fields.get("tags"), (list, tuple)):
        fields["tags"] = ",".join(fields["tags"])
    cols = ", ".join(fields)
    marks = ", ".join("?" for _ in fields)
    cur = conn.execute(
        f"INSERT INTO voter ({cols}) VALUES ({marks}) "
        f"ON CONFLICT(campaign_id, phone) DO NOTHING",
        tuple(fields.values()),
    )
    return cur.rowcount > 0


def record_call(conn: sqlite3.Connection, record: dict, voter_id: str) -> None:
    """Persist one `schema/answers.schema.json` record plus its turns and answers."""
    conn.execute(
        """INSERT INTO call (id, campaign_id, voter_id, attempt, outcome, started_at,
                             ended_at, duration_s, disclosure_played_at, dnd_checked_at,
                             voice_consent_ref, recording_url, cost_inr)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            record["call_id"], record["campaign_id"], voter_id,
            record.get("attempt", 1), record["outcome"], record.get("started_at"),
            record.get("ended_at"), record.get("duration_s"),
            record.get("disclosure_played_at") or None, record.get("dnd_checked_at"),
            record.get("voice_consent_ref"), record.get("recording_url"),
            record.get("cost_inr", 0.0),
        ),
    )
    for seq, t in enumerate(record.get("turns", [])):
        conn.execute(
            """INSERT INTO turn (call_id, seq, role, text, source, from_cache,
                                 latency_ms, stt_confidence)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                record["call_id"], seq, t["role"], t["text"], t.get("source"),
                int(bool(t.get("from_cache"))), t.get("latency_ms"),
                t.get("stt_confidence"),
            ),
        )

    answers = record.get("answers", {})
    priority = answers.get("open_grievance_priority")
    for field in ("water", "roads", "lights", "scheme_issue"):
        if field in answers:
            raw = answers.get("scheme_issue_text") if field == "scheme_issue" else None
            conn.execute(
                "INSERT INTO answer (call_id, voter_id, field, label, raw_text) "
                "VALUES (?,?,?,?,?)",
                (record["call_id"], voter_id, field, answers[field], raw),
            )
    if answers.get("open_grievance_text"):
        conn.execute(
            "INSERT INTO answer (call_id, voter_id, field, label, raw_text, priority) "
            "VALUES (?,?,?,?,?,?)",
            (
                record["call_id"], voter_id, "open_grievance",
                answers.get("open_grievance_category"),
                answers["open_grievance_text"], priority,
            ),
        )

    conn.execute(
        "INSERT INTO attempt_log (campaign_id, voter_id, at, outcome) VALUES (?,?,?,?)",
        (record["campaign_id"], voter_id, record.get("started_at") or now_iso(),
         record["outcome"]),
    )
