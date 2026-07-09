import pytest

from sdr_agent.config import ConfigError, load_config


REQUIRED = {
    "LIVEKIT_URL": "wss://voice.example-office.com",
    "LIVEKIT_API_KEY": "test-key",
    "LIVEKIT_API_SECRET": "test-secret",
}

OPTIONAL_NAMES = (
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


def _set_required(monkeypatch):
    for name, value in REQUIRED.items():
        monkeypatch.setenv(name, value)


def _clear_optional(monkeypatch):
    for name in OPTIONAL_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_load_config_raises_when_required_var_missing(monkeypatch):
    for name in REQUIRED:
        monkeypatch.delenv(name, raising=False)
    _clear_optional(monkeypatch)

    with pytest.raises(ConfigError):
        load_config()


def test_load_config_defaults_to_groq_and_requires_its_api_key(monkeypatch):
    _set_required(monkeypatch)
    _clear_optional(monkeypatch)

    with pytest.raises(ConfigError, match="GROQ_API_KEY"):
        load_config()


def test_load_config_applies_defaults_for_optional_vars(monkeypatch):
    _set_required(monkeypatch)
    _clear_optional(monkeypatch)
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")

    config = load_config()

    assert config.livekit_url == REQUIRED["LIVEKIT_URL"]
    assert config.llm_provider == "groq"
    assert config.llm_model == "llama-3.3-70b-versatile"
    assert config.llm_base_url == "https://api.groq.com/openai/v1"
    assert config.llm_api_key == "test-groq-key"
    assert config.load_threshold == 0.8
    assert config.whisper_model_size == "large-v3-turbo"
    assert config.whisper_compute_type == "int8_float16"
    assert config.whisper_device == "cuda"
    assert config.omnivoice_model_id == "k2-fsa/OmniVoice"
    assert config.omnivoice_device == "cuda:0"
    assert config.tenants_data_path == "data/tenants.json"


def test_load_config_respects_explicit_overrides(monkeypatch):
    _set_required(monkeypatch)
    _clear_optional(monkeypatch)
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    monkeypatch.setenv("OFFICE_LLM_MODEL", "llama-3.1-8b-instant")
    monkeypatch.setenv("OFFICE_LOAD_THRESHOLD", "0.5")

    config = load_config()

    assert config.llm_model == "llama-3.1-8b-instant"
    assert config.load_threshold == 0.5


def test_load_config_openai_provider(monkeypatch):
    _set_required(monkeypatch)
    _clear_optional(monkeypatch)
    monkeypatch.setenv("OFFICE_LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")

    config = load_config()

    assert config.llm_model == "gpt-4o-mini"
    assert config.llm_base_url == "https://api.openai.com/v1"
    assert config.llm_api_key == "test-openai-key"


def test_load_config_anthropic_provider(monkeypatch):
    _set_required(monkeypatch)
    _clear_optional(monkeypatch)
    monkeypatch.setenv("OFFICE_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")

    config = load_config()

    assert config.llm_model == "claude-haiku-4-5"
    assert config.llm_api_key == "test-anthropic-key"


def test_load_config_raises_for_unknown_provider(monkeypatch):
    _set_required(monkeypatch)
    _clear_optional(monkeypatch)
    monkeypatch.setenv("OFFICE_LLM_PROVIDER", "bedrock")

    with pytest.raises(ConfigError, match="Unknown OFFICE_LLM_PROVIDER"):
        load_config()


def test_load_config_no_longer_accepts_vllm_provider(monkeypatch):
    # vLLM self-hosting was removed (see git history to bring it back) —
    # OFFICE_LLM_PROVIDER=vllm is now just another unknown provider.
    _set_required(monkeypatch)
    _clear_optional(monkeypatch)
    monkeypatch.setenv("OFFICE_LLM_PROVIDER", "vllm")

    with pytest.raises(ConfigError, match="Unknown OFFICE_LLM_PROVIDER"):
        load_config()


def test_required_and_optional_env_var_lists_are_disjoint():
    from sdr_agent.config import OPTIONAL_ENV_VARS, REQUIRED_ENV_VARS

    assert set(REQUIRED_ENV_VARS).isdisjoint(OPTIONAL_ENV_VARS)
    assert REQUIRED_ENV_VARS == ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET")
