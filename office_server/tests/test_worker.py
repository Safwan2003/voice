import pytest
from pathlib import Path

from sdr_agent.session import SDRAgent
from sdr_agent.tenants import DEFAULT_TENANT_ID, JsonTenantStore, Tenant
from sdr_agent.worker import build_entrypoint


class FakeJob:
    def __init__(self, metadata):
        self.metadata = metadata


class FakeCtx:
    def __init__(self, metadata=""):
        self.connected = False
        self.room = object()
        self.job = FakeJob(metadata)

    async def connect(self):
        self.connected = True


class FakeSession:
    def __init__(self):
        self.start_call = None
        self.generate_reply_instructions = None

    async def start(self, *, agent, room):
        self.start_call = {"agent": agent, "room": room}

    async def generate_reply(self, *, instructions):
        self.generate_reply_instructions = instructions


class FakeTenantStore:
    def __init__(self, tenants_by_id):
        self._tenants_by_id = tenants_by_id
        self.requested_ids = []

    def get_tenant(self, tenant_id):
        self.requested_ids.append(tenant_id)
        return self._tenants_by_id[tenant_id]


ACME_TENANT = Tenant(
    id="acme",
    name="Acme Corp",
    persona_instructions="You are Sam from Acme.",
    greeting_instructions="Greet the prospect and introduce yourself and Acme.",
)

DEFAULT_TENANT = Tenant(
    id=DEFAULT_TENANT_ID,
    name="Streamline (demo tenant)",
    persona_instructions="You are Alex from Streamline.",
    greeting_instructions="Greet the prospect and introduce yourself and Streamline.",
)


@pytest.mark.asyncio
async def test_entrypoint_resolves_tenant_from_job_metadata_and_greets(monkeypatch):
    fake_session = FakeSession()
    create_session_args = {}

    def fake_create_session(config, whisper_model, omnivoice_model, vad):
        create_session_args["args"] = (config, whisper_model, omnivoice_model, vad)
        return fake_session

    import sdr_agent.worker as worker_module

    monkeypatch.setattr(worker_module, "create_sdr_agent_session", fake_create_session)

    tenant_store = FakeTenantStore({"acme": ACME_TENANT})
    config, whisper_model, omnivoice_model, vad = object(), object(), object(), object()
    entrypoint = build_entrypoint(config, whisper_model, omnivoice_model, vad, tenant_store)

    ctx = FakeCtx(metadata="acme")
    await entrypoint(ctx)

    assert ctx.connected is True
    assert tenant_store.requested_ids == ["acme"]
    assert create_session_args["args"] == (config, whisper_model, omnivoice_model, vad)
    assert isinstance(fake_session.start_call["agent"], SDRAgent)
    assert fake_session.start_call["agent"].instructions == ACME_TENANT.persona_instructions
    assert fake_session.start_call["room"] is ctx.room
    assert fake_session.generate_reply_instructions == ACME_TENANT.greeting_instructions


@pytest.mark.asyncio
async def test_entrypoint_falls_back_to_default_tenant_when_metadata_empty(monkeypatch):
    fake_session = FakeSession()

    def fake_create_session(config, whisper_model, omnivoice_model, vad):
        return fake_session

    import sdr_agent.worker as worker_module

    monkeypatch.setattr(worker_module, "create_sdr_agent_session", fake_create_session)

    tenant_store = FakeTenantStore({DEFAULT_TENANT_ID: DEFAULT_TENANT})
    config, whisper_model, omnivoice_model, vad = object(), object(), object(), object()
    entrypoint = build_entrypoint(config, whisper_model, omnivoice_model, vad, tenant_store)

    ctx = FakeCtx(metadata="")
    await entrypoint(ctx)

    assert tenant_store.requested_ids == [DEFAULT_TENANT_ID]
    assert fake_session.generate_reply_instructions == DEFAULT_TENANT.greeting_instructions


@pytest.mark.asyncio
async def test_entrypoint_integration_with_real_tenant_store(monkeypatch):
    """Integration test: verify the full chain with real JsonTenantStore and seed data."""
    fake_session = FakeSession()

    def fake_create_session(config, whisper_model, omnivoice_model, vad):
        return fake_session

    import sdr_agent.worker as worker_module

    monkeypatch.setattr(worker_module, "create_sdr_agent_session", fake_create_session)

    # Use the real seed data file
    seed_data_path = Path(__file__).resolve().parent.parent / "data" / "tenants.json"
    tenant_store = JsonTenantStore(seed_data_path)

    config, whisper_model, omnivoice_model, vad = object(), object(), object(), object()
    entrypoint = build_entrypoint(config, whisper_model, omnivoice_model, vad, tenant_store)

    # Test with empty metadata to exercise default fallback
    ctx = FakeCtx(metadata="")
    await entrypoint(ctx)

    # Verify connection and context handling
    assert ctx.connected is True

    # Verify the SDRAgent was created with the real default tenant's persona
    agent = fake_session.start_call["agent"]
    assert isinstance(agent, SDRAgent)
    assert "Alex" in agent.instructions
    assert "Streamline" in agent.instructions

    # Verify the greeting instructions match the real seed data
    assert fake_session.generate_reply_instructions == "Greet the prospect and introduce yourself and Streamline."
