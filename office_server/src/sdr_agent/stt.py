import io

from livekit import rtc
from livekit.agents import stt
from livekit.agents.utils import AudioBuffer

SILENCE_MARKER = "[SILENCE_OR_UNCLEAR_AUDIO]"
MIN_TRANSCRIPT_LENGTH = 2


class WhisperSTT(stt.STT):
    def __init__(self, model):
        super().__init__(
            capabilities=stt.STTCapabilities(
                streaming=False,
                interim_results=False,
            )
        )
        self._model = model

    async def _recognize_impl(
        self, buffer: AudioBuffer, *, language=None, conn_options=None
    ) -> stt.SpeechEvent:
        wav_bytes = io.BytesIO(rtc.combine_audio_frames(buffer).to_wav_bytes())

        segments, _info = self._model.transcribe(wav_bytes, language="en")
        text = " ".join(segment.text for segment in segments).strip()

        # Empty or very short output means silence/noise rather than real
        # speech. Forward a marker instead of the raw (empty) text so the
        # LLM's system prompt can react by asking the caller to repeat,
        # rather than the LLM receiving nothing to respond to.
        if len(text) < MIN_TRANSCRIPT_LENGTH:
            text = SILENCE_MARKER

        return stt.SpeechEvent(
            type=stt.SpeechEventType.FINAL_TRANSCRIPT,
            alternatives=[stt.SpeechData(language="en", text=text)],
        )
