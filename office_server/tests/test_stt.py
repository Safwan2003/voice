from dataclasses import dataclass

import pytest

from sdr_agent.stt import SILENCE_MARKER, WhisperSTT


@dataclass
class FakeSegment:
    text: str


class FakeWhisperModel:
    def __init__(self, segments):
        self._segments = segments

    def transcribe(self, wav_bytes, language="en"):
        return self._segments, {}


class FakeCombined:
    def to_wav_bytes(self):
        return b"fake-wav-bytes"


def _patch_combine_audio_frames(monkeypatch):
    monkeypatch.setattr("sdr_agent.stt.rtc.combine_audio_frames", lambda buffer: FakeCombined())


@pytest.mark.asyncio
async def test_recognize_returns_transcribed_text(monkeypatch):
    _patch_combine_audio_frames(monkeypatch)
    model = FakeWhisperModel([FakeSegment("Hello there"), FakeSegment("how are you")])
    plugin = WhisperSTT(model)

    event = await plugin._recognize_impl(buffer=[], language="en", conn_options=None)

    assert event.alternatives[0].text == "Hello there how are you"


@pytest.mark.asyncio
async def test_recognize_returns_silence_marker_for_empty_transcript(monkeypatch):
    _patch_combine_audio_frames(monkeypatch)
    model = FakeWhisperModel([FakeSegment("")])
    plugin = WhisperSTT(model)

    event = await plugin._recognize_impl(buffer=[], language="en", conn_options=None)

    assert event.alternatives[0].text == SILENCE_MARKER


@pytest.mark.asyncio
async def test_recognize_returns_silence_marker_for_single_char_noise(monkeypatch):
    _patch_combine_audio_frames(monkeypatch)
    model = FakeWhisperModel([FakeSegment("h")])
    plugin = WhisperSTT(model)

    event = await plugin._recognize_impl(buffer=[], language="en", conn_options=None)

    assert event.alternatives[0].text == SILENCE_MARKER
