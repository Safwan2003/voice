from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TENANT_ID = "default"


class TenantNotFoundError(RuntimeError):
    pass


@dataclass(frozen=True)
class Tenant:
    id: str
    name: str
    persona_instructions: str
    greeting_instructions: str


class JsonTenantStore:
    def __init__(self, path: Path):
        self._path = path

    def get_tenant(self, tenant_id: str) -> Tenant:
        with open(self._path) as f:
            data = json.load(f)

        for record in data["tenants"]:
            if record["id"] == tenant_id:
                return Tenant(
                    id=record["id"],
                    name=record["name"],
                    persona_instructions=record["persona_instructions"],
                    greeting_instructions=record["greeting_instructions"],
                )

        raise TenantNotFoundError(f"Unknown tenant_id: {tenant_id!r}")
