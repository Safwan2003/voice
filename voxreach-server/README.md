# voxreach-server — Office Server Deployment

Production deployment of the Voxreach AI voice agent: an outbound SDR
voice pipeline (STT + LLM + TTS over LiveKit's real-time transport),
ported from the validated Colab prototype (`../colab/sdr_voice_agent.ipynb`)
into a package meant to run on a self-hosted server with a GPU for
STT/TTS. The LLM leg talks to a hosted API (Groq by default; OpenAI or
Claude are config-only swaps) — it does not need local GPU capacity, and
there's no local LLM process to run at all.

See `../docs/superpowers/specs/2026-07-07-office-server-deployment-design.md`
and `../docs/superpowers/specs/2026-07-08-multi-tenant-foundation-design.md`
for the full design rationale (written when vLLM was the only LLM path,
since removed — the GPU/VRAM figures for Whisper and OmniVoice there
still apply; the vLLM-specific VRAM budget section no longer applies).

## Architecture, briefly

Two separate processes — not an HTTP API:

- **`livekit-server`** (Go binary, self-hosted) — real-time signaling/media
  server. The only network-facing "server" in the traditional sense.
- **`sdr_agent` worker** (this package) — a long-running process using the
  `livekit-agents` SDK. It registers with `livekit-server` and receives
  conversation jobs pushed to it (job-dispatch model, not request/response)
  — it never listens on a port itself. STT (faster-whisper) and TTS
  (OmniVoice) run in-process inside this worker, GPU-resident. The LLM is
  a hosted API call (Groq/OpenAI/Anthropic, config-selected via
  `OFFICE_LLM_PROVIDER`) — no local LLM process.

## Run the tests (any machine, no GPU needed)

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

All 30 tests pass without a GPU — model instances are dependency-injected
fakes in tests; real model loading only happens in `worker.py`'s
`load_models()`, which needs real hardware and isn't unit-tested.

## Run it locally for real (quick dev/test)

A GPU is only needed for real-quality STT/TTS (see `WHISPER_DEVICE=cpu`
below for a GPU-free correctness-only path). With the default
`OFFICE_LLM_PROVIDER=groq`, the LLM leg needs no GPU at all — just a
[Groq API key](https://console.groq.com/keys).

```bash
cp deploy/env/office.env.example office.env
# edit office.env:
# - generate real LIVEKIT_API_KEY/LIVEKIT_API_SECRET with
#   livekit-server generate-keys
#   (self-hosted — nobody issues these to you, you generate the pair
#   yourself and it just needs to match everywhere)
# - set GROQ_API_KEY (or switch OFFICE_LLM_PROVIDER to openai/anthropic)

./deploy/container/run-local.sh office.env
```

`run-local.sh` builds Podman images automatically (no local Python environment setup needed beyond Podman),
then starts a local non-TLS `livekit-server` (`ws://localhost:7880`
— no domain or certs needed for local testing), the UI/token service, and
the worker. Open `http://localhost:8080`, enter the shared secret
(`UI_ACCESS_SECRET` in `office.env`), and click **Get Token** — it fetches
a fresh connection token itself, no copy/pasting. Ctrl+C stops everything
it started.

Prefer to do it by hand, or connect via the LiveKit Agents Playground
instead of `ui/index.html`? Generate a token yourself:

```bash
set -a; . office.env; set +a
python scripts/generate-test-token.py
```

## Deploy to production (real domain, TLS, auto-restart)

```bash
cp deploy/env/office.env.example /etc/sdr-agent/office.env
# fill in real LIVEKIT_URL (wss://), LIVEKIT_API_KEY/SECRET, OFFICE_DOMAIN
# (needs valid certs at /etc/letsencrypt/live/$OFFICE_DOMAIN/)
# and GROQ_API_KEY (or your chosen OFFICE_LLM_PROVIDER's key)

sudo mkdir -p /etc/containers/systemd
sudo cp deploy/systemd/sdr-worker@.container deploy/systemd/voxreach-ui.container /etc/containers/systemd/
sudo cp deploy/systemd/livekit-server.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now livekit-server.service
# Create host cache directory for Hugging Face weights (persists across container rebuilds)
sudo mkdir -p /opt/sdr-agent/hf-cache
sudo systemctl enable --now voxreach-ui.service
./deploy/systemd/scale-workers.sh /etc/sdr-agent/office.env   # starts OFFICE_NUM_WORKERS worker instances
```

This deploys systemd-managed (`Restart=on-failure`, boot-start) versions of the components,
using Podman Quadlets for the containerized worker and UI service (deployed to `/etc/containers/systemd/`,
not `/etc/systemd/system/` — they're picked up by `podman-system-generator` on `daemon-reload`).
The real TLS config (`deploy/livekit/livekit-server.yaml.template`, rendered via `envsubst`
at service start) is used instead of the local no-TLS dev config.

## Updating a running deployment

CI builds and pushes new images automatically on every merge to `main`.
Getting a new image running on the office server is currently a manual
step (no hardware exists yet to automate this against):

```bash
podman pull ghcr.io/safwan2003/voice/sdr-worker:latest
podman pull ghcr.io/safwan2003/voice/sdr-ui:latest
sudo systemctl restart sdr-worker@1.service   # repeat per worker instance
sudo systemctl restart voxreach-ui.service
```

## Portability

Every hardware/environment-specific value is an env var — nothing is
hardcoded — so this should run unchanged on any Linux box once `office.env`
is filled in. Both dev (`run-local.sh`) and production deployment use Podman
containerization for full isolation and reproducibility. Production deployment
assumes a Linux server with systemd and Podman, using Quadlet units for
service management. A full `docker-compose.yml` covering every component would be
an alternative for non-systemd deployments, but hasn't been built.

## `.env` keys

| Key | Required? | Purpose |
|---|---|---|
| `LIVEKIT_URL` | **required** | Where the worker connects — `ws://localhost:7880` for local dev, `wss://your-domain` for production |
| `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` | **required** | Self-generated pair (`livekit-server generate-keys`) shared by the server and every client |
| `OFFICE_LLM_PROVIDER` | optional (default `groq`) | `groq` / `openai` / `anthropic` — selects the hosted LLM backend |
| `GROQ_API_KEY` / `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | required for the matching provider | API key for the selected hosted provider (`anthropic` needs `pip install -e ".[anthropic]"`) |
| `OFFICE_LLM_MODEL` | optional (defaults per-provider — see `config.py`) | Model name for whichever provider is selected |
| `OFFICE_NUM_WORKERS` | optional (default `1`) | Worker instance count (deploy-only, read by `scale-workers.sh`) |
| `OFFICE_LOAD_THRESHOLD` | optional (default `0.8`) | Backpressure — worker stops accepting new calls above this load |
| `WHISPER_MODEL_SIZE` / `WHISPER_COMPUTE_TYPE` / `WHISPER_DEVICE` | optional | STT model variant/precision/device |
| `OMNIVOICE_MODEL_ID` / `OMNIVOICE_DEVICE` | optional | TTS model/device |
| `TENANTS_DATA_PATH` | optional (default `data/tenants.json`) | Tenant persona/greeting store location |
| `OFFICE_DOMAIN` | optional | Production-only — domain for TLS cert lookup, unused by `run-local.sh` |
| `UI_PORT` | optional (default `8080`) | Port the UI/token service listens on |
| `UI_ACCESS_SECRET` | required for the UI service | Shared secret gating `POST /api/token` — treat like a password |

`deploy/env/office.env.example` ships with placeholders only — never
commit real credentials.
