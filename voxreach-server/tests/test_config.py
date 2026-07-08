import pytest

from sdr_agent.config import ConfigError, load_config


REQUIRED = {
    "LIVEKIT_URL": "wss://voice.example-office.com",
    "LIVEKIT_API_KEY": "test-key",
    "LIVEKIT_API_SECRET": "test-secret",
}


def _set_required(monkeypatch):
    for name, value in REQUIRED.items():
        monkeypatch.setenv(name, value)


def _clear_optional(monkeypatch):
    for name in (
        "OFFICE_LLM_MODEL",
        "OFFICE_VLLM_BASE_URL",
        "OFFICE_LOAD_THRESHOLD",
        "WHISPER_MODEL_SIZE",
        "WHISPER_COMPUTE_TYPE",
        "WHISPER_DEVICE",
        "OMNIVOICE_MODEL_ID",
        "OMNIVOICE_DEVICE",
        "TENANTS_DATA_PATH",
    ):
        monkeypatch.delenv(name, raising=False)


def test_load_config_raises_when_required_var_missing(monkeypatch):
    for name in REQUIRED:
        monkeypatch.delenv(name, raising=False)
    _clear_optional(monkeypatch)

    with pytest.raises(ConfigError):
        load_config()


def test_load_config_applies_defaults_for_optional_vars(monkeypatch):
    _set_required(monkeypatch)
    _clear_optional(monkeypatch)

    config = load_config()

    assert config.livekit_url == REQUIRED["LIVEKIT_URL"]
    assert config.llm_model == "Qwen/Qwen2.5-3B-Instruct-AWQ"
    assert config.vllm_base_url == "http://localhost:8000/v1"
    assert config.load_threshold == 0.8
    assert config.whisper_model_size == "large-v3-turbo"
    assert config.whisper_compute_type == "int8_float16"
    assert config.whisper_device == "cuda"
    assert config.omnivoice_model_id == "k2-fsa/OmniVoice"
    assert config.omnivoice_device == "cuda:0"
    assert config.tenants_data_path == "data/tenants.json"


def test_load_config_respects_explicit_overrides(monkeypatch):
    _set_required(monkeypatch)
    monkeypatch.setenv("OFFICE_LLM_MODEL", "Qwen/Qwen2.5-7B-Instruct-AWQ")
    monkeypatch.setenv("OFFICE_LOAD_THRESHOLD", "0.5")

    config = load_config()

    assert config.llm_model == "Qwen/Qwen2.5-7B-Instruct-AWQ"
    assert config.load_threshold == 0.5


def test_required_and_optional_env_var_lists_are_disjoint():
    from sdr_agent.config import OPTIONAL_ENV_VARS, REQUIRED_ENV_VARS

    assert set(REQUIRED_ENV_VARS).isdisjoint(OPTIONAL_ENV_VARS)
    assert REQUIRED_ENV_VARS == ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET")
