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

pip install -e .
pip install omnivoice || pip install "git+https://github.com/k2-fsa/OmniVoice.git"

./start.sh office.env
```

`start.sh` starts a local non-TLS `livekit-server` (`ws://localhost:7880`
— no domain or certs needed for local testing) and the worker — then
generates a test token itself and serves `ui/index.html` on
`http://localhost:8080`, printing a **ready-to-click link with the URL
and token pre-filled**. Open that link, hit Connect, done. Ctrl+C stops
everything it started.

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

sudo cp deploy/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now livekit-server.service
./deploy/systemd/scale-workers.sh /etc/sdr-agent/office.env   # starts OFFICE_NUM_WORKERS worker instances
```

This is what `start.sh` is a dev-mode stand-in for: systemd-managed
(`Restart=on-failure`, boot-start) versions of the same processes, using
the real TLS config (`deploy/livekit/livekit-server.yaml.template`,
rendered via `envsubst` at service start) instead of the local no-TLS one.

## Portability

Every hardware/environment-specific value is an env var — nothing is
hardcoded — so this should run unchanged on any Linux box once `office.env`
is filled in. `start.sh` runs `livekit-server` via Podman if the native
binary isn't installed, but the worker itself still runs natively (not
containerized) — production deployment assumes a Linux server with
systemd. A full `docker-compose.yml` covering every component would be
the natural next step for deeper portability, but hasn't been built.

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
| `OFFICE_DOMAIN` | optional | Production-only — domain for TLS cert lookup, unused by `start.sh` |

`deploy/env/office.env.example` ships with placeholders only — never
commit real credentials.
