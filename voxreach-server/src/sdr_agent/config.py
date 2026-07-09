from __future__ import annotations

import os
from dataclasses import dataclass


class ConfigError(RuntimeError):
    pass


REQUIRED_ENV_VARS = ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET")
OPTIONAL_ENV_VARS = (
    "OFFICE_LLM_PROVIDER",
    "OFFICE_LLM_MODEL",
    "GROQ_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "OFFICE_LOAD_THRESHOLD",
    "WHISPER_MODEL_SIZE",
    "WHISPER_COMPUTE_TYPE",
    "WHISPER_DEVICE",
    "OMNIVOICE_MODEL_ID",
    "OMNIVOICE_DEVICE",
    "TENANTS_DATA_PATH",
)

# LLM provider selection. All are hosted APIs, reachable through LiveKit's
# openai.LLM plugin except anthropic (needs livekit-plugins-anthropic, an
# optional dependency — see pyproject.toml). No local LLM process runs on
# the office server — only Whisper (~1.2GB VRAM) and OmniVoice (~3GB VRAM)
# are GPU-resident (see Capacity Analysis in
# docs/superpowers/specs/2026-07-07-office-server-deployment-design.md;
# its vLLM-specific budget no longer applies — self-hosting an LLM isn't
# a supported provider right now, see git history to bring it back).
KNOWN_LLM_PROVIDERS = ("groq", "openai", "anthropic")

_PROVIDER_BASE_URLS = {
    "groq": "https://api.groq.com/openai/v1",
    "openai": "https://api.openai.com/v1",
}

_PROVIDER_DEFAULT_MODELS = {
    "groq": "llama-3.3-70b-versatile",
    "openai": "gpt-4o-mini",
    "anthropic": "claude-haiku-4-5",
}

_PROVIDER_API_KEY_ENV = {
    "groq": "GROQ_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ConfigError(f"Required environment variable {name} is not set")
    return value


def _optional(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class OfficeConfig:
    livekit_url: str
    livekit_api_key: str
    livekit_api_secret: str
    llm_provider: str
    llm_model: str
    llm_base_url: str
    llm_api_key: str
    load_threshold: float
    whisper_model_size: str
    whisper_compute_type: str
    whisper_device: str
    omnivoice_model_id: str
    omnivoice_device: str
    tenants_data_path: str


def _resolve_llm(provider: str) -> tuple[str, str, str]:
    """Returns (model, base_url, api_key) for the given provider.

    Raises ConfigError with an actionable message on misconfiguration
    (unknown provider, or a hosted provider missing its API key) rather
    than surfacing an opaque auth failure once a call actually comes in.
    """
    if provider not in KNOWN_LLM_PROVIDERS:
        raise ConfigError(
            f"Unknown OFFICE_LLM_PROVIDER={provider!r} "
            f"(expected one of: {', '.join(KNOWN_LLM_PROVIDERS)})"
        )

    model = os.environ.get("OFFICE_LLM_MODEL") or _PROVIDER_DEFAULT_MODELS[provider]

    key_env = _PROVIDER_API_KEY_ENV[provider]
    api_key = os.environ.get(key_env)
    if not api_key:
        raise ConfigError(f"OFFICE_LLM_PROVIDER={provider} requires {key_env} to be set")

    # anthropic.LLM (livekit-plugins-anthropic) takes api_key/model directly
    # and has no base_url concept in the same sense as the OpenAI-compatible
    # plugin — session.py branches on provider rather than using this value.
    base_url = _PROVIDER_BASE_URLS.get(provider, "")
    return model, base_url, api_key


def load_config() -> OfficeConfig:
    llm_provider = _optional("OFFICE_LLM_PROVIDER", "groq").lower()
    llm_model, llm_base_url, llm_api_key = _resolve_llm(llm_provider)

    return OfficeConfig(
        livekit_url=_require("LIVEKIT_URL"),
        livekit_api_key=_require("LIVEKIT_API_KEY"),
        livekit_api_secret=_require("LIVEKIT_API_SECRET"),
        llm_provider=llm_provider,
        llm_model=llm_model,
        llm_base_url=llm_base_url,
        llm_api_key=llm_api_key,
        load_threshold=float(_optional("OFFICE_LOAD_THRESHOLD", "0.8")),
        whisper_model_size=_optional("WHISPER_MODEL_SIZE", "large-v3-turbo"),
        whisper_compute_type=_optional("WHISPER_COMPUTE_TYPE", "int8_float16"),
        whisper_device=_optional("WHISPER_DEVICE", "cuda"),
        omnivoice_model_id=_optional("OMNIVOICE_MODEL_ID", "k2-fsa/OmniVoice"),
        omnivoice_device=_optional("OMNIVOICE_DEVICE", "cuda:0"),
        tenants_data_path=_optional("TENANTS_DATA_PATH", "data/tenants.json"),
    )
