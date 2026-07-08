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
    plugin = OmniVoiceTTS(model)

    stream = plugin.synthesize("Hello prospect")

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

    # Constructing via plugin.synthesize() starts real background tasks
    # (TTS._synthesize_task, TTS._metrics_task) as a side effect of the base
    # ChunkedStream.__init__. aclose() is ChunkedStream's own public API for
    # releasing them; without it they're torn down ungracefully when the
    # test's event loop closes, logging "Task was destroyed but it is
    # pending!" to stderr.
    await stream.aclose()


@pytest.mark.asyncio
async def test_synthesize_returns_chunked_stream_with_input_text():
    model = FakeOmniVoiceModel(np.array([0.0], dtype=np.float32))
    plugin = OmniVoiceTTS(model)

    stream = plugin.synthesize("This is a test.")

    assert isinstance(stream, _OmniVoiceChunkedStream)
    assert stream.input_text == "This is a test."

    await stream.aclose()
