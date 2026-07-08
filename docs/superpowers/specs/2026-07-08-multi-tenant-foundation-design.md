# Multi-Tenant Foundation — Extension Seams for the Office Server Deployment

**Date**: 2026-07-08
**Status**: Approved for implementation planning

## Goal

Add the minimum structural seams to the office-server deployment (spec:
`2026-07-07-office-server-deployment-design.md`, plan:
`2026-07-08-office-server-deployment.md`) so that multi-tenancy, inbound
calling, and real telephony can each be added later as isolated changes,
without restructuring the worker, session, or plugin code that's already
been designed. **This phase changes no runtime behavior** — one tenant runs
today, with the exact same persona and greeting as before — it only makes
persona/greeting data-driven instead of hardcoded, and makes the call's
tenant identity flow through the system instead of being assumed.

## Why now

The office-server plan was about to hardcode a single persona as a Python
constant a second time (having already done so once in the Colab
notebook). Retrofitting tenant-awareness after a dashboard, campaign
engine, and real database exist would mean changing the worker entrypoint,
session factory, and agent construction simultaneously, under more
integration pressure than exists today. Building the seam now, while the
system is still one file's worth of plumbing, costs a few functions and a
JSON file.

## Non-Goals (this phase)

- A real relational database (SQLite/Postgres) — deferred; the JSON store
  below is designed so replacing it later touches one class, not its
  callers.
- Dashboard, authentication, or any tenant-management UI.
- Outbound campaign/dial-triggering logic (what decides "call this lead
  now" and sets a room's tenant metadata) — nothing sets tenant metadata
  yet, so every call still resolves to the one `"default"` tenant.
- Inbound calling and real SIP/PSTN telephony (both directions) — unchanged
  from the office-server spec's existing deferral.
- Per-tenant infrastructure config (LLM model choice, GPU allocation,
  voice) — infra config (`OFFICE_LLM_MODEL`, `OFFICE_NUM_WORKERS`, etc.)
  stays global/environment-driven, serving all tenants from the same
  shared vLLM instance and worker pool. Only the *business* config
  (persona script, greeting) is tenant-scoped in this phase.

## Design

### Non-seam: call origin needs no abstraction

Whether a room's participant arrived via the browser tester, an
outbound-dialed number, or (later) an inbound SIP trunk call, LiveKit
reduces all three to "a participant is in a room." The worker's
`entrypoint(ctx)` already only inspects `ctx.room` — it has no reason to
know or branch on how the call started, and none is being added. This is
called out explicitly so no unnecessary "call origin" abstraction gets
built later out of habit.

### Seam 1: persona/greeting resolve from a tenant record, not a constant

A `Tenant` record (`id`, `name`, `persona_instructions`,
`greeting_instructions`) replaces the standalone `SDR_INSTRUCTIONS`
constant and the hardcoded greeting string. `SDRAgent.__init__` takes a
`Tenant` and uses `tenant.persona_instructions`. The worker's
greet-on-connect call uses `tenant.greeting_instructions`. Adding a second
tenant with a different company name and script is a new record, not a
code change.

### Seam 2: tenant identity flows from the call, not a global

LiveKit rooms/jobs carry a `metadata` string field already, with no new
infrastructure needed to use it. The worker entrypoint reads
`ctx.job.metadata` as `tenant_id`, falling back to the constant
`DEFAULT_TENANT_ID = "default"` when empty — true for every call today,
since nothing yet sets room metadata when creating a call. When a future
dashboard or campaign engine starts creating rooms with real tenant
metadata, no worker code changes; it already reads this field.

### Data store: local JSON file today, swappable later

`office_server/data/tenants.json` holds an array of tenant records,
seeded with one `"default"` entry carrying today's exact persona and
greeting text (verbatim, so behavior is unchanged). A `JsonTenantStore`
class in `sdr_agent/tenants.py` exposes `get_tenant(tenant_id) -> Tenant`,
raising `TenantNotFoundError` for unknown IDs (fail loudly — matches the
project's existing error-handling philosophy from the office-server spec).
The store's file path is env-driven (`TENANTS_DATA_PATH`, default
`data/tenants.json` relative to the working directory), consistent with
every other hardware/deployment-dependent value in this project already
being config, not code.

**Migration path**: replacing the JSON file with SQLite/Postgres later
means writing a new class with the same `get_tenant(tenant_id) -> Tenant`
shape and changing the one line in `worker.py` that constructs the store.
`session.py`, `SDRAgent`, and the entrypoint's control flow do not change.

## Data Model

```json
{
  "tenants": [
    {
      "id": "default",
      "name": "Streamline (demo tenant)",
      "persona_instructions": "<verbatim text of today's SDR_INSTRUCTIONS>",
      "greeting_instructions": "Greet the prospect and introduce yourself and Streamline."
    }
  ]
}
```

## Impact on the existing implementation plan

`docs/superpowers/plans/2026-07-08-office-server-deployment.md` has not
been executed yet (no `office_server/` code exists on disk). This phase
revises it in place rather than adding a parallel plan:

- **Task 1** gains `TENANTS_DATA_PATH` to `OfficeConfig`.
- **Task 4** drops `persona.py`; adds `sdr_agent/tenants.py`
  (`Tenant`, `JsonTenantStore`, `TenantNotFoundError`,
  `DEFAULT_TENANT_ID`) and its seed data file; `SDRAgent` takes a
  `Tenant` instead of reading a module-level constant.
- **Task 5** updates `build_entrypoint`/`main()` to resolve `tenant_id`
  from `ctx.job.metadata`, look up the `Tenant` via the store, and use
  its `persona_instructions`/`greeting_instructions`.
- Tasks 2, 3, 6, 7, 8, 9 (STT/TTS plugins, systemd units, deploy config,
  final verification) are unaffected.

## Testing

Same approach as the rest of the office-server plan: `JsonTenantStore` is
tested directly against a temp JSON file (happy path + unknown-tenant
error), and `worker.py`'s entrypoint test is updated to assert it resolves
and passes through the correct `Tenant` for a given job metadata value —
no GPU or real database required, consistent with every other unit test in
this project.
