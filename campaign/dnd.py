"""DND / preference-registry gate.

TRAI TCCCPR requires the sender to honour subscriber preferences before dialling, and
`docs/02_COMPLIANCE.md §1.4` requires the check to be logged per number per batch.
The real check happens against the access provider's DLT preference registry, which we
cannot reach until the MLA's office is registered as a Principal Entity — so the
provider is an interface with a stub behind it today.

The important part is what the stub *refuses to do*. `NullDNDProvider` returns
all-clear in demo mode and raises in production. Shipping a pilot where every number
silently passes a check that never ran is how you end up with a real TRAI complaint
against a sitting MLA's office, and it is the kind of thing that is invisible until it
is very visible.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Protocol

from .db import now_iso


class DNDCheckUnavailableError(RuntimeError):
    pass


class DNDProvider(Protocol):
    name: str

    def check(self, phones: list[str]) -> dict[str, bool]:
        """-> {phone: blocked}. True means do not dial."""


@dataclass
class NullDNDProvider:
    """Development stub. Passes everything, and says so loudly."""

    name: str = "null"
    production: bool = False
    warned: bool = field(default=False, repr=False)

    def check(self, phones: list[str]) -> dict[str, bool]:
        if self.production:
            raise DNDCheckUnavailableError(
                "NullDNDProvider cannot be used in production. No preference-registry "
                "check has actually run, so every number would be marked 'checked' "
                "without being checked (docs/02_COMPLIANCE.md §1.4). Wire the access "
                "provider's DLT registry before dialling a real list."
            )
        if not self.warned:
            print("  [dnd] NullDNDProvider: no real preference check is running (demo mode)")
            self.warned = True
        return {p: False for p in phones}


@dataclass
class StaticDNDProvider:
    """A fixed blocklist. Useful for tests, and for an office that has been handed a
    registry extract as a file rather than API access."""

    blocked: set[str]
    name: str = "static"

    def check(self, phones: list[str]) -> dict[str, bool]:
        return {p: p in self.blocked for p in phones}


@dataclass
class DNDGate:
    conn: sqlite3.Connection
    provider: DNDProvider

    def check_batch(self, campaign_id: str, phones: list[str]) -> dict[str, bool]:
        """Check and stamp. The timestamp is the evidence; without it a call cannot be
        shown to have honoured preferences."""
        if not phones:
            return {}
        results = self.provider.check(phones)
        stamp = now_iso()
        self.conn.executemany(
            "UPDATE voter SET dnd_checked_at = ?, dnd_blocked = ? "
            "WHERE campaign_id = ? AND phone = ?",
            [(stamp, int(results.get(p, False)), campaign_id, p) for p in phones],
        )
        return results

    def check_pending(self, campaign_id: str, limit: int = 1000) -> dict[str, bool]:
        """Check every voter in this campaign that has never been checked."""
        rows = self.conn.execute(
            "SELECT phone FROM voter WHERE campaign_id = ? AND dnd_checked_at IS NULL "
            "LIMIT ?",
            (campaign_id, limit),
        ).fetchall()
        return self.check_batch(campaign_id, [r["phone"] for r in rows])
