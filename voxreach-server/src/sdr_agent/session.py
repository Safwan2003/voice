from livekit.agents import Agent, AgentSession
from livekit.plugins import openai

from .config import OfficeConfig
from .stt import WhisperSTT
from .tenants import Tenant
from .tts import OmniVoiceTTS


def _build_llm(config: OfficeConfig):
    if config.llm_provider == "anthropic":
        # Separate plugin (livekit-plugins-anthropic, optional dependency —
        # see pyproject.toml's "anthropic" extra) since Claude's native API
        # isn't OpenAI-compatible. Imported lazily so installs that never
        # use this provider don't need the extra installed.
        from livekit.plugins import anthropic

        return anthropic.LLM(model=config.llm_model, api_key=config.llm_api_key)

    # groq and openai are both OpenAI-compatible endpoints — same plugin,
    # just a different base_url/api_key/model per provider, resolved once
    # in config.load_config().
    return openai.LLM(
        model=config.llm_model,
        base_url=config.llm_base_url,
        api_key=config.llm_api_key,
    )


def create_sdr_agent_session(
    config: OfficeConfig, whisper_model, omnivoice_model, vad
) -> AgentSession:
    return AgentSession(
        stt=WhisperSTT(whisper_model),
        llm=_build_llm(config),
        tts=OmniVoiceTTS(omnivoice_model),
        vad=vad,
    )


class SDRAgent(Agent):
    def __init__(self, tenant: Tenant):
        super().__init__(instructions=tenant.persona_instructions)
