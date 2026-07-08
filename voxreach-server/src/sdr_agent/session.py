from livekit.agents import Agent, AgentSession
from livekit.plugins import openai

from .config import OfficeConfig
from .stt import WhisperSTT
from .tenants import Tenant
from .tts import OmniVoiceTTS


def create_sdr_agent_session(
    config: OfficeConfig, whisper_model, omnivoice_model, vad
) -> AgentSession:
    return AgentSession(
        stt=WhisperSTT(whisper_model),
        llm=openai.LLM(
            model=config.llm_model,
            base_url=config.vllm_base_url,
            api_key="not-needed",
        ),
        tts=OmniVoiceTTS(omnivoice_model),
        vad=vad,
    )


class SDRAgent(Agent):
    def __init__(self, tenant: Tenant):
        super().__init__(instructions=tenant.persona_instructions)
