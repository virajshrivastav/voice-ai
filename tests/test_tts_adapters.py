"""Vendor adapters, tested against the request shapes in the vendors' current docs.

These do not prove the vendors accept the requests — only a live key does that. They
prove the adapters send what the docs (read 2026-09-09) say to send, and that a doc
change shows up as a failing test here rather than as a silent 400 on bake-off day.
"""

from __future__ import annotations

import json
import struct
import wave
from pathlib import Path

import httpx
import pytest

from voiceai.audio import prepare_reference_clip, probe_wav, require_ffmpeg
from voiceai.tts import get_tts
from voiceai.tts.gnani import CLONE_MODEL as GNANI_VC_MODEL, HANDLE_PREFIX, GnaniTTS
from voiceai.tts.smallest import CLONE_MODEL as SMALLEST_CLONE_MODEL, TTS_MODEL, SmallestTTS

WAV_HEADER = b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00"


def _sample_wav(path: Path, seconds: float = 90.0, rate: int = 44100) -> Path:
    n = int(seconds * rate)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        # A quiet tone so ffmpeg has something other than digital silence to cut.
        w.writeframes(b"".join(struct.pack("<h", (i % 200) - 100) for i in range(n)))
    return path


@pytest.fixture
def sample(tmp_path):
    return _sample_wav(tmp_path / "long_sample.wav")


def _has_ffmpeg() -> bool:
    try:
        require_ffmpeg()
        return True
    except Exception:  # noqa: BLE001
        return False


needs_ffmpeg = pytest.mark.skipif(not _has_ffmpeg(), reason="ffmpeg not installed")


# -- reference clip ------------------------------------------------------------------


@needs_ffmpeg
def test_prepare_reference_clip_cuts_to_vendor_size(sample, tmp_path):
    clip = prepare_reference_clip(sample, tmp_path / "ref.wav", seconds=25.0)
    info = probe_wav(clip)
    assert info.sample_rate == 16000
    assert info.channels == 1
    assert 24.5 <= info.seconds <= 25.5
    # 25 s of 16 kHz mono PCM16 is ~800 KB — comfortably under Smallest's 5 MB cap.
    assert clip.stat().st_size < 1_000_000


# -- Smallest ------------------------------------------------------------------------


@needs_ffmpeg
def test_smallest_clone_and_synth_match_current_docs(sample):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/waves/v1/voice-cloning":
            return httpx.Response(200, json={"message": "ok", "data": {"voiceId": "voice_abc123", "status": "pending"}})
        if request.url.path == "/waves/v1/tts":
            return httpx.Response(200, content=WAV_HEADER + b"\x00" * 64, headers={"content-type": "audio/wav"})
        return httpx.Response(404)

    tts = SmallestTTS(api_key="k")
    tts._client = httpx.Client(transport=httpx.MockTransport(handler), headers={"Authorization": "Bearer k"})

    vid = tts.clone(sample, display_name="bakeoff-mr-IN", lang="mr-IN")
    assert vid == "voice_abc123"

    clone_req = seen[0]
    assert clone_req.method == "POST"
    assert clone_req.headers["authorization"] == "Bearer k"
    body = clone_req.content
    assert b'name="displayName"' in body and b"bakeoff-mr-IN" in body
    assert b'name="language"' in body and b"\r\nmr\r\n" in body  # ISO 639-1, not mr-IN
    assert b'name="model"' in body and SMALLEST_CLONE_MODEL.encode() in body
    assert b'name="file"' in body

    res = tts.synth("नमस्कार", vid, "mr-IN", sample_rate=24000)
    synth_req = seen[1]
    payload = json.loads(synth_req.content)
    assert synth_req.url.path == "/waves/v1/tts"
    assert synth_req.headers["accept"] == "audio/wav"
    assert payload == {
        "text": "नमस्कार",
        "voice_id": "voice_abc123",
        "model": TTS_MODEL,
        "language": "mr",
        "sample_rate": 24000,
        "output_format": "wav",
    }
    assert res.audio.startswith(b"RIFF")
    assert res.cost_inr > 0


def test_smallest_rejects_unsupported_sample_rate():
    tts = SmallestTTS(api_key="k")
    with pytest.raises(ValueError):
        tts.synth("x", "voice_a", "mr-IN", sample_rate=22050)


def test_smallest_refuses_json_masquerading_as_audio():
    def handler(request):
        return httpx.Response(200, json={"error": "quota"}, headers={"content-type": "application/json"})

    tts = SmallestTTS(api_key="k")
    tts._client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(RuntimeError):
        tts.synth("x", "voice_a", "mr-IN")


# -- Gnani ---------------------------------------------------------------------------


@needs_ffmpeg
def test_gnani_clone_stores_embedding_and_synth_sends_it(sample, tmp_path):
    seen: list[httpx.Request] = []
    embedding = {"embedding": "QUJD...", "shape": [1, 768], "dtype": "torch.bfloat16"}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/api/v1/tts/voice-clone/embeddings":
            return httpx.Response(200, json={"success": True, "data": {"voice_clone_embedding": embedding}})
        if request.url.path == "/api/v1/tts/inference":
            return httpx.Response(200, content=WAV_HEADER + b"\x00" * 64, headers={"content-type": "audio/wav"})
        return httpx.Response(404)

    tts = GnaniTTS(api_key="k", voices_dir=tmp_path / "voices")
    tts._client = httpx.Client(
        base_url="https://api.vachana.ai", transport=httpx.MockTransport(handler), headers={"X-API-Key-ID": "k"}
    )

    vid = tts.clone(sample, display_name="bakeoff-mr-IN", lang="mr-IN")
    assert vid.startswith(HANDLE_PREFIX)
    assert (tmp_path / "voices" / f"{vid}.json").exists()
    embed_req = seen[0]
    assert embed_req.headers["x-api-key-id"] == "k"
    assert b'name="audio_file"' in embed_req.content

    res = tts.synth("नमस्कार", vid, "mr-IN", sample_rate=24000)
    payload = json.loads(seen[1].content)
    assert payload["model"] == GNANI_VC_MODEL
    assert payload["speaker_embedding"] == embedding
    assert payload["audio_config"]["sample_rate"] == 24000
    assert payload["audio_config"]["container"] == "wav"
    assert "voice" not in payload
    assert res.fmt == "wav" and res.sample_rate == 24000

    # Telephony wire format straight from the vendor.
    res8 = tts.synth("नमस्कार", vid, "mr-IN", container="mulaw")
    assert res8.sample_rate == 8000 and res8.fmt == "mulaw"


def test_gnani_catalog_voice_uses_timbre():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, content=WAV_HEADER, headers={"content-type": "audio/wav"})

    tts = GnaniTTS(api_key="k")
    tts._client = httpx.Client(base_url="https://api.vachana.ai", transport=httpx.MockTransport(handler))
    tts.synth("नमस्ते", "Nalini", "hi-IN")
    payload = json.loads(seen[0].content)
    assert payload["model"] == "timbre-v2.5"
    assert payload["voice"] == "Nalini"
    assert payload["language"] == "hi-IN"
    assert "speaker_embedding" not in payload


def test_gnani_unknown_handle_fails_loud(tmp_path):
    tts = GnaniTTS(api_key="k", voices_dir=tmp_path)
    with pytest.raises(FileNotFoundError):
        tts.synth("x", f"{HANDLE_PREFIX}deadbeef", "mr-IN")


# -- registry ------------------------------------------------------------------------


def test_registry_constructs_gnani():
    assert isinstance(get_tts("gnani", api_key="k"), GnaniTTS)


def test_registry_still_refuses_empty_keys():
    with pytest.raises(ValueError):
        get_tts("gnani", api_key="")
    with pytest.raises(ValueError):
        get_tts("smallest", api_key="")
