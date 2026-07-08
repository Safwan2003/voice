import json
from pathlib import Path

import pytest

from sdr_agent.tenants import DEFAULT_TENANT_ID, JsonTenantStore, Tenant, TenantNotFoundError

SEED_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "tenants.json"


def _write_store(tmp_path, tenants):
    path = tmp_path / "tenants.json"
    path.write_text(json.dumps({"tenants": tenants}))
    return path


def test_get_tenant_returns_matching_record(tmp_path):
    path = _write_store(
        tmp_path,
        [
            {
                "id": "acme",
                "name": "Acme Corp",
                "persona_instructions": "You are Sam from Acme.",
                "greeting_instructions": "Greet the prospect and introduce yourself and Acme.",
            }
        ],
    )
    store = JsonTenantStore(path)

    tenant = store.get_tenant("acme")

    assert tenant == Tenant(
        id="acme",
        name="Acme Corp",
        persona_instructions="You are Sam from Acme.",
        greeting_instructions="Greet the prospect and introduce yourself and Acme.",
    )


def test_get_tenant_raises_for_unknown_id(tmp_path):
    path = _write_store(tmp_path, [])
    store = JsonTenantStore(path)

    with pytest.raises(TenantNotFoundError):
        store.get_tenant("nonexistent")


def test_default_tenant_seed_file_is_loadable():
    store = JsonTenantStore(SEED_DATA_PATH)

    tenant = store.get_tenant(DEFAULT_TENANT_ID)

    assert tenant.id == DEFAULT_TENANT_ID
    assert "Alex" in tenant.persona_instructions
    assert "Streamline" in tenant.persona_instructions
    assert tenant.greeting_instructions
