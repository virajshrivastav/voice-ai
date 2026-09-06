"""Constituency report.

    python -m insights.report --db out/campaign.db --campaign csn-central-2026q3

Produces one self-contained HTML file and one CSV. No server, no CDN, no fonts to
fetch — it opens on a phone, prints on A4, and can be forwarded as an attachment. That
is deliberate: the person who needs to read this runs an MLA's office, not a laptop
with a dev server on it.

The argument this file makes, and the reason it exists before any voice clone does:
what an MLA's office buys is not a clever phone call, it is **a ranked list of who in
which ward has which problem, with a number to call back**. That list can be built,
shown and priced today. `docs/07_HANDOFF.md §5 Q3` makes the same point commercially —
pricing per minute invites a comparison against ₹0.50/call blasts that we lose, while
pricing on the grievance list does not.

Compliance is reported as a first-class section rather than a footnote. A call with no
logged disclosure is not a call the office can defend, so it is counted and shown, not
averaged away.
"""

from __future__ import annotations

import argparse
import csv
import html
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from campaign.db import connect
from campaign.dialer import IST, Dialer
from voiceai.console import setup

PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2, None: 3}

FIELD_LABELS = {
    "water": "Water supply",
    "roads": "Roads",
    "lights": "Street lights",
    "scheme_issue": "Government schemes",
}
VALUE_LABELS = {
    "ok": "No problem", "irregular": "Irregular", "none": "None at all",
    "bad": "Poor", "very_bad": "Very poor", "other": "Other",
    "unanswered": "Not answered", "ration": "Ration", "pension": "Pension",
    "ladki_bahin": "Ladki Bahin", "housing": "Housing",
}
# Values that mean "this person has a problem", used for the ward ranking.
PROBLEM_VALUES = {
    "water": {"irregular", "none", "other"},
    "roads": {"bad", "very_bad"},
    "lights": {"bad"},
    "scheme_issue": {"ration", "pension", "ladki_bahin", "housing", "other"},
}


# -- queries ---------------------------------------------------------------------


def answer_breakdown(conn: sqlite3.Connection, campaign_id: str) -> dict[str, Counter]:
    rows = conn.execute(
        """SELECT a.field, a.label, COUNT(*) AS n
             FROM answer a JOIN call c ON c.id = a.call_id
            WHERE c.campaign_id = ? AND a.field IN ('water','roads','lights','scheme_issue')
            GROUP BY a.field, a.label""",
        (campaign_id,),
    ).fetchall()
    out: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        out[r["field"]][r["label"]] = r["n"]
    return out


def ward_breakdown(conn: sqlite3.Connection, campaign_id: str) -> list[dict]:
    rows = conn.execute(
        """SELECT v.ward, a.field, a.label, COUNT(*) AS n
             FROM answer a
             JOIN call  c ON c.id = a.call_id
             JOIN voter v ON v.id = a.voter_id
            WHERE c.campaign_id = ? AND v.ward IS NOT NULL
            GROUP BY v.ward, a.field, a.label""",
        (campaign_id,),
    ).fetchall()

    wards: dict[str, dict] = defaultdict(
        lambda: {"answered": 0, "problems": 0, "fields": defaultdict(Counter)}
    )
    for r in rows:
        if r["field"] not in PROBLEM_VALUES:
            continue
        w = wards[r["ward"]]
        w["fields"][r["field"]][r["label"]] = r["n"]
        if r["label"] != "unanswered":
            w["answered"] += r["n"]
            if r["label"] in PROBLEM_VALUES[r["field"]]:
                w["problems"] += r["n"]

    reached = {
        r["ward"]: r["n"]
        for r in conn.execute(
            """SELECT v.ward, COUNT(DISTINCT c.id) AS n
                 FROM call c JOIN voter v ON v.id = c.voter_id
                WHERE c.campaign_id = ? AND c.outcome = 'completed'
                GROUP BY v.ward""",
            (campaign_id,),
        ).fetchall()
    }

    out = []
    for ward, w in wards.items():
        rate = (w["problems"] / w["answered"]) if w["answered"] else 0.0
        out.append(
            {
                "ward": ward,
                "completed": reached.get(ward, 0),
                "answered": w["answered"],
                "problems": w["problems"],
                "problem_rate": rate,
                "fields": w["fields"],
            }
        )
    # Worst first. This ordering is the point of the table.
    out.sort(key=lambda w: (-w["problem_rate"], -w["problems"]))
    return out


# Q4 is open-ended, so "nothing else, that's all" is a perfectly good answer to it and
# gets stored like any other. It is not a callback though, and an office working list
# that opens with twenty rows of "everything is fine" is a list nobody works from.
#
# This is a DISPLAY filter. The rows stay in the database, and `nothing_further()`
# reports how many there were, so the count is visible rather than quietly dropped.
NO_ISSUE_PATTERNS = (
    "काही नाही", "काहीच नाही", "एवढंच", "एवढेच", "सगळं ठीक", "सगळे ठीक",
    "काही अडचण नाही", "कोणतीही अडचण नाही", "कुछ नहीं", "सब ठीक", "बस इतना",
)


def _is_no_issue(text: str | None) -> bool:
    t = (text or "").strip()
    return bool(t) and any(pattern in t for pattern in NO_ISSUE_PATTERNS)


def nothing_further(conn: sqlite3.Connection, campaign_id: str) -> int:
    return sum(1 for g in _all_open_answers(conn, campaign_id) if _is_no_issue(g["raw_text"]))


def _all_open_answers(conn: sqlite3.Connection, campaign_id: str) -> list[dict]:
    rows = conn.execute(
        """SELECT v.name, v.ward, v.phone, a.label, a.priority, a.raw_text, c.started_at
             FROM answer a
             JOIN call  c ON c.id = a.call_id
             JOIN voter v ON v.id = a.voter_id
            WHERE c.campaign_id = ? AND a.field = 'open_grievance'
              AND a.raw_text IS NOT NULL AND TRIM(a.raw_text) != ''""",
        (campaign_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def grievances(conn: sqlite3.Connection, campaign_id: str) -> list[dict]:
    """The callback list: everyone who actually raised something, urgent first."""
    items = [g for g in _all_open_answers(conn, campaign_id) if not _is_no_issue(g["raw_text"])]
    items.sort(key=lambda g: (PRIORITY_ORDER.get(g["priority"], 3), g["ward"] or ""))
    return items


def compliance(conn: sqlite3.Connection, campaign_id: str) -> dict:
    total = conn.execute(
        "SELECT COUNT(*) FROM call WHERE campaign_id = ?", (campaign_id,)
    ).fetchone()[0]
    no_disclosure = conn.execute(
        "SELECT COUNT(*) FROM call WHERE campaign_id = ? "
        "AND (disclosure_played_at IS NULL OR disclosure_played_at = '')",
        (campaign_id,),
    ).fetchone()[0]
    no_dnd = conn.execute(
        "SELECT COUNT(*) FROM voter WHERE campaign_id = ? AND dnd_checked_at IS NULL",
        (campaign_id,),
    ).fetchone()[0]
    no_consent = conn.execute(
        "SELECT COUNT(*) FROM call WHERE campaign_id = ? "
        "AND (voice_consent_ref IS NULL OR voice_consent_ref = '')",
        (campaign_id,),
    ).fetchone()[0]
    optouts = conn.execute("SELECT COUNT(*) FROM optout").fetchone()[0]
    return {
        "calls": total,
        "missing_disclosure": no_disclosure,
        "missing_dnd": no_dnd,
        "missing_consent_ref": no_consent,
        "optout_ledger": optouts,
    }


def economics(conn: sqlite3.Connection, campaign_id: str) -> dict:
    row = conn.execute(
        """SELECT COUNT(*) AS calls, COALESCE(SUM(duration_s),0) AS secs,
                  COALESCE(SUM(cost_inr),0) AS cost
             FROM call WHERE campaign_id = ? AND duration_s > 0""",
        (campaign_id,),
    ).fetchone()
    minutes = row["secs"] / 60
    return {
        "connected_calls": row["calls"],
        "minutes": minutes,
        "cost": row["cost"],
        "cost_per_min": (row["cost"] / minutes) if minutes else 0.0,
        "avg_duration_s": (row["secs"] / row["calls"]) if row["calls"] else 0.0,
    }


# -- rendering -------------------------------------------------------------------

CSS = """
:root{--bg:#fbfaf8;--fg:#1a1a1a;--muted:#666;--line:#e2ded8;--card:#fff;
--accent:#8c2f1f;--ok:#2e6b4f;--warn:#a8641b;--bar:#c9c2b6;--bar2:#8c2f1f}
@media(prefers-color-scheme:dark){:root{--bg:#16151a;--fg:#eceaea;--muted:#9c9797;
--line:#2f2c33;--card:#1e1d23;--accent:#e8836d;--ok:#6cc39a;--warn:#e0a35a;
--bar:#3a3740;--bar2:#e8836d}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.55 "Nirmala UI","Noto Sans Devanagari",-apple-system,Segoe UI,Roboto,sans-serif}
.wrap{max-width:1000px;margin:0 auto;padding:24px 18px 64px}
.synthetic{background:var(--warn);color:#fff;padding:10px 16px;border-radius:6px;
font-weight:600;margin-bottom:24px;font-size:14px}
h1{font-size:26px;margin:0 0 4px;letter-spacing:-.02em}
h2{font-size:17px;margin:40px 0 12px;padding-bottom:7px;border-bottom:1px solid var(--line)}
.sub{color:var(--muted);font-size:14px;margin-bottom:8px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:18px 0}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:14px}
.card .n{font-size:26px;font-weight:650;letter-spacing:-.02em}
.card .k{color:var(--muted);font-size:12.5px;margin-top:2px}
table{width:100%;border-collapse:collapse;font-size:14px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:600;font-size:12.5px;text-transform:uppercase;letter-spacing:.04em}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
.bar{background:var(--bar);height:9px;border-radius:5px;min-width:2px}
.bar.hi{background:var(--bar2)}
.pill{display:inline-block;padding:1px 8px;border-radius:20px;font-size:12px;font-weight:600}
.p-high{background:var(--accent);color:#fff}
.p-medium{background:var(--warn);color:#fff}
.p-low{background:var(--bar);color:var(--fg)}
.good{color:var(--ok);font-weight:600}
.bad{color:var(--accent);font-weight:600}
.verbatim{font-size:14px}
.foot{margin-top:48px;padding-top:14px;border-top:1px solid var(--line);
color:var(--muted);font-size:12px}
code{font-family:ui-monospace,Consolas,monospace;font-size:12px}
@media print{body{background:#fff}.synthetic{border:2px solid #000}}
"""


def esc(x) -> str:
    return html.escape(str(x if x is not None else ""))


def card(n, k) -> str:
    return f'<div class="card"><div class="n">{n}</div><div class="k">{esc(k)}</div></div>'


def bar_row(label: str, n: int, total: int, highlight: bool = False) -> str:
    pct = (100 * n / total) if total else 0
    cls = "bar hi" if highlight else "bar"
    return (
        f"<tr><td>{esc(label)}</td>"
        f'<td class="num">{n:,}</td><td class="num">{pct:.0f}%</td>'
        f'<td style="width:45%"><div class="{cls}" style="width:{max(pct,0.8):.1f}%"></div></td></tr>'
    )


def render(conn: sqlite3.Connection, campaign_id: str) -> str:
    camp = conn.execute("SELECT * FROM campaign WHERE id = ?", (campaign_id,)).fetchone()
    if camp is None:
        raise SystemExit(f"no campaign {campaign_id!r} in this database")
    pol = conn.execute(
        "SELECT * FROM politician WHERE id = ?", (camp["politician_id"],)
    ).fetchone()

    funnel = Dialer(conn).funnel(campaign_id)
    answers = answer_breakdown(conn, campaign_id)
    wards = ward_breakdown(conn, campaign_id)
    griev = grievances(conn, campaign_id)
    comp = compliance(conn, campaign_id)
    econ = economics(conn, campaign_id)

    dialled = funnel["dialled"] or 1
    connected = sum(v for k, v in funnel.items() if k.startswith("outcome_")) - funnel.get(
        "outcome_no_answer", 0
    )
    completed = funnel.get("outcome_completed", 0)

    p: list[str] = []
    p.append('<div class="synthetic">SYNTHETIC DEMO DATA — every name, phone number and '
             'grievance below was generated by <code>campaign.simulate</code>. '
             'No real resident is described here.</div>')

    p.append(f"<h1>{esc(camp['name'])}</h1>")
    p.append(f'<div class="sub">{esc(pol["constituency"] if pol else "")} · '
             f'{esc(camp["lang"])} · generated '
             f'{datetime.now(IST).strftime("%d %b %Y")} IST</div>')

    # -- headline
    p.append('<div class="grid">')
    p.append(card(f"{funnel['voters']:,}", "Numbers in list"))
    p.append(card(f"{connected:,}", "Reached a person"))
    p.append(card(f"{completed:,}", "Full conversations"))
    p.append(card(f"{len(griev):,}", "Grievances recorded"))
    p.append("</div>")

    # -- the grievance list, first because it is the product
    p.append("<h2>Grievance list</h2>")
    p.append('<div class="sub">Every resident who raised something, highest priority '
             'first. This is the working list for the office — each row is a callback.</div>')
    if griev:
        p.append('<div class="scroll"><table><thead><tr>'
                 "<th>Priority</th><th>Name</th><th>Ward / area</th><th>Phone</th>"
                 "<th>What they said</th></tr></thead><tbody>")
        for g in griev[:120]:
            pr = g["priority"] or "low"
            p.append(
                f'<tr><td><span class="pill p-{esc(pr)}">{esc(pr)}</span></td>'
                f"<td>{esc(g['name'])}</td><td>{esc(g['ward'])}</td>"
                f"<td class='num'>{esc(g['phone'])}</td>"
                f"<td class='verbatim'>{esc(g['raw_text'])}</td></tr>"
            )
        p.append("</tbody></table></div>")
        if len(griev) > 120:
            p.append(f'<div class="sub">Showing 120 of {len(griev):,}. '
                     "The CSV alongside this file has all of them.</div>")
        quiet = nothing_further(conn, campaign_id)
        if quiet:
            p.append(f'<div class="sub">A further {quiet:,} people finished the call '
                     "saying they had nothing else to raise. They are in the data but "
                     "not on this list.</div>")
    else:
        p.append('<div class="sub">None recorded.</div>')

    # -- wards
    p.append("<h2>Wards, worst first</h2>")
    p.append('<div class="sub">Share of answered questions that reported a problem. '
             'Where to send someone next.</div>')
    p.append('<div class="scroll"><table><thead><tr><th>Ward / area</th>'
             '<th class="num">Conversations</th><th class="num">Problem rate</th>'
             "<th></th></tr></thead><tbody>")
    worst = wards[0]["problem_rate"] if wards else 1
    for w in wards:
        width = 100 * w["problem_rate"] / worst if worst else 0
        p.append(
            f"<tr><td>{esc(w['ward'])}</td>"
            f"<td class='num'>{w['completed']:,}</td>"
            f"<td class='num'>{100 * w['problem_rate']:.0f}%</td>"
            f"<td style='width:40%'><div class='bar hi' style='width:{max(width,1):.1f}%'></div></td></tr>"
        )
    p.append("</tbody></table></div>")

    # -- answers
    p.append("<h2>What people said</h2>")
    for field, label in FIELD_LABELS.items():
        counts = answers.get(field)
        if not counts:
            continue
        total = sum(counts.values())
        p.append(f"<h3 style='font-size:14px;margin:22px 0 6px'>{esc(label)}</h3>")
        p.append("<table><tbody>")
        for value, n in counts.most_common():
            problem = value in PROBLEM_VALUES.get(field, set())
            p.append(bar_row(VALUE_LABELS.get(value, value), n, total, highlight=problem))
        p.append("</tbody></table>")

    # -- funnel
    p.append("<h2>Call outcomes</h2>")
    p.append("<table><tbody>")
    for key, n in sorted(
        ((k.replace("outcome_", ""), v) for k, v in funnel.items() if k.startswith("outcome_")),
        key=lambda kv: -kv[1],
    ):
        p.append(bar_row(key.replace("_", " "), n, dialled))
    p.append("</tbody></table>")

    # -- compliance
    p.append("<h2>Compliance</h2>")
    p.append('<div class="sub">These are obligations, not metrics. Any non-zero '
             "exception below is a call the office cannot defend.</div>")
    p.append("<table><tbody>")
    for label, n, good_when_zero in (
        ("Calls with no logged AI disclosure", comp["missing_disclosure"], True),
        ("Numbers never preference-checked", comp["missing_dnd"], True),
        ("Calls with no voice-consent reference", comp["missing_consent_ref"], True),
        ("Numbers on the opt-out ledger", comp["optout_ledger"], False),
    ):
        cls = "good" if (n == 0 and good_when_zero) else ("bad" if good_when_zero else "")
        p.append(f"<tr><td>{esc(label)}</td>"
                 f"<td class='num {cls}'>{n:,}</td></tr>")
    p.append("</tbody></table>")

    # -- economics
    p.append("<h2>Cost</h2>")
    p.append('<div class="grid">')
    p.append(card(f"₹{econ['cost']:,.0f}", "Total cost"))
    p.append(card(f"₹{econ['cost_per_min']:.2f}", "Per connected minute"))
    p.append(card(f"{econ['minutes']:,.0f}", "Connected minutes"))
    p.append(card(f"{econ['avg_duration_s']:.0f}s", "Average call"))
    p.append("</div>")
    p.append('<div class="sub">Cost is modelled from <code>voiceai.costs</code> against '
             "the turns that actually occurred, not measured on a live line. Stage 2 "
             "replaces it with real vendor invoices.</div>")

    p.append(
        f'<div class="foot">Campaign <code>{esc(campaign_id)}</code> · '
        f'script v{esc(camp["script_version"])} · answer bank v{esc(camp["bank_version"])} · '
        f'approved-speech manifest <code>{esc((camp["manifest_sha"] or "")[:16])}</code><br>'
        "Every sentence spoken in this campaign came from that manifest. "
        "Nothing was generated at call time.</div>"
    )

    body = "\n".join(p)
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{esc(camp['name'])}</title><style>{CSS}</style></head>"
        f"<body><div class='wrap'>{body}</div></body></html>"
    )


def write_grievance_csv(conn: sqlite3.Connection, campaign_id: str, path: Path) -> int:
    rows = grievances(conn, campaign_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["priority", "name", "ward", "phone", "category", "grievance", "called_at"])
        for g in rows:
            w.writerow([g["priority"] or "low", g["name"], g["ward"], g["phone"],
                        g["label"] or "", g["raw_text"], g["started_at"]])
    return len(rows)


def main() -> None:
    setup()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", type=Path, default=Path("out/campaign.db"))
    p.add_argument("--campaign", required=True)
    p.add_argument("--out", type=Path, default=Path("out/report"))
    args = p.parse_args()

    conn = connect(args.db)
    args.out.mkdir(parents=True, exist_ok=True)
    html_path = args.out / f"{args.campaign}.html"
    csv_path = args.out / f"{args.campaign}_grievances.csv"

    html_path.write_text(render(conn, args.campaign), encoding="utf-8")
    n = write_grievance_csv(conn, args.campaign, csv_path)

    print(f"\n  report     {html_path}")
    print(f"  grievances {csv_path}  ({n:,} rows)\n")


if __name__ == "__main__":
    main()
