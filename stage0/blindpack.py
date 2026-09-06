"""Stage 0 — build the blind-test pack that 5-10 people from Sambhajinagar rate.

    python -m stage0.blindpack --in out/bakeoff --lang mr-IN \
        --control samples/viraj_mr_clean.wav

Three things this does that a naive pack does not, and each of them changes the answer:

1. **The control is degraded identically.** The real recording goes through the same
   G.711 round trip as the clones. Otherwise raters spot it in two seconds by audio
   quality alone, and every clone scores low against a studio reference that no voter
   will ever hear.

2. **The control sets the ceiling, not 5/5.** A real human voice through a phone line
   does not score 5 on "sounds like him" — it typically loses a point to the codec. A
   clone at 3.8 against a control at 4.2 is doing far better than 3.8/5 suggests, and
   the report reads the scores that way.

3. **Opaque filenames, shuffled order, and the key held separately.** `key.csv` is
   written outside the folder you send out, and is gitignored. If a rater can infer
   the vendor, the test measures branding, not voice.
"""

from __future__ import annotations

import argparse
import csv
import random
import shutil
from pathlib import Path

from voiceai.audio import degrade_to_telephony
from voiceai.config import OUT_DIR
from voiceai.console import setup

DIMENSIONS = ("sounds_like_him", "natural", "understandable")


def collect(in_dir: Path, lang: str) -> list[tuple[str, str, Path]]:
    """-> [(provider, turn, telephony_wav)]"""
    found: list[tuple[str, str, Path]] = []
    for provider_dir in sorted(p for p in in_dir.iterdir() if p.is_dir()):
        tele = provider_dir / lang / "tele"
        if not tele.is_dir():
            continue
        for wav in sorted(tele.glob("*.wav")):
            found.append((provider_dir.name, wav.stem, wav))
    return found


def main() -> None:
    setup()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--in", dest="in_dir", type=Path, default=OUT_DIR / "bakeoff")
    p.add_argument("--lang", default="mr-IN")
    p.add_argument("--out", type=Path, default=OUT_DIR / "blindtest")
    p.add_argument("--control", type=Path,
                   help="the speaker's real recording — include it or the scores mean nothing")
    p.add_argument("--seed", type=int, default=20260906)
    args = p.parse_args()

    items = collect(args.in_dir, args.lang)
    if not items:
        raise SystemExit(f"no telephony audio under {args.in_dir} for {args.lang}. Run stage0.bakeoff first.")

    audio_dir = args.out / args.lang / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    if args.control and args.control.exists():
        control_tele = args.out / args.lang / "_control_tele.wav"
        degrade_to_telephony(args.control, control_tele)
        items.append(("CONTROL", "control", control_tele))
    else:
        print("  !! no --control given. Without the speaker's real voice through the same\n"
              "     phone-line degradation there is no ceiling to compare clones against,\n"
              "     and a 3.8 is uninterpretable.\n")

    rng = random.Random(args.seed)
    rng.shuffle(items)

    key_rows, sheet_rows = [], []
    for i, (provider, turn, src) in enumerate(items, 1):
        opaque = f"{args.lang.split('-')[0]}_{i:03d}.wav"
        shutil.copyfile(src, audio_dir / opaque)
        key_rows.append({"file": opaque, "provider": provider, "turn": turn, "source": str(src)})
        sheet_rows.append({"file": opaque, **{d: "" for d in DIMENSIONS}, "comment": ""})

    # Key lives OUTSIDE the folder that gets sent to raters.
    key_path = args.out / f"key_{args.lang}.csv"
    with key_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["file", "provider", "turn", "source"])
        w.writeheader()
        w.writerows(key_rows)

    sheet_path = args.out / args.lang / "scoring_sheet.csv"
    with sheet_path.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=["file", *DIMENSIONS, "comment"])
        w.writeheader()
        w.writerows(sheet_rows)

    (args.out / args.lang / "INSTRUCTIONS.txt").write_text(
        _instructions(len(items)), encoding="utf-8"
    )

    print(f"\n  {len(items)} clips -> {audio_dir}")
    print(f"  scoring sheet -> {sheet_path}")
    print(f"  KEY (do not send) -> {key_path}")
    print(f"\n  Send the folder {args.out / args.lang} to raters. Keep the key.")
    print(f"  Then: python -m stage0.report --key {key_path} --scores <filled sheet(s)>\n")


def _instructions(n: int) -> str:
    return f"""\
ऐकून गुण द्या / सुनकर अंक दीजिए

{n} short audio clips are in the `audio` folder. Please play them ON YOUR PHONE,
in order, and fill one row per clip in scoring_sheet.csv.

Three scores, each 1 to 5:

  sounds_like_him   1 = clearly a different person, 5 = definitely the same person
  natural           1 = robotic, 5 = a normal person speaking normally
  understandable    1 = I had to guess words, 5 = every word was clear

Please also write anything you noticed in `comment` — a wrong accent, an odd word,
a strange pause. Those comments are more useful than the numbers.

Do not discuss the clips with other raters before you finish.
The clips are deliberately low quality: they are meant to sound like a phone call.
"""


if __name__ == "__main__":
    main()
