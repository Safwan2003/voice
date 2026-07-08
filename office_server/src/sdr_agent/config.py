from __future__ import annotations

import os
from dataclasses import dataclass


class ConfigError(RuntimeError):
    pass


REQUIRED_ENV_VARS = ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET")
OPTIONAL_ENV_VARS = (
    "OFFICE_LLM_MODEL",
    "OFFICE_VLLM_BASE_URL",
    "OFFICE_LOAD_THRESHOLD",
    "WHISPER_MODEL_SIZE",
    "WHISPER_COMPUTE_TYPE",
    "WHISPER_DEVICE",
    "OMNIVOICE_MODEL_ID",
    "OMNIVOICE_DEVICE",
    "TENANTS_DATA_PATH",
)


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
    llm_model: str
    vllm_base_url: str
    load_threshold: float
    whisper_model_size: str
    whisper_compute_type: str
    whisper_device: str
    omnivoice_model_id: str
    omnivoice_device: str
    tenants_data_path: str


def load_config() -> OfficeConfig:
    return OfficeConfig(
        livekit_url=_require("LIVEKIT_URL"),
        livekit_api_key=_require("LIVEKIT_API_KEY"),
        livekit_api_secret=_require("LIVEKIT_API_SECRET"),
        llm_model=_optional("OFFICE_LLM_MODEL", "Qwen/Qwen2.5-3B-Instruct-AWQ"),
        vllm_base_url=_optional("OFFICE_VLLM_BASE_URL", "http://localhost:8000/v1"),
        load_threshold=float(_optional("OFFICE_LOAD_THRESHOLD", "0.8")),
        whisper_model_size=_optional("WHISPER_MODEL_SIZE", "large-v3-turbo"),
        whisper_compute_type=_optional("WHISPER_COMPUTE_TYPE", "int8_float16"),
        whisper_device=_optional("WHISPER_DEVICE", "cuda"),
        omnivoice_model_id=_optional("OMNIVOICE_MODEL_ID", "k2-fsa/OmniVoice"),
        omnivoice_device=_optional("OMNIVOICE_DEVICE", "cuda:0"),
        tenants_data_path=_optional("TENANTS_DATA_PATH", "data/tenants.json"),
    )
