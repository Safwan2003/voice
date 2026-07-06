# Self-Hosted Conversational SDR Voice Agent — Colab Prototype

**Date**: 2026-07-06
**Status**: Approved for implementation planning

## Goal

Prove out a natural-sounding, conversational outbound-SDR voice agent using
fully self-hosted models, running end-to-end in a single Google Colab
notebook. This phase is about conversational quality only — no real phone
calls, no CRM integration, no custom UI, no campaign/lead management. Those
come later, once the conversation itself works well.

## Non-Goals (this phase)

- Outbound telephony / SIP / real phone numbers
- CRM integration or lead data storage
- Custom web UI
- Voicemail detection, call recording, compliance (DNC/TCPA) handling
- Production deployment, autoscaling, multi-call concurrency
- Automated test suite

These are explicitly deferred until conversational quality is validated.

## Architecture

```
Browser (LiveKit Agents Playground — LiveKit's own hosted test UI)
        │  WebSocket signaling via ngrok tunnel #1 → livekit-server port 7880
        │  Audio (ICE/TCP fallback) via ngrok tunnel #2 → livekit-server port 7881
        ▼
  Colab Notebook (single GPU), all running together:
    ├─ livekit-server (self-hosted, `--dev` mode)
    │     configured with its externally-visible address set to the
    │     ngrok tunnel #2 address, so it advertises the correct address
    │     for audio/ICE candidates to the browser
    ├─ ngrok (two simultaneous tunnels: one for 7880, one for 7881;
    │     reserved/static ngrok address recommended to avoid the URL
    │     changing on every reconnect)
    ├─ LiveKit Agent worker (Python, `livekit-agents`)
    │     connects to livekit-server over localhost (same machine)
    │     AgentSession pipeline:
    │       STT  → custom plugin wrapping faster-whisper
    │              (whisper-large-v3-turbo, in-process, no server)
    │       LLM  → stock `openai.LLM` plugin, base_url pointed at
    │              a local Ollama server (OpenAI-compatible API)
    │       TTS  → custom plugin wrapping OmniVoice (in-process, no server)
    │     + LiveKit's built-in turn detection / interruption handling
    └─ Ollama subprocess → serves Qwen2.5-7B-Instruct (4-bit quantized)
          on localhost:11434
```

**Why this shape:**

- Colab has no public inbound networking, so a room/signaling server is
  needed as a rendezvous point between the browser and the Colab GPU.
  Rather than depending on LiveKit Cloud, this phase self-hosts
  `livekit-server` directly inside Colab and exposes it via ngrok, to
  match production parity with the eventual office-server deployment as
  closely as possible while still being runnable from a Colab GPU today.
- `livekit-server` needs two separate reachable ports — 7880 for
  WebSocket signaling and 7881 for ICE/TCP media fallback (the fallback
  path designed for clients that can't use raw UDP, which fits this
  tunneled scenario) — so two ngrok tunnels are required, not one.
- STT and TTS have no mature "run as a local server" option for
  faster-whisper or OmniVoice, so those are implemented as small custom
  LiveKit plugin classes running in-process on the agent worker.
- The LLM benefits from a real inference server (streaming token output,
  continuous handling of generation) rather than a hand-rolled wrapper, so
  it runs via Ollama (simple to install in Colab, serves an
  OpenAI-compatible API) and reuses LiveKit's stock, battle-tested
  `openai.LLM` plugin by pointing its `base_url` at localhost.
- No code written against LiveKit's client APIs changes when moving off
  Colab later — only the server/networking config (drop ngrok, point
  `livekit-server` at the office server's real public IP) changes.

## Model Choices

| Stage | Model | Notes |
|---|---|---|
| STT | whisper-large-v3-turbo (via faster-whisper) | Fast, open, runs well on a single GPU alongside the other models |
| LLM | Qwen2.5-7B-Instruct, 4-bit quantized | Apache-2.0, strong instruction-following/tool-calling for its size, fits on a single Colab GPU (T4/L4/A100) alongside STT/TTS |
| TTS | OmniVoice (k2-fsa) | Apache-2.0, self-hosted, RTF ~0.025 (well under real-time), supports voice design/cloning |

## Components

- **Setup cells**: install dependencies (`livekit-agents`, `faster-whisper`,
  `omnivoice`, `ollama`, `pyngrok`), download model weights, pull
  Qwen2.5-7B-Instruct into Ollama.
- **Server cells**: launch `livekit-server --dev`, launch the two ngrok
  tunnels, capture their assigned URLs, write the LiveKit server config
  with the correct external address for the media port.
- **Agent cells**: define the custom `STT` plugin (audio frames in →
  transcribed text out via faster-whisper), the custom `TTS` plugin (text
  in → audio frames out via OmniVoice), and assemble the `AgentSession`
  with the stock `openai.LLM` plugin against the local Ollama endpoint.
- **Persona cell**: a system prompt defining a generic SDR persona (a
  fictional SaaS product, a standard discovery/objection-handling
  conversation flow, instructed to keep responses short and
  conversational since this is voice, not chat).
- **Run cell**: starts the agent worker and prints the ngrok WebSocket URL
  and LiveKit API key/secret for pasting into the LiveKit Agents
  Playground.

## Error Handling

Lightweight, appropriate to a conversational-quality prototype rather than
production:

- Model load failures (e.g. GPU OOM on the shared Colab GPU) fail loudly
  at the setup cell with a clear message — no silent degradation.
- Empty or low-confidence STT output (silence, background noise) causes
  the agent to ask the caller to repeat, rather than forwarding empty
  input to the LLM.
- If the ngrok tunnels drop (e.g. Colab disconnect), the fix is to re-run
  the notebook from the server cells — no automatic reconnection logic in
  this phase.
- Out of scope for this phase: call recording, persistence, retry queues,
  automatic tunnel recovery.

## Testing / Validation

Manual conversational UAT, not automated tests:

1. Run the notebook end-to-end.
2. Connect via LiveKit's hosted Agents Playground using the printed ngrok
   URL and API key/secret.
3. Talk through several rounds covering: a normal discovery flow, an
   interruption (talking over the agent mid-response), and a
   silence/no-input case.

**Success criteria**: natural turn-taking, no crashes, no dead air longer
than ~2-3 seconds, and the agent stays in character as a generic SDR
throughout.

## Migration Path (future phases, not built now)

When moving to the office server: drop ngrok, point `livekit-server` at
the office server's real public IP/domain (or switch to LiveKit Cloud if
preferred at that point), keep the agent worker, STT/LLM/TTS plugin code,
and Ollama setup unchanged. Real telephony (SIP/outbound calling), CRM
integration, a proper UI, and compliance handling are all separate,
later, sub-projects.
