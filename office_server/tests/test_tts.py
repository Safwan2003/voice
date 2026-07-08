import numpy as np
import pytest

from sdr_agent.tts import SAMPLE_RATE, VOICE_INSTRUCT, OmniVoiceTTS, _OmniVoiceChunkedStream


class FakeOmniVoiceModel:
    def __init__(self, samples):
        self._samples = samples
        self.calls = []

    def generate(self, text, instruct):
        self.calls.append((text, instruct))
        return [self._samples]


class FakeTTSHolder:
    def __init__(self, model):
        self._model = model


class FakeEmitter:
    def __init__(self):
        self.initialized = None
        self.pushed = b""
        self.flushed = False

    def initialize(self, **kwargs):
        self.initialized = kwargs

    def push(self, data):
        self.pushed += data

    def flush(self):
        self.flushed = True


@pytest.mark.asyncio
async def test_run_synthesizes_and_emits_pcm16():
    samples = np.array([0.0, 0.5, -0.5], dtype=np.float32)
    model = FakeOmniVoiceModel(samples)

    stream = _OmniVoiceChunkedStream.__new__(_OmniVoiceChunkedStream)
    stream._tts = FakeTTSHolder(model)
    stream.input_text = "Hello prospect"

    emitter = FakeEmitter()
    await stream._run(emitter)

    assert model.calls == [("Hello prospect", VOICE_INSTRUCT)]
    assert emitter.initialized == {
        "request_id": "",
        "sample_rate": SAMPLE_RATE,
        "num_channels": 1,
        "mime_type": "audio/pcm",
    }
    expected_pcm16 = (samples * 32767.0).astype(np.int16).tobytes()
    assert emitter.pushed == expected_pcm16
    assert emitter.flushed is True


def test_synthesize_returns_chunked_stream_with_input_text():
    model = FakeOmniVoiceModel(np.array([0.0], dtype=np.float32))
    plugin = OmniVoiceTTS(model)

    stream = plugin.synthesize("This is a test.")

    assert isinstance(stream, _OmniVoiceChunkedStream)
    assert stream.input_text == "This is a test."
