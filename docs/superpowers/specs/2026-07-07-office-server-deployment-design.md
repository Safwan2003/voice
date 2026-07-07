# Office Server Deployment — Production Voice Agent Design

**Date**: 2026-07-07
**Status**: Approved for implementation planning

## Goal

Take the conversational voice pipeline validated in the Colab prototype
(`sdr_voice_agent.ipynb`) and design a production deployment that runs on a
self-hosted office server instead of Colab, using vLLM instead of Ollama for
LLM serving, self-hosted `livekit-server` with real networking instead of
ngrok/LiveKit Cloud, and an architecture that works on the initial hardware
(a single ~12GB-VRAM NVIDIA GPU, not yet purchased) while scaling cleanly if
more/better GPUs are added later — without needing a redesign at that point.

**This is a planning/spec phase.** The Colab notebook is the validated
prototype and is not modified by this work — it stays as-is. This spec
covers a separate deployment target (the office server), reusing the
prototype's proven STT/TTS plugin logic and persona, ported into a
production-appropriate project structure.

## Non-Goals (this phase)

- Actual telephony/SIP/outbound calling integration (still a separate,
  later phase — unchanged from the original Colab spec's deferral)
- CRM integration, custom UI beyond what already exists (`index.html`
  tester), compliance handling
- Autoscaling/orchestration frameworks (Kubernetes, etc.) — scaling in this
  phase means manually adding worker processes or GPUs, not dynamic
  orchestration
- Uptime monitoring/alerting
- Multi-machine clustering (this spec assumes a single office server box;
  a multi-box deployment is a further future concern)
- Modifying `sdr_voice_agent.ipynb` — that notebook remains the Colab
  prototype, untouched by this work

## Capacity Analysis (why the architecture looks the way it does)

The office server's GPU is not yet purchased; the only known detail is
"NVIDIA, 12GB VRAM" (e.g. RTX 3060/4070-class consumer card). This section
grounds the architecture in real numbers rather than assumption.

**VRAM budget on a 12GB card, all three models co-located:**

| Component | VRAM (resident) | Basis |
|---|---|---|
| Whisper large-v3-turbo (int8_float16) | ~1.2GB | Same quantization already proven in the Colab notebook |
| OmniVoice TTS | ~3GB | Model weights are 2.45GB on disk (fp16); budgeted with activation overhead |
| CUDA context / driver overhead | ~1GB | Two separate processes (worker + vLLM) each hold a CUDA context |
| **Remaining for vLLM (weights + KV cache)** | **~6.8GB** | |

**KV-cache math** (bytes/token = 2 × layers × kv_heads × head_dim × 2),
computed from each model's real `config.json`:

| Model | Params | 4-bit weights | KV cache/token | Notes |
|---|---|---|---|---|
| Qwen2.5-7B-Instruct | 7B | ~3.7GB | 56KB | Leaves only ~3GB for KV cache — workable but tight, and its larger per-token compute cost eats into the shared GPU's compute budget that Whisper/OmniVoice also need |
| Qwen2.5-3B-Instruct | 3B | ~1.7GB | 36KB | Leaves ~5GB for KV cache — comfortable, lower compute footprint |
| Qwen2.5-1.5B-Instruct | 1.5B | ~0.85GB | 28KB | Most headroom, but weaker conversational quality — fallback if 3B proves too slow |

**Key finding: memory is not the real constraint.** Even the 7B model at
4-bit leaves enough KV cache for far more concurrent short conversations
than this deployment needs — and since this is spoken conversation, the LLM
only needs to generate tokens fast enough to stay ahead of TTS playback
(roughly 4-6 tokens/sec per call is sufficient), not as fast as possible.

**The real ceiling is GPU *compute* contention** between Whisper, the LLM,
and OmniVoice sharing one card's CUDA cores. Without the exact GPU model in
hand, an exact tokens/sec figure isn't knowable yet — but the reasoned
estimate is **2-4 concurrent calls on a single 12GB card using Qwen2.5-3B**
(not 7B — its higher per-token compute cost leaves too little headroom for
the other two models). This must be validated for real once hardware
arrives (see Testing/Validation).

**vLLM memory behavior** (confirmed via vLLM's own docs): `--gpu-memory-utilization`
defaults to 90% of *total* VRAM, but respects memory already claimed by
other processes — if Whisper+OmniVoice claim ~4.2GB before vLLM starts, a
`gpu-memory-utilization` of e.g. 0.6 on a 12GB card correctly leaves vLLM
with the remaining budget rather than fighting the other models for
memory. Load order matters: Whisper and OmniVoice must load before vLLM
starts.

## Architecture

Rather than bundling STT+LLM+TTS into one inseparable unit per call (as the
Colab prototype does, out of Colab's single-GPU-single-process
convenience), the LLM is split out into **one shared vLLM service** that
all calls talk to over the network. Each **agent worker process** (STT +
TTS + conversation logic — the prototype's code, unchanged) becomes a
lightweight, horizontally-replicable unit.

```
                          ┌─────────────────────────┐
                          │   livekit-server         │
                          │  (self-hosted, real IP,  │
                          │   TLS via real domain)   │
                          └───────────┬─────────────┘
                     ┌────────────────┼────────────────┐
                     ▼                ▼                ▼
              Agent Worker #1   Agent Worker #2   Agent Worker #N
              (STT+TTS+logic)   (STT+TTS+logic)   (STT+TTS+logic)
                     │                │                │
                     └────────────────┼────────────────┘
                                       ▼
                          ┌─────────────────────────┐
                          │      vLLM server         │
                          │  (OpenAI-compatible API)  │
                          │   one shared instance     │
                          └─────────────────────────┘
```

**Why this shape:**

- Concurrency for the LLM stage is handled once, efficiently, by vLLM's own
  continuous batching — no need for N separate LLM copies each eating
  their own multi-GB VRAM slice.
- Concurrency for STT/TTS scales by running more worker processes.
  LiveKit's own job dispatcher automatically routes incoming calls to
  whichever registered worker is free — no custom load balancer needed,
  this is inherent to `livekit-agents`.
- **Day one (single 12GB card):** vLLM and one worker's STT/TTS share the
  card, carefully budgeted per the capacity analysis above.
- **Later, with a second GPU:** two config-only options, no code changes —
  dedicate the new GPU entirely to vLLM (freeing the original card for
  more STT/TTS workers, raising concurrency substantially since one GPU
  dedicated purely to vLLM can serve many calls), or add another full
  worker on the new card. The choice is a deployment config decision, not
  an engineering one.
- No code written against LiveKit's client APIs or the STT/TTS plugin
  classes changes when moving off Colab — matches the original prototype
  spec's migration promise. Only the LLM's `base_url`/model name (Ollama →
  vLLM) and the server's networking config change.

## Components

### 1. `livekit-server` (self-hosted, real networking)

Replaces both ngrok (Colab prototype phase 1) and LiveKit Cloud (Colab
phase 2). Requires a real reachable address — either the office has a
public IP with router port-forwarding, or a domain name plus a reverse
proxy/tunnel if the network is more locked down. The exact choice is a
config-time decision made once the office network situation is confirmed;
this spec keeps the deployment scripts parameterized rather than
hardcoding one networking approach.

**Production requirement not present in the Colab prototype:** TLS
(`wss://`). ngrok and LiveKit Cloud both provided HTTPS/WSS automatically;
a self-hosted deployment needs a domain and a certificate (e.g. Let's
Encrypt via certbot).

### 2. vLLM server

One shared instance, exposing an OpenAI-compatible HTTP API on localhost
(or LAN-reachable, if workers ever run on separate machines). Run as a
systemd service, not a manually-started process.

Config knobs (environment-driven, tuned once real hardware is known):

- `OFFICE_LLM_MODEL` — default `Qwen/Qwen2.5-3B-Instruct-AWQ` for the
  initial 12GB-shared scenario. Documented upgrade path to
  `Qwen/Qwen2.5-7B-Instruct-AWQ` once vLLM has a dedicated GPU or a
  larger card.
- `OFFICE_VLLM_GPU_MEM_UTIL` — default conservative (~0.6) when sharing a
  card with STT/TTS; raise (~0.85) once vLLM has a dedicated GPU.

### 3. Agent worker process(es)

Ported from the Colab notebook's logic — `WhisperSTT` plugin, `OmniVoiceTTS`
plugin, SDR persona, `AgentSession` factory, and the entrypoint — into a
proper Python package suitable for running as a systemd service, since
notebooks aren't a production hosting mechanism. **The logic itself does
not change**: the only edit is the LLM's `base_url`/model name, since vLLM
and Ollama both expose the same OpenAI-compatible chat completions API, so
the stock `openai.LLM` plugin the prototype already uses works unmodified.

Config knob: `OFFICE_NUM_WORKERS` — how many worker processes to run,
tuned to whatever the hardware can support (starting point: 1, per the
capacity analysis above).

## Error Handling (production upgrade from the Colab prototype's "fail loudly, no auto-recovery")

- **vLLM overload**: each worker sets its LiveKit `load_threshold` so it
  stops accepting *new* calls once its backing vLLM's queue is deep —
  degrades by declining new calls rather than breaking active ones.
- **Process crashes**: vLLM and worker processes run under systemd with
  `Restart=on-failure` — a transient crash doesn't take the whole system
  down, unlike the Colab notebook where a crash just meant re-running
  cells.
- **Networking/certificate issues**: no monitoring/alerting in this phase
  — explicitly flagged as a known gap for a later phase, following the
  same deferral pattern the original Colab spec used.
- Silence/low-confidence STT handling carries over unchanged from the
  prototype (the `[SILENCE_OR_UNCLEAR_AUDIO]` marker approach already
  proven to work).

## Testing / Validation

1. Same manual conversational UAT as the Colab prototype's Task 10 (normal
   discovery flow, interruption, silence handling) run against the office
   server deployment.
2. **New: explicit concurrency validation once hardware is in hand.** Open
   2-4 simultaneous test calls (reusing the token-generation approach
   already built for the Colab tester) and confirm response latency holds
   up under real concurrent load. This validates the capacity analysis's
   "2-4 concurrent calls" estimate for real, rather than leaving it as
   math alone — the estimate depends on GPU compute throughput that isn't
   knowable until the actual card is in the server.

## Deliverables (what this phase produces)

A new, separate project structure (not inside/modifying the Colab
notebook) containing:

- A Python package with the STT/TTS plugin classes, persona, and
  `AgentSession` factory, ported from the notebook's proven logic
- A systemd unit (or equivalent) for the vLLM service, parameterized by
  `OFFICE_LLM_MODEL` and `OFFICE_VLLM_GPU_MEM_UTIL`
- A systemd unit template for agent worker processes, parameterized by
  `OFFICE_NUM_WORKERS`
- `livekit-server` configuration for real networking (TLS, real
  IP/domain), parameterized rather than hardcoded to one networking
  approach
- A config/env file capturing `LIVEKIT_URL`, API key/secret, and the
  hardware-dependent knobs above, documented so they can be tuned once
  the actual GPU(s) are confirmed

## Migration Notes

- STT/TTS plugin code, persona, and `AgentSession` assembly: unchanged
  from the Colab prototype.
- LLM: `openai.LLM` plugin unchanged; only `base_url` and model name
  change (Ollama's `localhost:11434` → vLLM's endpoint).
- Networking: ngrok/LiveKit Cloud replaced with self-hosted
  `livekit-server` on real infrastructure, per the original prototype
  spec's already-planned migration path.
- Hardware-dependent values (`OFFICE_LLM_MODEL`,
  `OFFICE_VLLM_GPU_MEM_UTIL`, `OFFICE_NUM_WORKERS`) are config, not code —
  tuned once the actual GPU(s) are confirmed, without needing to revisit
  this design.
