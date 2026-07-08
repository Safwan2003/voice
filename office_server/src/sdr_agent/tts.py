import numpy as np
from livekit.agents import DEFAULT_API_CONNECT_OPTIONS, APIConnectOptions, tts

VOICE_INSTRUCT = "female, moderate pitch, american accent"
SAMPLE_RATE = 24000


class OmniVoiceTTS(tts.TTS):
    def __init__(self, model):
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False),
            sample_rate=SAMPLE_RATE,
            num_channels=1,
        )
        self._model = model

    def synthesize(
        self, text: str, *, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS
    ) -> "tts.ChunkedStream":
        return _OmniVoiceChunkedStream(tts=self, input_text=text, conn_options=conn_options)


class _OmniVoiceChunkedStream(tts.ChunkedStream):
    async def _run(self, output_emitter: "tts.AudioEmitter") -> None:
        audio_chunks = self._tts._model.generate(
            text=self.input_text,
            instruct=VOICE_INSTRUCT,
        )
        audio = audio_chunks[0]
        pcm16 = (audio * 32767.0).astype(np.int16)

        output_emitter.initialize(
            request_id="",
            sample_rate=SAMPLE_RATE,
            num_channels=1,
            mime_type="audio/pcm",
        )
        output_emitter.push(pcm16.tobytes())
        output_emitter.flush()
