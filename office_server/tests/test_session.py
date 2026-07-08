from sdr_agent.config import OfficeConfig
from sdr_agent.tenants import Tenant


def _config(**overrides):
    defaults = dict(
        livekit_url="wss://example.com",
        livekit_api_key="key",
        livekit_api_secret="secret",
        llm_model="Qwen/Qwen2.5-3B-Instruct-AWQ",
        vllm_base_url="http://localhost:8000/v1",
        load_threshold=0.8,
        whisper_model_size="large-v3-turbo",
        whisper_compute_type="int8_float16",
        whisper_device="cuda",
        omnivoice_model_id="k2-fsa/OmniVoice",
        omnivoice_device="cuda:0",
        tenants_data_path="data/tenants.json",
    )
    defaults.update(overrides)
    return OfficeConfig(**defaults)


def _tenant(**overrides):
    defaults = dict(
        id="acme",
        name="Acme Corp",
        persona_instructions="You are Sam from Acme.",
        greeting_instructions="Greet the prospect and introduce yourself and Acme.",
    )
    defaults.update(overrides)
    return Tenant(**defaults)


def test_sdr_agent_uses_tenant_persona_instructions():
    from sdr_agent.session import SDRAgent

    tenant = _tenant(persona_instructions="You are Sam from Acme, selling widgets.")
    agent = SDRAgent(tenant)

    assert agent.instructions == "You are Sam from Acme, selling widgets."


def test_create_sdr_agent_session_wires_components(monkeypatch):
    calls = {}

    class FakeWhisperSTT:
        def __init__(self, model):
            calls["stt_model"] = model

    class FakeOmniVoiceTTS:
        def __init__(self, model):
            calls["tts_model"] = model

    class FakeLLM:
        def __init__(self, *, model, base_url, api_key):
            calls["llm"] = {"model": model, "base_url": base_url, "api_key": api_key}

    class FakeAgentSession:
        def __init__(self, *, stt, llm, tts, vad):
            calls["session"] = {"stt": stt, "llm": llm, "tts": tts, "vad": vad}

    import sdr_agent.session as session_module

    monkeypatch.setattr(session_module, "WhisperSTT", FakeWhisperSTT)
    monkeypatch.setattr(session_module, "OmniVoiceTTS", FakeOmniVoiceTTS)
    monkeypatch.setattr(session_module.openai, "LLM", FakeLLM)
    monkeypatch.setattr(session_module, "AgentSession", FakeAgentSession)

    config = _config(llm_model="test-model", vllm_base_url="http://vllm.local/v1")
    whisper_model, omnivoice_model, vad = object(), object(), object()

    session_module.create_sdr_agent_session(config, whisper_model, omnivoice_model, vad)

    assert calls["stt_model"] is whisper_model
    assert calls["tts_model"] is omnivoice_model
    assert calls["llm"] == {
        "model": "test-model",
        "base_url": "http://vllm.local/v1",
        "api_key": "not-needed",
    }
    assert calls["session"]["vad"] is vad
