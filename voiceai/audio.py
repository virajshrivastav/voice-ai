"""Audio helpers, mostly about making studio audio sound like an Indian phone line.

The single most important function here is `degrade_to_telephony`. Every voice
judgement in this project must be made on 8 kHz μ-law audio, because that is what the
voter hears, and because the one blind evaluation we trust (Josh Talks, 11,902
telephony votes) found rankings *invert* between full-band and 8 kHz — ElevenLabs
wins at full-band and drops 19 points at 8 kHz. Judging clones on clean WAVs would
pick the wrong vendor.
"""

from __future__ import annotations

import contextlib
import shutil
import struct
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path


class FfmpegMissingError(RuntimeError):
    pass


def require_ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise FfmpegMissingError(
            "ffmpeg not found on PATH. It is needed to simulate the phone line; install "
            "it (winget install Gyan.FFmpeg) or pass --skip-degrade to work on full-band "
            "audio only, which will give you the wrong vendor ranking."
        )
    return exe


def degrade_to_telephony(src: Path, dst: Path, *, keep_8k: bool = False) -> Path:
    """G.711 round trip: resample to 8 kHz mono μ-law, then back up to 16 kHz.

    Going back up to 16 kHz matters for the blind test — raters play these on phones
    and laptops, and a raw 8 kHz file can be judged as "bad recording" rather than
    "bad voice". `keep_8k=True` skips the upsample when you want the true wire format.
    """
    ffmpeg = require_ffmpeg()
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(".8k.wav")

    _run([ffmpeg, "-y", "-loglevel", "error", "-i", str(src),
          "-ar", "8000", "-ac", "1", "-c:a", "pcm_mulaw", str(tmp)])

    if keep_8k:
        tmp.replace(dst)
        return dst

    _run([ffmpeg, "-y", "-loglevel", "error", "-i", str(tmp),
          "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(dst)])
    tmp.unlink(missing_ok=True)
    return dst


def _run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {' '.join(cmd[:4])}…\n{proc.stderr.strip()}")


@dataclass(frozen=True)
class AudioInfo:
    seconds: float
    sample_rate: int
    channels: int
    frames: int


def probe_wav(path: Path) -> AudioInfo:
    with contextlib.closing(wave.open(str(path), "rb")) as w:
        rate = w.getframerate()
        frames = w.getnframes()
        return AudioInfo(
            seconds=frames / rate if rate else 0.0,
            sample_rate=rate,
            channels=w.getnchannels(),
            frames=frames,
        )


def write_wav(path: Path, pcm16: bytes, sample_rate: int, channels: int = 1) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.closing(wave.open(str(path), "wb")) as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm16)
    return path


def silence_wav(path: Path, seconds: float, sample_rate: int = 16000) -> Path:
    n = int(seconds * sample_rate)
    return write_wav(path, b"".join(struct.pack("<h", 0) for _ in range(n)), sample_rate)
