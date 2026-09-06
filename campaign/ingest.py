"""Voter list ingest.

    python -m campaign.ingest voters.csv --campaign c1 --db out/campaign.db

Real voter lists arrive as somebody's export with headers nobody agreed on, phone
numbers in four formats, the same household entered twice, and a few hundred rows of
placeholder junk. This turns that into rows we are allowed to dial, and — just as
importantly — a rejects file that says *why* each dropped row was dropped.

That rejects file is not a nicety. If 8% of a constituency silently vanishes during
import, nobody notices until the MLA asks why his own neighbourhood never got called.
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from voiceai.console import setup

from .db import insert_voter, session
from .optout import OptOutLedger
from .phone import mask, normalise

# Header names seen in the wild, lowercased. First match wins.
COLUMN_GUESSES = {
    "phone": ("phone", "mobile", "mobile no", "mobile number", "contact", "contact no",
              "phone number", "मोबाइल", "मोबाईल", "भ्रमणध्वनी"),
    "name": ("name", "voter name", "full name", "elector name", "नाव", "नाम"),
    "ward": ("ward", "ward no", "ward name", "area", "locality", "booth", "वॉर्ड", "प्रभाग"),
    "tags": ("tags", "segment", "category"),
}


@dataclass
class IngestReport:
    rows_read: int = 0
    accepted: int = 0
    duplicate_in_file: int = 0
    duplicate_in_db: int = 0
    opted_out: int = 0
    rejected: Counter = field(default_factory=Counter)

    @property
    def dropped(self) -> int:
        return (
            self.duplicate_in_file + self.duplicate_in_db + self.opted_out
            + sum(self.rejected.values())
        )

    def summary(self) -> str:
        lines = [
            f"  rows read            {self.rows_read:,}",
            f"  accepted             {self.accepted:,}",
            f"  dropped              {self.dropped:,}",
            f"    duplicate in file  {self.duplicate_in_file:,}",
            f"    already in db      {self.duplicate_in_db:,}",
            f"    on opt-out list    {self.opted_out:,}",
        ]
        for reason, n in self.rejected.most_common():
            lines.append(f"    {reason:<18} {n:,}")
        if self.rows_read:
            kept = 100 * self.accepted / self.rows_read
            lines.append(f"  kept                 {kept:.1f}%")
        return "\n".join(lines)


def guess_columns(headers: list[str]) -> dict[str, str]:
    lowered = {h.strip().lower(): h for h in headers}
    mapping: dict[str, str] = {}
    for field_name, candidates in COLUMN_GUESSES.items():
        for candidate in candidates:
            if candidate in lowered:
                mapping[field_name] = lowered[candidate]
                break
    return mapping


def parse_map_arg(arg: str | None) -> dict[str, str]:
    """`--map phone=Mobile,ward=Prabhag`"""
    if not arg:
        return {}
    out = {}
    for pair in arg.split(","):
        if "=" in pair:
            k, v = pair.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def ingest(
    csv_path: Path,
    db_path: Path,
    campaign_id: str,
    *,
    column_map: dict[str, str] | None = None,
    rejects_path: Path | None = None,
    source: str | None = None,
) -> IngestReport:
    report = IngestReport()
    rejects: list[dict] = []
    seen: set[str] = set()

    with csv_path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        headers = reader.fieldnames or []
        mapping = {**guess_columns(headers), **(column_map or {})}
        if "phone" not in mapping:
            raise SystemExit(
                f"could not find a phone column in {headers}. "
                f"Pass --map phone=<header>."
            )

        with session(db_path) as conn:
            ledger = OptOutLedger(conn)
            for row in reader:
                report.rows_read += 1
                raw_phone = row.get(mapping["phone"], "")
                parsed = normalise(raw_phone)

                if not parsed.ok:
                    reason = parsed.reason.value if parsed.reason else "unknown"
                    report.rejected[reason] += 1
                    rejects.append({**row, "_reason": reason})
                    continue
                if parsed.e164 in seen:
                    report.duplicate_in_file += 1
                    rejects.append({**row, "_reason": "duplicate_in_file"})
                    continue
                seen.add(parsed.e164)

                # Checked at ingest as well as at dial time. Belt and braces: a number
                # on the opt-out list should not even be sitting in a campaign table.
                if ledger.contains(parsed.e164):
                    report.opted_out += 1
                    rejects.append({**row, "_reason": "opted_out"})
                    continue

                context = {
                    k: v for k, v in row.items()
                    if v and k not in mapping.values()
                }
                inserted = insert_voter(
                    conn,
                    id=f"{campaign_id}:{parsed.e164}",
                    campaign_id=campaign_id,
                    phone=parsed.e164,
                    name=(row.get(mapping.get("name", ""), "") or "").strip() or None,
                    ward=(row.get(mapping.get("ward", ""), "") or "").strip() or None,
                    tags=(row.get(mapping.get("tags", ""), "") or "").strip() or None,
                    context=context or None,
                    source=source or csv_path.name,
                )
                if inserted:
                    report.accepted += 1
                else:
                    report.duplicate_in_db += 1
                    rejects.append({**row, "_reason": "duplicate_in_db"})

    if rejects_path and rejects:
        rejects_path.parent.mkdir(parents=True, exist_ok=True)
        keys = list({k for r in rejects for k in r})
        with rejects_path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=keys)
            writer.writeheader()
            writer.writerows(rejects)

    return report


def main() -> None:
    setup()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("csv", type=Path)
    p.add_argument("--db", type=Path, default=Path("out/campaign.db"))
    p.add_argument("--campaign", required=True)
    p.add_argument("--map", dest="column_map", help="phone=Mobile,ward=Prabhag")
    p.add_argument("--rejects", type=Path, help="where to write dropped rows (default: alongside --db)")
    args = p.parse_args()

    rejects = args.rejects or args.db.parent / f"rejects_{args.csv.stem}.csv"
    report = ingest(
        args.csv, args.db, args.campaign,
        column_map=parse_map_arg(args.column_map), rejects_path=rejects,
    )
    print(f"\n{args.csv.name} -> {args.db}\n")
    print(report.summary())
    if report.dropped:
        print(f"\n  dropped rows written to {rejects}")
    print()


if __name__ == "__main__":
    main()
