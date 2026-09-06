"""The opt-out ledger.

The one table in this system with no expiry, no scope and no override. When someone
says "stop calling me", that is a statement about being called, not about a campaign,
so the ledger is keyed on the phone number alone and every campaign checks the same
list (`docs/02_COMPLIANCE.md §1.3`, and the retention table's "indefinite — must
persist").

There is no `remove()`. Taking a number *off* an opt-out list is the single most
damaging accidental operation available here, and if a person genuinely asks to be
re-added they can be re-consented through a path that leaves a record — not by an
engineer running a DELETE. Import from CSV is one-way for the same reason: it only
ever adds.
"""

from __future__ import annotations

import csv
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .db import now_iso
from .phone import normalise


@dataclass
class ImportResult:
    added: int = 0
    already_present: int = 0
    unparseable: list[tuple[str, str]] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.unparseable is None:
            self.unparseable = []

    def summary(self) -> str:
        return (
            f"{self.added} added, {self.already_present} already on the list, "
            f"{len(self.unparseable)} could not be parsed"
        )


class OptOutLedger:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def add(self, phone: str, *, source: str = "call", campaign_id: str | None = None) -> bool:
        """-> True if newly added. Idempotent; adding twice is not an error."""
        result = normalise(phone)
        if not result.ok:
            raise ValueError(f"cannot opt out an unparseable number: {phone!r} ({result.reason})")
        cur = self._conn.execute(
            "INSERT INTO optout (phone, at, source, campaign_id) VALUES (?,?,?,?) "
            "ON CONFLICT(phone) DO NOTHING",
            (result.e164, now_iso(), source, campaign_id),
        )
        return cur.rowcount > 0

    def contains(self, phone: str) -> bool:
        """The gate. Called before every dial, and before every ingest row is accepted."""
        result = normalise(phone)
        if not result.ok:
            # An unparseable number cannot be dialled anyway. Fail closed.
            return True
        row = self._conn.execute(
            "SELECT 1 FROM optout WHERE phone = ?", (result.e164,)
        ).fetchone()
        return row is not None

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM optout").fetchone()[0]

    def all(self) -> list[sqlite3.Row]:
        return self._conn.execute("SELECT * FROM optout ORDER BY at DESC").fetchall()

    # -- interchange with the office's existing lists ----------------------------

    def import_csv(self, path: Path, column: str = "phone", source: str = "import") -> ImportResult:
        """Additive only. An office that already keeps a do-not-call list must be able
        to bring it, and nothing in that file can ever remove an existing entry."""
        result = ImportResult()
        with Path(path).open(encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                raw = (row.get(column) or "").strip()
                parsed = normalise(raw)
                if not parsed.ok:
                    result.unparseable.append((raw, parsed.reason.value if parsed.reason else "?"))
                    continue
                if self.add(parsed.e164, source=source):
                    result.added += 1
                else:
                    result.already_present += 1
        return result

    def export_csv(self, path: Path) -> int:
        rows = self.all()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(["phone", "at", "source", "campaign_id"])
            for r in rows:
                writer.writerow([r["phone"], r["at"], r["source"], r["campaign_id"]])
        return len(rows)
