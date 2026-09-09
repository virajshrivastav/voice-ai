"""Stamp an answer bank as approved, or verify a stamp.

    python -m tools.approve_bank data/answer_bank.mr.yaml --by "Name, MLA office" --approve
    python -m tools.approve_bank data/answer_bank.mr.yaml --check

`answer_bank.py` refuses to serve a bank in production unless `approval.status ==
"approved"`, `approved_by` is set, and the stored hash matches the loaded text. This is
the only tool that should write that block; it records who approved what, and when.
"""

from __future__ import annotations

import argparse
import re
from datetime import date
from pathlib import Path

import yaml

from voiceai.answer_bank import AnswerBank
from voiceai.config import SpeakerIdentity
from voiceai.console import setup


def _bank(path: Path) -> AnswerBank:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return AnswerBank(raw, SpeakerIdentity())


def _rewrite_approval(path: Path, status: str, by: str | None, digest: str | None) -> None:
    """Edit only the four approval lines in place so comments and ordering survive."""
    text = path.read_text(encoding="utf-8")
    today = date.today().isoformat()
    subs = {
        "status": f"{status}",
        "approved_by": f'"{by}"' if by else "null",
        "approved_at": f'"{today}"' if by else "null",
        "approved_text_sha256": f'"{digest}"' if digest else "null",
    }
    for key, value in subs.items():
        pattern = re.compile(rf"^(\s+{key}:\s*)([^#\n]*)(.*)$", re.M)
        text, n = pattern.subn(lambda m: f"{m.group(1)}{value}{' ' + m.group(3).strip() if m.group(3).strip() else ''}", text, count=1)
        if n != 1:
            raise SystemExit(f"could not find `{key}:` under approval in {path}")
    path.write_text(text, encoding="utf-8")


def main() -> None:
    setup()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("bank", type=Path)
    p.add_argument("--by", help="name + role of the approver, e.g. 'R. Patil, PA to MLA'")
    p.add_argument("--approve", action="store_true")
    p.add_argument("--check", action="store_true", help="verify the stored stamp against the text")
    args = p.parse_args()

    bank = _bank(args.bank)
    digest = bank.content_hash()

    if args.check or not args.approve:
        stored = bank.approval.get("approved_text_sha256")
        print(f"{args.bank}: {len(bank.entries)} entries, status={bank.approval.get('status')}")
        print(f"  current sha256  {digest}")
        print(f"  approved sha256 {stored or '—'}")
        if stored and stored != digest:
            raise SystemExit("  MISMATCH: text changed after approval. Re-approve.")
        return

    if not args.by:
        raise SystemExit("--approve needs --by 'Name, role' — an approval without a person is not one.")
    _rewrite_approval(args.bank, "approved", args.by, digest)
    print(f"approved {args.bank} ({len(bank.entries)} entries) by {args.by}; sha256 {digest[:12]}…")
    _bank(args.bank).require_approved()
    print("re-loaded and verified.")


if __name__ == "__main__":
    main()
