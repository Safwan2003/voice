# voxreach-server — Office Server Deployment

Production deployment of the Voxreach AI voice agent: an outbound SDR
voice pipeline (STT + LLM + TTS over LiveKit's real-time transport),
ported from the validated Colab prototype (`../colab/sdr_voice_agent.ipynb`)
into a package meant to run on a self-hosted server with a GPU.

See `../docs/superpowers/specs/2026-07-07-office-server-deployment-design.md`
and `../docs/superpowers/specs/2026-07-08-multi-tenant-foundation-design.md`
for the full design rationale.

## Architecture, briefly

Three separate processes — not an HTTP API:

- **`livekit-server`** (Go binary, self-hosted) — real-time signaling/media
  server. The only network-facing "server" in the traditional sense.
- **vLLM** (Python) — serves the LLM over an OpenAI-compatible HTTP API.
  The one piece of this stack that looks like a typical web server.
- **`sdr_agent` worker** (this package) — a long-running process using the
  `livekit-agents` SDK. It registers with `livekit-server` and receives
  conversation jobs pushed to it (job-dispatch model, not request/response)
  — it never listens on a port itself.

## Run the tests (any machine, no GPU needed)

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

All 23 tests pass without a GPU — model instances are dependency-injected
fakes in tests; real model loading only happens in `worker.py`'s
`load_models()`, which needs real hardware and isn't unit-tested.

## Run it locally for real (single GPU machine, quick dev/test)

```bash
cp deploy/env/office.env.example office.env
# edit office.env: generate real LIVEKIT_API_KEY/LIVEKIT_API_SECRET with
#   livekit-server generate-keys
# (self-hosted — nobody issues these to you, you generate the pair
# yourself and it just needs to match everywhere)

pip install -e .
pip install omnivoice || pip install "git+https://github.com/k2-fsa/OmniVoice.git"

./start.sh office.env
```

`start.sh` starts vLLM, a local non-TLS `livekit-server`
(`ws://localhost:7880` — no domain or certs needed for local testing), and
the worker — then generates a test token itself and serves `ui/index.html`
on `http://localhost:8080`, printing a **ready-to-click link with the URL
and token pre-filled**. Open that link, hit Connect, done. Ctrl+C stops
all four processes (vLLM, livekit-server, worker, the UI's HTTP server).

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

sudo cp deploy/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now vllm.service
sudo systemctl enable --now livekit-server.service
./deploy/systemd/scale-workers.sh /etc/sdr-agent/office.env   # starts OFFICE_NUM_WORKERS worker instances
```

This is what `start.sh` is a dev-mode stand-in for: the same three
components, but systemd-managed (`Restart=on-failure`, boot-start) and
using the real TLS config (`deploy/livekit/livekit-server.yaml.template`,
rendered via `envsubst` at service start) instead of the local no-TLS one.

## Portability

Every hardware/environment-specific value is an env var — nothing is
hardcoded — so this should run unchanged on any Linux box once `office.env`
is filled in. It is **not containerized**: deployment assumes a Linux
server with systemd. Docker support (one image per component, wired with
`docker-compose.yml`) would be the natural next step for true any-OS
portability, but hasn't been built.

## `.env` keys

| Key | Required? | Purpose |
|---|---|---|
| `LIVEKIT_URL` | **required** | Where the worker connects — `ws://localhost:7880` for local dev, `wss://your-domain` for production |
| `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` | **required** | Self-generated pair (`livekit-server generate-keys`) shared by the server and every client |
| `OFFICE_LLM_MODEL` | optional (default `Qwen/Qwen2.5-3B-Instruct-AWQ`) | Model vLLM serves |
| `OFFICE_VLLM_BASE_URL` | optional (default `http://localhost:8000/v1`) | Where the worker's LLM client points |
| `OFFICE_VLLM_GPU_MEM_UTIL` | optional (default `0.6`) | vLLM's GPU memory budget (deploy-only, read by the systemd unit/start.sh) |
| `OFFICE_NUM_WORKERS` | optional (default `1`) | Worker instance count (deploy-only, read by `scale-workers.sh`) |
| `OFFICE_LOAD_THRESHOLD` | optional (default `0.8`) | Backpressure — worker stops accepting new calls above this load |
| `WHISPER_MODEL_SIZE` / `WHISPER_COMPUTE_TYPE` / `WHISPER_DEVICE` | optional | STT model variant/precision/device |
| `OMNIVOICE_MODEL_ID` / `OMNIVOICE_DEVICE` | optional | TTS model/device |
| `TENANTS_DATA_PATH` | optional (default `data/tenants.json`) | Tenant persona/greeting store location |
| `OFFICE_DOMAIN` | optional | Production-only — domain for TLS cert lookup, unused by `start.sh` |

`deploy/env/office.env.example` ships with placeholders only — never
commit real credentials.
