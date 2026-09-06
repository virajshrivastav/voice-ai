"""Dialling policy.

This module does not dial. It decides *whether* dialling is allowed and *who* is next,
which is where every compliance rule that constrains outbound calling actually lives:
the 10:00–19:00 window, blackout dates for polling day and the 48-hour silence period,
the opt-out ledger, the preference check, and how hard we are willing to chase someone
who did not pick up.

Keeping it separate from the transport means all of it is testable today, a year before
there is a phone number — and it means the rules cannot be quietly bypassed by whoever
writes the Stage 2 telephony integration.

The retry policy is the one place here with a real judgement in it. See RETRYABLE.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone

# IST is UTC+05:30 and has never observed DST. A fixed offset is exactly correct and
# avoids depending on the IANA database, which Windows does not ship.
IST = timezone(timedelta(hours=5, minutes=30))

# Outcomes worth trying again.
#
# `hangup` and `silence` are deliberately absent. Someone who picked up and ended the
# call has told us something, and someone who picked up and said nothing twice has too.
# Redialling either is how a governance-outreach campaign turns into a nuisance
# complaint against the MLA's office, and at 3.5 lakh numbers there is no shortage of
# people who have not been called at all yet.
RETRYABLE = frozenset({"no_answer", "error", "voicemail"})
TERMINAL = frozenset({"completed", "opted_out", "hangup", "silence"})


@dataclass(frozen=True)
class DialPlan:
    window_start: time = time(10, 0)
    window_end: time = time(19, 0)
    blackout_dates: frozenset[date] = frozenset()
    max_attempts: int = 3
    # Hours to wait before attempt 2, then before attempt 3. Spread across days so a
    # second try lands at a different time of day than the first.
    retry_backoff_hours: tuple[int, ...] = (5, 27)
    max_concurrent: int = 50

    def with_blackout(self, *days: date) -> DialPlan:
        return DialPlan(
            window_start=self.window_start,
            window_end=self.window_end,
            blackout_dates=self.blackout_dates | frozenset(days),
            max_attempts=self.max_attempts,
            retry_backoff_hours=self.retry_backoff_hours,
            max_concurrent=self.max_concurrent,
        )

    def backoff_for(self, attempts_so_far: int) -> timedelta:
        if not self.retry_backoff_hours:
            return timedelta(0)
        idx = min(attempts_so_far - 1, len(self.retry_backoff_hours) - 1)
        return timedelta(hours=self.retry_backoff_hours[max(idx, 0)])


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str

    def __bool__(self) -> bool:
        return self.allowed


def is_dialable_now(plan: DialPlan, now: datetime | None = None) -> Decision:
    """Whether the dialer may run at all right now."""
    now = (now or datetime.now(IST)).astimezone(IST)

    if now.date() in plan.blackout_dates:
        return Decision(False, f"blackout date ({now.date().isoformat()})")
    local = now.timetz().replace(tzinfo=None)
    if local < plan.window_start:
        return Decision(False, f"before dialling window (opens {plan.window_start:%H:%M} IST)")
    if local >= plan.window_end:
        return Decision(False, f"after dialling window (closes {plan.window_end:%H:%M} IST)")
    return Decision(True, "within window")


@dataclass
class Candidate:
    voter_id: str
    phone: str
    name: str | None
    ward: str | None
    attempts: int
    last_outcome: str | None
    last_attempt_at: str | None


@dataclass
class Dialer:
    conn: sqlite3.Connection
    plan: DialPlan = field(default_factory=DialPlan)

    def next_batch(
        self, campaign_id: str, size: int | None = None, now: datetime | None = None
    ) -> list[Candidate]:
        """Voters eligible to be dialled, most-neglected first.

        Every exclusion here is a rule from `02_COMPLIANCE.md`, not an optimisation:
        opted out, never preference-checked, preference-blocked, already resolved, or
        still inside its retry backoff.
        """
        now = (now or datetime.now(IST)).astimezone(IST)
        size = size or self.plan.max_concurrent

        rows = self.conn.execute(
            """
            SELECT v.id, v.phone, v.name, v.ward,
                   COUNT(a.id)                AS attempts,
                   MAX(a.at)                  AS last_attempt_at,
                   (SELECT outcome FROM attempt_log
                     WHERE voter_id = v.id ORDER BY at DESC LIMIT 1) AS last_outcome
              FROM voter v
              LEFT JOIN attempt_log a ON a.voter_id = v.id
             WHERE v.campaign_id = ?
               AND v.dnd_checked_at IS NOT NULL
               AND v.dnd_blocked = 0
               AND NOT EXISTS (SELECT 1 FROM optout o WHERE o.phone = v.phone)
             GROUP BY v.id
            HAVING attempts < ?
             ORDER BY attempts ASC, v.created_at ASC
            """,
            (campaign_id, self.plan.max_attempts),
        ).fetchall()

        out: list[Candidate] = []
        for r in rows:
            if r["last_outcome"] in TERMINAL:
                continue
            if r["attempts"] and r["last_outcome"] not in RETRYABLE:
                continue
            if r["last_attempt_at"]:
                try:
                    last = datetime.fromisoformat(r["last_attempt_at"])
                except ValueError:
                    last = None
                if last is not None:
                    if last.tzinfo is None:
                        last = last.replace(tzinfo=timezone.utc)
                    if now - last < self.plan.backoff_for(r["attempts"]):
                        continue
            out.append(
                Candidate(
                    voter_id=r["id"], phone=r["phone"], name=r["name"], ward=r["ward"],
                    attempts=r["attempts"], last_outcome=r["last_outcome"],
                    last_attempt_at=r["last_attempt_at"],
                )
            )
            if len(out) >= size:
                break
        return out

    def funnel(self, campaign_id: str) -> dict[str, int]:
        """Where every number in the campaign currently stands. This is the first table
        the office will ask for."""
        total = self.conn.execute(
            "SELECT COUNT(*) FROM voter WHERE campaign_id = ?", (campaign_id,)
        ).fetchone()[0]
        opted = self.conn.execute(
            "SELECT COUNT(*) FROM voter v JOIN optout o ON o.phone = v.phone "
            "WHERE v.campaign_id = ?",
            (campaign_id,),
        ).fetchone()[0]
        unchecked = self.conn.execute(
            "SELECT COUNT(*) FROM voter WHERE campaign_id = ? AND dnd_checked_at IS NULL",
            (campaign_id,),
        ).fetchone()[0]
        blocked = self.conn.execute(
            "SELECT COUNT(*) FROM voter WHERE campaign_id = ? AND dnd_blocked = 1",
            (campaign_id,),
        ).fetchone()[0]
        outcomes = {
            r["outcome"]: r["n"]
            for r in self.conn.execute(
                "SELECT outcome, COUNT(*) AS n FROM call WHERE campaign_id = ? "
                "GROUP BY outcome",
                (campaign_id,),
            ).fetchall()
        }
        dialled = self.conn.execute(
            "SELECT COUNT(DISTINCT voter_id) FROM attempt_log WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()[0]

        return {
            "voters": total,
            "opted_out": opted,
            "dnd_unchecked": unchecked,
            "dnd_blocked": blocked,
            "dialled": dialled,
            "not_yet_dialled": total - dialled,
            **{f"outcome_{k}": v for k, v in sorted(outcomes.items())},
        }
