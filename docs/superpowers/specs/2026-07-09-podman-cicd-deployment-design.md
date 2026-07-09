# Podman Containerization + CI/CD — Deployment Design

**Date**: 2026-07-09
**Status**: Approved for implementation planning

## Goal

Package `voxreach-server`'s three runtime pieces (`livekit-server`, the
browser-based UI tester, and the `sdr_agent` worker) so they run
reproducibly via Podman + systemd, and add a GitHub Actions pipeline that
tests every push and builds container images on merge — without requiring
the office-server hardware to exist yet. The office GPU box has not been
purchased at the time of this spec; everything here must be buildable and
verifiable today, with the final "deploy the new image to the real box"
step left as a documented manual step until hardware exists.

## Context (why this spec exists now)

`docs/superpowers/specs/2026-07-07-office-server-deployment-design.md`
covers the original systemd-based deployment, written when vLLM was the
only LLM path. Since then (2026-07-09 session): the LLM moved to a hosted
API (Groq by default, OpenAI/Claude as config swaps) — vLLM and its
systemd unit were removed entirely, and the WSL2/Windows GPU-passthrough
setup (which existed specifically because vLLM had no native Windows
support) was removed too. STT (faster-whisper) and TTS (OmniVoice) are
unaffected — their VRAM budget from the original spec's Capacity Analysis
(~1.2GB + ~3GB) still applies unchanged; this spec does not revisit it.

## Non-Goals (this phase)

- **Kubernetes or any dynamic orchestrator.** Unchanged from the original
  spec's stance: scaling means manually adding worker instances, not
  autoscaling. Podman + systemd Quadlets (defined below) achieve
  reproducibility without adopting an orchestrator.
- **Automating the actual deploy-to-production step.** No hardware exists
  yet to deploy to. CI builds and publishes images; getting a new image
  running on the real box is a documented manual command for this phase.
  Automating that (e.g. a self-hosted GitHub Actions runner on the box)
  is a small, natural follow-up once hardware exists — not designed here
  in detail so it isn't designed against guessed specs.
- **Live token issuance for the production UI.** The UI container serves
  the same static `ui/index.html` tester that exists today. Generating a
  fresh connection token stays a manual step (`scripts/generate-test-token.py`),
  same as it already is for local dev via `start.sh`. A self-service
  token-issuing backend is a separate feature, not part of this spec.
- **Blue/green or zero-downtime deploys.** A restart during an update is
  acceptable at this stage — this isn't yet a 24/7 service with live
  traffic to protect.
- **Linting/formatting tooling.** Out of scope for this spec — CI runs
  the existing pytest suite; adding a linter is a separate, optional
  future change if wanted.

## Why Podman (not bare processes, not Kubernetes)

- **Reproducibility without fragility.** Today, standing up a worker
  means manually installing `faster-whisper`, a CUDA-matched `torch`, and
  `omnivoice` (no PyPI release — a GitHub install) in the right versions.
  A container image bakes that once, in CI; running it anywhere after
  that is "pull and run," not "hope the manual install matches."
- **Rootless, daemonless.** Podman needs no background root daemon
  (unlike Docker) — a better default for a single office box.
- **Fits the systemd model already in place**, via Quadlets — Podman's
  native systemd integration (Podman 4.4+). A Quadlet is a `.container`
  file that systemd reads and turns into a regular unit — `systemctl
  enable --now sdr-worker@2`, `Restart=on-failure`, and
  `deploy/systemd/scale-workers.sh` all keep working exactly as they do
  today; only the unit's `ExecStart` changes from a bare Python command
  to a container run.
- **GPU passthrough is a solved problem**, not something built from
  scratch: NVIDIA Container Toolkit + CDI (Container Device Interface)
  lets a Quadlet request `AddDevice=nvidia.com/gpu=all`.
- **Scaling for concurrent calls becomes "run one more identical
  container"** rather than "hope worker #2's environment matches worker
  #1's" — this is the concrete payoff for handling parallel calls.

## Architecture

Three systemd-managed units on the office server. Only the worker
changes shape (bare process → container); `livekit-server` is untouched.

```
                  ┌─────────────────────────┐
                  │   livekit-server         │  (unchanged: native binary,
                  │   (unchanged)            │   or existing Podman fallback
                  └───────────┬─────────────┘   in start.sh)
                     ┌────────┼────────┐
                     ▼        ▼        ▼
              ┌───────────┐ ┌───────────┐ ┌───────────┐
              │ UI         │ │ Worker #1 │ │ Worker #N │  ← Podman containers,
              │ container  │ │ container │ │ container │    each a systemd
              │ (Quadlet)  │ │ (Quadlet) │ │ (Quadlet) │    Quadlet unit
              └───────────┘ └───────────┘ └───────────┘
                              GPU-resident        GPU-resident
                              (Whisper+OmniVoice)  (Whisper+OmniVoice)
                              → hosted LLM API     → hosted LLM API
```

`OFFICE_NUM_WORKERS` and `scale-workers.sh` keep working unchanged — they
now `systemctl enable --now sdr-worker@N.service`, where that unit
happens to be a Quadlet instead of a bare `ExecStart=python ...`.

## Components

### 1. Worker container image

A `Containerfile` (Podman/Docker's build recipe) at
`voxreach-server/deploy/container/worker.Containerfile`:

- Base image with a CUDA runtime (matching whatever CUDA version the
  eventual GPU driver needs — pinned once real hardware is confirmed,
  parameterized as a build arg so it isn't hardcoded ahead of time).
- Installs the `sdr_agent` package + `faster-whisper` + `omnivoice` +
  CUDA-matched `torch`.
- **Does not bake in model weights.** Whisper and OmniVoice weights
  (multi-GB, downloaded from Hugging Face on first load — see
  `worker.py`'s `load_models()`) are mounted from a host directory as a
  volume (the standard Hugging Face cache path), so they download once
  and persist across image updates — an image rebuild doesn't mean
  re-downloading gigabytes of weights.
- Multi-stage build (build-time deps vs. runtime deps) to keep the final
  image reasonably sized.

### 2. Worker Quadlet (`sdr-worker@.container`)

Replaces `deploy/systemd/sdr-worker@.service`'s `ExecStart=python -m
sdr_agent.worker` with a container run of the image above:
`EnvironmentFile=/etc/sdr-agent/office.env` (unchanged — same config
surface, no new env vars needed for the worker itself), a volume mount
for the Hugging Face cache directory, and `AddDevice=nvidia.com/gpu=all`
for GPU passthrough. `Restart=on-failure` carries over from Quadlets'
systemd integration — crash recovery behavior is unchanged from today.

### 3. UI container + Quadlet

A second, much lighter `Containerfile`
(`deploy/container/ui.Containerfile`) — a minimal static-file-serving
image (no CUDA, no Python ML deps) serving `voxreach-server/ui/index.html`
on `UI_PORT` (currently only defaulted inside `start.sh`; this spec adds
it to `office.env.example` as a documented, deploy-relevant var). Its
Quadlet (`voxreach-ui.container`) runs permanently via systemd, so the
tester is reachable on the office server at any time — not just during a
manual `start.sh` run. Token generation for connecting to it stays the
existing manual script, run on demand.

### 4. `livekit-server` — unchanged

No new work. Stays as it is today: native binary preferred, with the
existing Podman-fallback path in `start.sh` for local dev when the
binary isn't installed. It has no GPU dependency and never needs more
than one instance, so containerizing it buys nothing for this spec's
goals (see brainstorming discussion — scaling for concurrent calls is
entirely a worker concern).

### 5. CI — GitHub Actions

Two jobs in `.github/workflows/`:

- **`test`** (every push and PR): `pip install -e ".[dev]"`, then
  `pytest tests/ -v`. Needs no GPU — all 29 existing tests use
  dependency-injected fakes for the real models (per
  `voxreach-server/README.md`). This is a pure regression gate; nothing
  about it depends on hardware existing.
- **`build`** (on push to `main` only, after `test` passes): builds both
  Containerfiles and pushes to GHCR (`ghcr.io/safwan2003/voice/sdr-worker`
  and `ghcr.io/safwan2003/voice/sdr-ui`), tagged with both the git SHA
  and `latest`. Auth uses the automatic `GITHUB_TOKEN` — no new secret to
  manage, since GHCR is tied to the same GitHub account/org as the repo.

**Deploy stage (explicitly manual for now):** once hardware exists,
getting a new image running is `podman pull ghcr.io/.../sdr-worker:latest
&& systemctl restart sdr-worker@1.service` (repeated per worker
instance) — documented as a runbook step in `voxreach-server/README.md`,
not automated. Automating this later (self-hosted runner on the box,
triggered on a successful `build`) is a small addition to the existing
`build` job, not a redesign.

## Data / Update Flow

```
push/PR → CI runs pytest (always) →
  merge to main → CI builds + pushes worker & UI images to GHCR →
    [manual, until hardware exists] operator pulls the new image on the
    office box and restarts the relevant systemd unit(s)
```

## Error Handling

- **Worker crash**: `Restart=on-failure` on the Quadlet — identical
  behavior to today's bare-process unit.
- **Image pull failure during an update**: the currently-running
  container keeps running (Podman doesn't tear down a working container
  just because a pull failed) — a failed update is a no-op, not an
  outage, though it does mean the fix didn't roll out; the operator sees
  this from the pull command's own exit status.
- **GPU passthrough failure** (e.g. NVIDIA Container Toolkit not
  installed/configured on a given box): the worker Quadlet fails to
  start, surfaced the same way any other systemd unit failure is
  (`systemctl status`, journal) — no silent fallback to CPU inference,
  since that would silently produce a far-too-slow, broken-feeling call.

## Testing / Validation

- CI's `test` job is the ongoing regression gate — runs today, no
  hardware required.
- Once real hardware exists: a one-time manual sanity check that GPU
  passthrough actually works (`podman run --rm --device nvidia.com/gpu=all
  <base-image> nvidia-smi`) before trusting it with real calls — this is
  the one piece of this spec that is fundamentally unverifiable without
  the physical box, same limitation the original deployment spec had for
  its own concurrency validation.

## Deliverables (what this phase produces)

- `voxreach-server/deploy/container/worker.Containerfile`
- `voxreach-server/deploy/container/ui.Containerfile`
- `voxreach-server/deploy/systemd/sdr-worker@.container` (Quadlet,
  replacing the current `sdr-worker@.service`)
- `voxreach-server/deploy/systemd/voxreach-ui.container` (new Quadlet)
- `.github/workflows/ci.yml` (or split `test.yml` + `build.yml`) with the
  `test` and `build` jobs described above
- `UI_PORT` added to `deploy/env/office.env.example` and `office.env`
- README updates: the manual pull+restart runbook for deploying a new
  image, and updated production-deploy instructions reflecting the
  Quadlet units

## Migration Notes

- `deploy/systemd/sdr-worker@.service` is replaced by a Quadlet of a
  similar name — `scale-workers.sh` and `OFFICE_NUM_WORKERS` do not
  change.
- `deploy/systemd/livekit-server.service` is untouched.
- No new required env vars for the worker's own logic — `office.env`'s
  LLM/STT/TTS variables are unchanged from the current (post-vLLM-removal)
  set. `UI_PORT` is the only addition, and it already existed as a
  `start.sh`-only default.
- This spec assumes the CUDA version/driver compatibility question gets
  pinned once real hardware is confirmed (a build-arg in the worker
  Containerfile) — not guessed at now.
