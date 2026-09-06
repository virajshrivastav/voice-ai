"""Stage 0 — score the blind test and apply the decision rule.

    python -m stage0.report --key out/blindtest/key_mr-IN.csv \
        --scores out/blindtest/mr-IN/filled/*.csv

The decision rule from docs/04_BUILD_PLAN.md: proceed with the vendor whose telephony
scores are `sounds_like_him >= 3.5` and `understandable >= 4`; otherwise stop and
rethink.

This report reads those thresholds against the CONTROL rather than against 5.0. If the
speaker's own recording only scores 4.1 for "sounds like him" through a phone line —
and it usually does, because the codec eats the timbre — then a clone at 3.6 has
recovered 88% of what a real call sounds like, and calling that a failure would be a
measurement error, not a product finding.
"""

from __future__ import annotations

import argparse
import csv
import glob
import statistics
from collections import defaultdict
from pathlib import Path

from voiceai.console import setup

DIMENSIONS = ("sounds_like_him", "natural", "understandable")
THRESHOLDS = {"sounds_like_him": 3.5, "understandable": 4.0}


def load_key(path: Path) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8") as fh:
        return {r["file"]: r for r in csv.DictReader(fh)}


def load_scores(patterns: list[str]) -> list[dict]:
    rows: list[dict] = []
    for pattern in patterns:
        for match in glob.glob(pattern):
            with open(match, encoding="utf-8-sig") as fh:
                for r in csv.DictReader(fh):
                    r["_rater"] = Path(match).stem
                    rows.append(r)
    return rows


def _num(value: str) -> float | None:
    try:
        f = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return f if 1.0 <= f <= 5.0 else None


def main() -> None:
    setup()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--key", type=Path, required=True)
    p.add_argument("--scores", nargs="+", required=True, help="filled scoring sheets (globs ok)")
    args = p.parse_args()

    key = load_key(args.key)
    rows = load_scores(args.scores)
    if not rows:
        raise SystemExit(f"no score rows matched {args.scores}")

    # provider -> dimension -> [scores]
    data: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    raters: set[str] = set()
    skipped = 0
    for row in rows:
        entry = key.get(row.get("file", ""))
        if not entry:
            skipped += 1
            continue
        raters.add(row["_rater"])
        for dim in DIMENSIONS:
            value = _num(row.get(dim, ""))
            if value is not None:
                data[entry["provider"]][dim].append(value)

    control = data.get("CONTROL", {})
    print(f"\n  {len(raters)} raters · {len(rows) - skipped} scored clips"
          + (f" · {skipped} unmatched rows ignored" if skipped else ""))

    if control:
        print("\n  CONTROL (the speaker's real voice, same phone-line degradation)")
        for dim in DIMENSIONS:
            print(f"    {dim:<20} {_fmt(control.get(dim, []))}")
        print("\n  Read every clone against those numbers, not against 5.0.\n")
    else:
        print("\n  !! No CONTROL clips. Absolute scores below are not interpretable —\n"
              "     rerun blindpack with --control.\n")

    print(f"  {'provider':<12} " + " ".join(f"{d:<18}" for d in DIMENSIONS) + " verdict")
    print("  " + "-" * 78)

    verdicts: list[tuple[str, float]] = []
    for provider in sorted(p for p in data if p != "CONTROL"):
        dims = data[provider]
        cells = " ".join(f"{_fmt(dims.get(d, [])):<18}" for d in DIMENSIONS)
        verdict, score = _verdict(dims, control)
        print(f"  {provider:<12} {cells} {verdict}")
        verdicts.append((provider, score))

    print()
    if verdicts:
        best, score = max(verdicts, key=lambda v: v[1])
        if score > 0:
            print(f"  Recommended vendor: {best}\n")
        else:
            print("  No vendor clears the bar. Options, in order of cost:\n"
                  "    1. Re-record the reference sample — clean room, Marathi, 3+ minutes.\n"
                  "       Most 'bad clone' results are bad reference audio.\n"
                  "    2. Try a vendor not yet tested (Sarvam enterprise, IndicF5 on a GPU).\n"
                  "    3. Reconsider the product: a named human-recorded IVR with the same\n"
                  "       two-way logic still collects the same answer data.\n")


def _verdict(dims: dict[str, list[float]], control: dict[str, list[float]]) -> tuple[str, float]:
    parts, ok = [], True
    for dim, floor in THRESHOLDS.items():
        values = dims.get(dim, [])
        if not values:
            return "no data", -1.0
        mean = statistics.fmean(values)
        passed = mean >= floor
        ok = ok and passed
        ctrl = control.get(dim, [])
        if ctrl:
            pct = 100 * mean / statistics.fmean(ctrl)
            parts.append(f"{dim.split('_')[0]} {pct:.0f}% of control")
        else:
            parts.append(f"{dim.split('_')[0]} {mean:.2f}")
    label = "PASS" if ok else "fail"
    score = statistics.fmean(
        [statistics.fmean(dims[d]) for d in THRESHOLDS if dims.get(d)]
    ) if ok else -1.0
    return f"{label} ({', '.join(parts)})", score


def _fmt(values: list[float]) -> str:
    if not values:
        return "—"
    mean = statistics.fmean(values)
    sd = statistics.stdev(values) if len(values) > 1 else 0.0
    return f"{mean:.2f} ±{sd:.2f} (n={len(values)})"


if __name__ == "__main__":
    main()
