"""Stage 0 — clone the same voice on every vendor and synthesise the same sentences.

Usage (works today, with no keys and no voice sample):

    python -m stage0.bakeoff --lang mr-IN --providers mock

and later, when a sample and a key exist:

    python -m stage0.bakeoff --lang mr-IN --providers smallest \
        --sample samples/viraj_mr_clean.wav

Every output is written twice: `raw/` at the vendor's native rate, and `tele/` after a
G.711 round trip. Only `tele/` may be used to judge a vendor. The one blind evaluation
worth trusting found the ranking inverts between full-band and 8 kHz, so scoring clean
WAVs is not a shortcut, it is a way to pick the wrong vendor.
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict
from pathlib import Path

from voiceai import build
from voiceai.audio import FfmpegMissingError, degrade_to_telephony
from voiceai.config import OUT_DIR, load_settings
from voiceai.console import setup
from voiceai.tts import PROVIDER_CAPABILITIES, get_tts

# The sentence set: the fixed turns a voter actually hears, not lorem ipsum. Using the
# real script means a rater is judging the product, and it warms the cache for free.
SENTENCE_TURNS = ("OPEN", "Q1", "Q2", "Q3", "Q4", "CLOSE")


def provider_kwargs(name: str, settings) -> dict:
    return {
        "mock": {},
        "smallest": {"api_key": settings.smallest_api_key},
        "gnani": {"api_key": settings.gnani_api_key},
        "sarvam": {"api_key": settings.sarvam_api_key},
    }.get(name, {})


def _clone(tts, sample: Path, lang: str, transcript: str | None) -> str:
    """Vendors that care about the clip's language take `lang`; the base signature
    does not, so pass it only where it is accepted."""
    try:
        return tts.clone(sample, display_name=f"bakeoff-{lang}", transcript=transcript, lang=lang)
    except TypeError:
        return tts.clone(sample, display_name=f"bakeoff-{lang}", transcript=transcript)


def run_provider(
    name: str,
    lang: str,
    sentences: list[tuple[str, str]],
    out_root: Path,
    *,
    sample: Path | None,
    voice_id: str | None,
    transcript: str | None,
    skip_degrade: bool,
    settings,
) -> list[dict]:
    tts = get_tts(name, **provider_kwargs(name, settings))

    if voice_id:
        vid = voice_id
        cloned = False
    elif sample:
        print(f"  cloning from {sample.name} …")
        vid = _clone(tts, sample, lang, transcript)
        cloned = True
        print(f"  voice_id = {vid}")
    else:
        raise SystemExit(
            f"{name}: need either --voice-id or --sample. With no voice sample this "
            f"vendor has nothing to clone — record 3 minutes of clean speech first "
            f"(docs/04_BUILD_PLAN.md Stage 0, step 1)."
        )

    raw_dir = out_root / name / lang / "raw"
    tele_dir = out_root / name / lang / "tele"
    raw_dir.mkdir(parents=True, exist_ok=True)
    tele_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    for turn_id, text in sentences:
        result = tts.synth(text, vid, lang)
        raw_path = raw_dir / f"{turn_id}.wav"
        raw_path.write_bytes(result.audio)

        tele_path = tele_dir / f"{turn_id}.wav"
        if skip_degrade:
            tele_path = raw_path
        else:
            try:
                degrade_to_telephony(raw_path, tele_path)
            except FfmpegMissingError as exc:
                raise SystemExit(str(exc)) from exc

        rows.append(
            {
                "provider": name,
                "lang": lang,
                "turn": turn_id,
                "voice_id": vid,
                "cloned": cloned,
                "chars": result.chars,
                "ttfb_ms": round(result.ttfb_ms or 0.0, 1),
                "total_ms": round(result.total_ms, 1),
                "cost_inr": round(result.cost_inr, 4),
                "raw": str(raw_path.relative_to(out_root)),
                "tele": str(tele_path.relative_to(out_root)),
            }
        )
        cost = f"₹{result.cost_inr:.4f}" if (result.cost_inr or name != "gnani") else "₹ n/a (unpublished)"
        print(f"    {turn_id:<12} {result.ttfb_ms or 0:>7.0f} ms ttfb   {cost}")
    return rows


def main() -> None:
    setup()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--lang", default="mr-IN")
    p.add_argument("--providers", default="mock", help="comma separated: mock,smallest,gnani,sarvam")
    p.add_argument("--sample", type=Path, help="reference audio to clone from")
    p.add_argument("--transcript", help="transcript of --sample (IndicF5-style models need it)")
    p.add_argument("--voice-id", help="skip cloning and use an existing voice id")
    p.add_argument("--out", type=Path, default=OUT_DIR / "bakeoff")
    p.add_argument("--skip-degrade", action="store_true",
                   help="do not simulate the phone line — produces a misleading ranking")
    p.add_argument("--list", action="store_true", help="show provider capabilities and exit")
    args = p.parse_args()

    if args.list:
        print("\nTTS providers\n")
        for name, cap in PROVIDER_CAPABILITIES.items():
            print(f"  {name:<10} marathi={cap.marathi:<12} cloning={cap.cloning:<12} "
                  f"streaming={str(cap.streaming):<5}")
            print(f"             {cap.note}\n")
        return

    settings = load_settings()
    script, _bank, _guard = build(args.lang, settings)
    sentences = [(t, script.turn(t).text) for t in SENTENCE_TURNS if t in script.turns]
    print(f"\n{len(sentences)} sentences, {args.lang}\n")

    if args.skip_degrade:
        print("  !! --skip-degrade: judging full-band audio. Rankings from full-band do\n"
              "     not survive 8 kHz. Use this for debugging only.\n")

    all_rows: list[dict] = []
    for name in [n.strip() for n in args.providers.split(",") if n.strip()]:
        print(f"[{name}]")
        all_rows.extend(
            run_provider(
                name, args.lang, sentences, args.out,
                sample=args.sample, voice_id=args.voice_id, transcript=args.transcript,
                skip_degrade=args.skip_degrade, settings=settings,
            )
        )
        print()

    args.out.mkdir(parents=True, exist_ok=True)
    latency_csv = args.out / f"latency_{args.lang}.csv"
    with latency_csv.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(all_rows[0]))
        writer.writeheader()
        writer.writerows(all_rows)

    (args.out / f"manifest_{args.lang}.json").write_text(
        json.dumps({"sentences": [{"turn": t, "text": x} for t, x in sentences]},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"latency table -> {latency_csv}")
    print(f"next: python -m stage0.blindpack --in {args.out} --lang {args.lang}")


if __name__ == "__main__":
    main()
