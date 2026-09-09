"""Cost model.

Answers two questions the project keeps needing: what does one connected minute cost,
and what does one sweep of a constituency cost.

The headline finding this model makes visible: **telephony is the biggest line, not
the AI**, and pre-rendering removes most of what is left. docs/00_CONTEXT.md quotes
₹2.5-3.0/min, which assumes live TTS on every turn and STT billed on the whole call.
With the fixed turns cached and STT billed only on voter speech, the same rates give
roughly half that. Both are models. Stage 2 replaces them with measurements.

Every rate below carries its source. Change a rate, keep the citation.
"""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass, field

from .console import setup

USD_INR = 84.0


@dataclass(frozen=True)
class Rates:
    # Plivo Voice API, India domestic outbound, 30-second pulse (plivo.com/voice/pricing/in,
    # read 2026-09-06). SIP trunking is ₹0.60/min. Exotel is ~₹0.50/pulse, enterprise-negotiated.
    telephony_inr_per_min: float = 0.38
    telephony_pulse_seconds: int = 30

    # Sarvam STT ₹30/hour (docs.sarvam.ai pricing, 2026-09-06).
    stt_inr_per_min: float = 30.0 / 60

    # Sarvam Bulbul v3 ₹30 / 10k chars. Smallest Lightning ~$14.5/1M chars.
    tts_inr_per_char: float = 30.0 / 10_000
    tts_alt_inr_per_char: float = (14.5 * USD_INR) / 1_000_000

    # Classification only: a few hundred tokens per answer on a cheap model.
    llm_inr_per_min: float = 0.05

    # One small VM + Postgres, amortised over campaign volume.
    infra_inr_per_min: float = 0.15


@dataclass(frozen=True)
class CallShape:
    """How a call is actually spent. Defaults from docs/00_CONTEXT.md §4."""

    avg_minutes: float = 2.0
    agent_talk_fraction: float = 0.55
    chars_per_agent_minute: float = 500.0

    # Share of agent speech served from the pre-render cache. The fixed turns are
    # ~everything; only clarifications and unmatched answer-bank misses are live.
    prerendered_fraction: float = 0.90

    # Bill STT on voter audio only (streaming just the voter's turns) rather than the
    # whole call. Worth ~₹0.27/min at these rates — confirm your transport can do it.
    stt_on_voter_audio_only: bool = True


@dataclass
class Line:
    name: str
    inr_per_min: float
    note: str = ""


@dataclass
class Breakdown:
    lines: list[Line] = field(default_factory=list)

    @property
    def total(self) -> float:
        return sum(line.inr_per_min for line in self.lines)

    def table(self) -> str:
        width = max(len(line.name) for line in self.lines) + 2
        rows = [
            f"  {line.name:<{width}} ₹{line.inr_per_min:>6.3f}/min   {line.note}"
            for line in self.lines
        ]
        rows.append(f"  {'TOTAL':<{width}} ₹{self.total:>6.3f}/min")
        return "\n".join(rows)


def per_minute(
    rates: Rates | None = None,
    shape: CallShape | None = None,
    *,
    tts_vendor: str = "sarvam",
) -> Breakdown:
    r = rates or Rates()
    s = shape or CallShape()

    # Telephony: a 30-second pulse means a 2m10s call bills as 2m30s.
    pulses = math.ceil((s.avg_minutes * 60) / r.telephony_pulse_seconds)
    billed_minutes = pulses * r.telephony_pulse_seconds / 60
    telephony = (billed_minutes * r.telephony_inr_per_min) / s.avg_minutes

    stt_fraction = (1 - s.agent_talk_fraction) if s.stt_on_voter_audio_only else 1.0
    stt = r.stt_inr_per_min * stt_fraction

    per_char = r.tts_inr_per_char if tts_vendor == "sarvam" else r.tts_alt_inr_per_char
    live_chars_per_min = (
        s.chars_per_agent_minute * s.agent_talk_fraction * (1 - s.prerendered_fraction)
    )
    tts = live_chars_per_min * per_char

    return Breakdown(
        lines=[
            Line("Telephony (PSTN out)", telephony,
                 f"{pulses} × {r.telephony_pulse_seconds}s pulse"),
            Line("STT", stt,
                 "voter turns only" if s.stt_on_voter_audio_only else "full call duration"),
            Line(f"TTS ({tts_vendor}, live only)", tts,
                 f"{s.prerendered_fraction:.0%} served from cache"),
            Line("LLM (classification)", r.llm_inr_per_min, "labels only, no generation"),
            Line("Orchestrator + DB", r.infra_inr_per_min, "amortised"),
        ]
    )


@dataclass
class CampaignEstimate:
    voters: int
    pickup_rate: float
    connected_calls: int
    connected_minutes: float
    cost_per_min: float
    variable_cost: float
    failed_attempt_cost: float
    total_cost: float
    revenue_at_sell_price: float
    sell_price_per_min: float

    @property
    def margin(self) -> float:
        return self.revenue_at_sell_price - self.total_cost

    def report(self) -> str:
        return "\n".join(
            [
                f"  Voters dialled          {self.voters:,}",
                f"  Pickup rate             {self.pickup_rate:.0%}",
                f"  Connected calls         {self.connected_calls:,}",
                f"  Connected minutes       {self.connected_minutes:,.0f}",
                "",
                f"  Cost / connected min    ₹{self.cost_per_min:.2f}",
                f"  Variable cost           ₹{self.variable_cost:,.0f}",
                f"  Unanswered attempts     ₹{self.failed_attempt_cost:,.0f}",
                f"  TOTAL COST              ₹{self.total_cost:,.0f}",
                "",
                f"  Billed at ₹{self.sell_price_per_min:g}/min      ₹{self.revenue_at_sell_price:,.0f}",
                f"  Margin                  ₹{self.margin:,.0f}",
            ]
        )


def campaign(
    voters: int = 350_000,
    pickup_rate: float = 0.45,
    sell_price_per_min: float = 5.0,
    rates: Rates | None = None,
    shape: CallShape | None = None,
    *,
    tts_vendor: str = "sarvam",
    bill_unanswered: bool = False,
) -> CampaignEstimate:
    r = rates or Rates()
    s = shape or CallShape()

    connected = int(voters * pickup_rate)
    minutes = connected * s.avg_minutes
    cpm = per_minute(r, s, tts_vendor=tts_vendor).total
    variable = minutes * cpm

    # Most Indian carriers bill answered calls only. Left as a switch because it is a
    # real line item if a route bills on ring, and it is worth confirming in writing.
    failed = 0.0
    if bill_unanswered:
        failed = (voters - connected) * (r.telephony_inr_per_min * r.telephony_pulse_seconds / 60)

    return CampaignEstimate(
        voters=voters,
        pickup_rate=pickup_rate,
        connected_calls=connected,
        connected_minutes=minutes,
        cost_per_min=cpm,
        variable_cost=variable,
        failed_attempt_cost=failed,
        total_cost=variable + failed,
        revenue_at_sell_price=minutes * sell_price_per_min,
        sell_price_per_min=sell_price_per_min,
    )


def main() -> None:
    setup()
    p = argparse.ArgumentParser(description="Cost model for one connected minute and one sweep.")
    p.add_argument("--voters", type=int, default=350_000)
    p.add_argument("--pickup", type=float, default=0.45)
    p.add_argument("--minutes", type=float, default=2.0, help="average connected call length")
    p.add_argument("--prerender", type=float, default=0.90, help="fraction of agent speech cached")
    p.add_argument("--tts", choices=["sarvam", "smallest"], default="sarvam")
    p.add_argument("--sell", type=float, default=5.0, help="sell price per connected minute")
    p.add_argument("--stt-full-call", action="store_true", help="bill STT on the whole call")
    p.add_argument("--bill-unanswered", action="store_true")
    args = p.parse_args()

    shape = CallShape(
        avg_minutes=args.minutes,
        prerendered_fraction=args.prerender,
        stt_on_voter_audio_only=not args.stt_full_call,
    )

    print(f"\nPer connected minute ({args.tts} TTS, {args.prerender:.0%} pre-rendered)\n")
    print(per_minute(shape=shape, tts_vendor=args.tts).table())

    est = campaign(
        voters=args.voters,
        pickup_rate=args.pickup,
        sell_price_per_min=args.sell,
        shape=shape,
        tts_vendor=args.tts,
        bill_unanswered=args.bill_unanswered,
    )
    print(f"\nOne sweep of a constituency\n")
    print(est.report())

    naive = per_minute(
        shape=CallShape(
            avg_minutes=args.minutes, prerendered_fraction=0.0, stt_on_voter_audio_only=False
        ),
        tts_vendor=args.tts,
    ).total
    print(
        f"\n  For contrast, with no pre-render and STT on the full call: ₹{naive:.2f}/min"
        f" — that is the ₹2.5-3.0 figure in docs/00_CONTEXT.md §4.\n"
    )


if __name__ == "__main__":
    main()
