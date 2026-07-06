# SDR Voice Agent (Colab Prototype) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a single Google Colab notebook that runs a fully self-hosted, conversational outbound-SDR voice agent (Whisper STT, Qwen2.5 LLM via Ollama, OmniVoice TTS) on LiveKit Agents, reachable from a browser via a self-hosted `livekit-server` tunneled through ngrok.

**Architecture:** Everything (STT, LLM server, TTS, LiveKit server, ngrok tunnels, agent worker) runs inside one Colab GPU instance. STT and TTS are thin custom LiveKit plugin classes wrapping faster-whisper and OmniVoice in-process; the LLM runs via Ollama's OpenAI-compatible server and is consumed through LiveKit's stock `openai.LLM` plugin. A human tests the agent by connecting to it through LiveKit's hosted Agents Playground using printed ngrok URLs.

**Tech Stack:** `livekit-agents`, `livekit-plugins-openai`, `livekit-plugins-silero`, `faster-whisper`, `omnivoice`, `ollama` (Qwen2.5-7B-Instruct), `pyngrok`, self-hosted `livekit-server` binary.

## Global Constraints

- Single deliverable file: `sdr_voice_agent.ipynb` at the repo root — all code lives in notebook cells, no separate `.py` modules or automated test suite (per spec's Non-Goals).
- STT: whisper-large-v3-turbo via `faster-whisper`, in-process (no server).
- LLM: Qwen2.5-7B-Instruct (Ollama default quantization, ~Q4_K_M / "4-bit class") served via Ollama's OpenAI-compatible API on `localhost:11434`, consumed via `livekit.plugins.openai.LLM`.
- TTS: OmniVoice (k2-fsa), in-process (no server), 24000 Hz mono output.
- Room/signaling server: self-hosted `livekit-server --dev`, exposed via two simultaneous ngrok TCP tunnels (port 7880 signaling, port 7881 ICE/TCP media fallback) — not LiveKit Cloud.
- No telephony/SIP, no CRM integration, no custom web UI, no automated pytest suite, no voicemail/DNC/compliance handling — all explicitly out of scope for this phase (see spec Non-Goals).
- Verification throughout is manual (run cell, inspect printed output) per the spec's Testing/Validation section — there is no pytest harness for this notebook.

---

## Task 1: Notebook scaffold, GPU check, and dependency installation

**Files:**
- Create: `sdr_voice_agent.ipynb` (cells tagged `setup-*` below)

**Interfaces:**
- Produces: a working Colab environment with all Python packages importable and GPU confirmed, for every later task to build on.

- [ ] **Step 1: Create the notebook with a title/markdown cell**

Cell (markdown):
```markdown
# Self-Hosted Conversational SDR Voice Agent (Colab Prototype)

Fully self-hosted STT (Whisper) + LLM (Qwen2.5 via Ollama) + TTS (OmniVoice)
voice pipeline on LiveKit Agents, exposed via a self-hosted `livekit-server`
tunneled through ngrok. Test by connecting through LiveKit's Agents Playground.

Non-goals for this notebook: telephony, CRM, custom UI, compliance handling.
```

- [ ] **Step 2: Add GPU check cell**

Cell (code, tag `setup-gpu-check`):
```python
import torch
assert torch.cuda.is_available(), "No GPU detected — set Runtime > Change runtime type > GPU in Colab"
print(f"GPU: {torch.cuda.get_device_name(0)}")
print(f"VRAM: {torch.cuda.get_device_properties(0).total_memory / 1e9:.1f} GB")
```

Run: execute the cell.
Expected: prints a GPU name (e.g. `Tesla T4` or `A100-SXM4-40GB`) and VRAM size, no `AssertionError`. If it raises `AssertionError`, stop and fix the Colab runtime type before continuing to any other task.

- [ ] **Step 3: Add dependency installation cell**

Cell (code, tag `setup-install`):
```python
%pip install -q \
    livekit-agents~=1.0 \
    "livekit-plugins-openai~=1.0" \
    "livekit-plugins-silero~=1.0" \
    faster-whisper \
    ollama \
    pyngrok \
    soundfile

# OmniVoice: try PyPI first, fall back to installing from GitHub source
%pip install -q omnivoice || %pip install -q "git+https://github.com/k2-fsa/OmniVoice.git"
```

- [ ] **Step 4: Run install cell and verify imports**

Run: execute the install cell, then a new cell:
```python
import livekit.agents
import livekit.plugins.openai
import livekit.plugins.silero
import faster_whisper
import omnivoice
import ollama
import pyngrok
print("All imports OK")
```

Expected: `All imports OK` with no `ImportError`/`ModuleNotFoundError`. If `omnivoice` import fails, re-check the fallback install command's output for the actual error before proceeding — do not continue to later tasks with a broken TTS import.

- [ ] **Step 5: Download the livekit-server binary**

Cell (code, tag `setup-livekit-server-binary`):
```python
!curl -sSL https://get.livekit.io | bash
!livekit-server --version
```

Run: execute the cell.
Expected: prints a version string like `livekit-server version 1.x.x` with no error. This confirms the binary is installed and on `PATH` for Task 5.

- [ ] **Step 6: Commit notebook scaffold**

```bash
git add sdr_voice_agent.ipynb
git commit -m "Add notebook scaffold with GPU check and dependency install"
```

---

## Task 2: STT — load and verify faster-whisper transcription

**Files:**
- Modify: `sdr_voice_agent.ipynb` (cells tagged `stt-*`)

**Interfaces:**
- Consumes: nothing from earlier tasks except the installed `faster-whisper` package.
- Produces: a module-level `whisper_model = WhisperModel(...)` instance (variable name `whisper_model`) that Task 6's custom STT plugin will wrap directly.

- [ ] **Step 1: Download a known reference audio + transcript pair**

Cell (code, tag `stt-reference-audio`):
```python
import urllib.request

REFERENCE_AUDIO_PATH = "jfk.flac"
REFERENCE_TRANSCRIPT_SNIPPET = "ask not what your country can do for you"

urllib.request.urlretrieve(
    "https://github.com/openai/whisper/raw/main/tests/jfk.flac",
    REFERENCE_AUDIO_PATH,
)
print("Downloaded:", REFERENCE_AUDIO_PATH)
```

Run: execute the cell.
Expected: `Downloaded: jfk.flac` with no `HTTPError`.

- [ ] **Step 2: Load whisper-large-v3-turbo**

Cell (code, tag `stt-load-model`):
```python
from faster_whisper import WhisperModel

whisper_model = WhisperModel("large-v3-turbo", device="cuda", compute_type="float16")
print("Whisper model loaded")
```

Run: execute the cell.
Expected: `Whisper model loaded` after the model download/load completes (first run downloads weights, may take 1-2 minutes).

- [ ] **Step 3: Verify transcription against the known reference**

Cell (code, tag `stt-verify`):
```python
segments, info = whisper_model.transcribe(REFERENCE_AUDIO_PATH, language="en")
transcript = " ".join(segment.text for segment in segments).strip()
print("Transcript:", transcript)
assert REFERENCE_TRANSCRIPT_SNIPPET in transcript.lower(), f"Expected snippet not found in: {transcript}"
print("STT verification PASSED")
```

Run: execute the cell.
Expected: prints the transcript (containing "...ask not what your country can do for you...") and `STT verification PASSED`. If the assertion fails, do not proceed to Task 6 — the base model must transcribe correctly before it's wrapped in a plugin.

- [ ] **Step 4: Commit**

```bash
git add sdr_voice_agent.ipynb
git commit -m "Add and verify faster-whisper STT model loading"
```

---

## Task 3: LLM — install Ollama, pull Qwen2.5-7B-Instruct, verify chat completion

**Files:**
- Modify: `sdr_voice_agent.ipynb` (cells tagged `llm-*`)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: a running Ollama server on `http://localhost:11434` serving model tag `qwen2.5:7b-instruct`, which Task 8's `openai.LLM` plugin instance will point at via `base_url`.

- [ ] **Step 1: Install and start the Ollama server as a background process**

Cell (code, tag `llm-install-ollama`):
```python
import subprocess
import time

!curl -fsSL https://ollama.com/install.sh | sh

ollama_process = subprocess.Popen(
    ["ollama", "serve"],
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
)
time.sleep(5)
print("Ollama server starting, PID:", ollama_process.pid)
```

Run: execute the cell.
Expected: `Ollama server starting, PID: <number>` with no immediate crash (check `ollama_process.poll() is None` if unsure — `None` means still running).

- [ ] **Step 2: Pull the Qwen2.5-7B-Instruct model**

Cell (code, tag `llm-pull-model`):
```python
!ollama pull qwen2.5:7b-instruct
```

Run: execute the cell.
Expected: download progress output ending in `success` with no error. This model tag is Ollama's standard pre-quantized GGUF build (~Q4_K_M class), matching the spec's "4-bit quantized" requirement.

- [ ] **Step 3: Verify the OpenAI-compatible chat completion endpoint**

Cell (code, tag `llm-verify`):
```python
import requests

response = requests.post(
    "http://localhost:11434/v1/chat/completions",
    json={
        "model": "qwen2.5:7b-instruct",
        "messages": [{"role": "user", "content": "Reply with exactly the word: PONG"}],
        "max_tokens": 10,
    },
    timeout=60,
)
response.raise_for_status()
reply = response.json()["choices"][0]["message"]["content"]
print("LLM reply:", reply)
assert "PONG" in reply.upper(), f"Unexpected reply: {reply}"
print("LLM verification PASSED")
```

Run: execute the cell.
Expected: `LLM reply: PONG` (or similar) and `LLM verification PASSED`.

- [ ] **Step 4: Commit**

```bash
git add sdr_voice_agent.ipynb
git commit -m "Add and verify Ollama-served Qwen2.5-7B-Instruct LLM"
```

---

## Task 4: TTS — load OmniVoice and verify audio synthesis

**Files:**
- Modify: `sdr_voice_agent.ipynb` (cells tagged `tts-*`)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: a module-level `omnivoice_model = OmniVoice.from_pretrained(...)` instance (variable name `omnivoice_model`) that Task 7's custom TTS plugin will wrap directly. Also produces `reference_voice.wav` / reference text used for voice-design generation.

- [ ] **Step 1: Load the OmniVoice model**

Cell (code, tag `tts-load-model`):
```python
import torch
from omnivoice import OmniVoice

omnivoice_model = OmniVoice.from_pretrained(
    "k2-fsa/OmniVoice",
    device_map="cuda:0",
    dtype=torch.float16,
)
print("OmniVoice model loaded")
```

Run: execute the cell.
Expected: `OmniVoice model loaded` (first run downloads weights).

- [ ] **Step 2: Verify synthesis produces valid, non-silent audio**

Cell (code, tag `tts-verify`):
```python
import numpy as np
import soundfile as sf

TEST_SENTENCE = "Hi, this is a quick test of the voice pipeline."

audio_chunks = omnivoice_model.generate(
    text=TEST_SENTENCE,
    instruct="female, medium pitch, american accent, friendly sales tone",
)
audio = audio_chunks[0]

assert isinstance(audio, np.ndarray), f"Expected np.ndarray, got {type(audio)}"
assert audio.ndim == 1 and audio.shape[0] > 0, f"Unexpected shape: {audio.shape}"

duration_seconds = audio.shape[0] / 24000
rms = float(np.sqrt(np.mean(audio.astype(np.float64) ** 2)))
print(f"Duration: {duration_seconds:.2f}s, RMS: {rms:.4f}")
assert duration_seconds > 0.5, "Audio too short — synthesis likely failed"
assert rms > 0.001, "Audio is near-silent — synthesis likely failed"

sf.write("tts_test_output.wav", audio, 24000)
print("TTS verification PASSED — listen to tts_test_output.wav to confirm quality")
```

Run: execute the cell.
Expected: prints duration (a few seconds) and an RMS value clearly above `0.001`, and `TTS verification PASSED`. Manually play `tts_test_output.wav` (e.g. via `IPython.display.Audio("tts_test_output.wav")` in the next cell) to confirm the voice sounds like intelligible speech, not noise.

- [ ] **Step 3: Add a playback cell for manual confirmation**

Cell (code, tag `tts-playback`):
```python
from IPython.display import Audio, display
display(Audio("tts_test_output.wav"))
```

Run: execute the cell and listen to the output.
Expected: clear, intelligible speech saying the test sentence.

- [ ] **Step 4: Commit**

```bash
git add sdr_voice_agent.ipynb
git commit -m "Add and verify OmniVoice TTS model loading"
```

---

## Task 5: Self-hosted livekit-server + dual ngrok tunnels

**Files:**
- Modify: `sdr_voice_agent.ipynb` (cells tagged `server-*`)

**Interfaces:**
- Consumes: the `livekit-server` binary installed in Task 1 Step 5.
- Produces: module-level variables `LIVEKIT_WS_URL` (str, e.g. `wss://0.tcp.ngrok.io:XXXXX` — actually the signaling tunnel's public URL, used by both the agent worker in Task 9 and the human tester in Task 10), `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` (both `"devkey"` / `"secret"`, the `--dev` mode defaults), and a running `livekit-server` process plus two live ngrok tunnels for the lifetime of the notebook session.

- [ ] **Step 1: Set up an ngrok auth token**

Cell (markdown):
```markdown
Before running the next cell, sign up free at https://dashboard.ngrok.com/signup,
copy your authtoken from https://dashboard.ngrok.com/get-started/your-authtoken,
and paste it below. Also reserve one static TCP address at
https://dashboard.ngrok.com/cloud-edge/tcp-addresses (free tier includes one) —
note its host and port, you'll need them in Step 3.
```

Cell (code, tag `server-ngrok-auth`):
```python
from pyngrok import ngrok, conf

NGROK_AUTHTOKEN = "PASTE_YOUR_NGROK_AUTHTOKEN_HERE"  # from dashboard.ngrok.com
conf.get_default().auth_token = NGROK_AUTHTOKEN
ngrok.set_auth_token(NGROK_AUTHTOKEN)
print("ngrok authenticated")
```

Run: execute after pasting a real token.
Expected: `ngrok authenticated` with no error.

- [ ] **Step 2: Write the livekit-server config with the reserved TCP address' port**

Cell (markdown):
```markdown
Set `RESERVED_TCP_PORT` below to the port number from the static TCP address
you reserved in Step 1 (the part after the colon, e.g. for
`6.tcp.ngrok.io:19302` the port is `19302`). This makes `livekit-server`
bind its media/ICE port on the exact same port number ngrok forwards to,
which keeps the address it advertises to browsers correct.
```

Cell (code, tag `server-write-config`):
```python
RESERVED_TCP_HOST = "PASTE_RESERVED_HOST_HERE"   # e.g. "6.tcp.ngrok.io"
RESERVED_TCP_PORT = 0                             # e.g. 19302

import socket
resolved_ip = socket.gethostbyname(RESERVED_TCP_HOST)
print(f"{RESERVED_TCP_HOST} resolves to {resolved_ip}")

config_yaml = f"""
port: 7880
rtc:
  tcp_port: {RESERVED_TCP_PORT}
  use_external_ip: false
  node_ip: {resolved_ip}
keys:
  devkey: secret
"""
with open("livekit-config.yaml", "w") as f:
    f.write(config_yaml)
print(config_yaml)
```

Run: execute the cell after filling in `RESERVED_TCP_HOST` and `RESERVED_TCP_PORT`.
Expected: prints the resolved IP and the written config, no `socket.gaierror`.

- [ ] **Step 3: Start livekit-server with this config**

Cell (code, tag `server-start-livekit`):
```python
import subprocess
import time

livekit_process = subprocess.Popen(
    ["livekit-server", "--config", "livekit-config.yaml"],
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
)
time.sleep(3)
assert livekit_process.poll() is None, "livekit-server exited immediately — check config"
print("livekit-server running, PID:", livekit_process.pid)
```

Run: execute the cell.
Expected: `livekit-server running, PID: <number>`, no immediate exit.

- [ ] **Step 4: Open both ngrok tunnels**

Cell (code, tag `server-ngrok-tunnels`):
```python
signaling_tunnel = ngrok.connect(7880, "tcp")
media_tunnel = ngrok.connect(
    RESERVED_TCP_PORT, "tcp", remote_addr=f"{RESERVED_TCP_HOST}:{RESERVED_TCP_PORT}"
)

print("Signaling tunnel:", signaling_tunnel.public_url)
print("Media tunnel:", media_tunnel.public_url)

# Convert the signaling tunnel's tcp:// URL into the ws:// form the LiveKit
# SDK/Playground expects.
LIVEKIT_WS_URL = signaling_tunnel.public_url.replace("tcp://", "ws://")
LIVEKIT_API_KEY = "devkey"
LIVEKIT_API_SECRET = "secret"
print("LIVEKIT_WS_URL:", LIVEKIT_WS_URL)
```

Run: execute the cell.
Expected: two `public_url` values printed (both `tcp://...ngrok...` form), and `LIVEKIT_WS_URL` printed as a `ws://` URL. The media tunnel's `public_url` should show the exact `RESERVED_TCP_HOST:RESERVED_TCP_PORT` you reserved — if it shows a different, randomly-assigned address instead, the reservation didn't take effect; stop and re-check the ngrok dashboard reservation before continuing.

- [ ] **Step 5: Verify reachability**

Cell (code, tag `server-verify`):
```python
import socket

host, port = LIVEKIT_WS_URL.replace("ws://", "").split(":")
with socket.create_connection((host, int(port)), timeout=10) as sock:
    print(f"Successfully connected to {host}:{port}")
```

Run: execute the cell.
Expected: `Successfully connected to <host>:<port>` with no `TimeoutError`/`ConnectionRefusedError`. If this fails, the ngrok signaling tunnel or livekit-server isn't reachable — do not proceed to Task 9 until this passes.

- [ ] **Step 6: Commit**

```bash
git add sdr_voice_agent.ipynb
git commit -m "Add self-hosted livekit-server behind dual ngrok tunnels"
```

---

## Task 6: Custom STT plugin wrapping faster-whisper

**Files:**
- Modify: `sdr_voice_agent.ipynb` (cells tagged `stt-plugin-*`)

**Interfaces:**
- Consumes: `whisper_model` (the `WhisperModel` instance from Task 2), `REFERENCE_AUDIO_PATH`/`REFERENCE_TRANSCRIPT_SNIPPET` (from Task 2) for verification.
- Produces: a `WhisperSTT` class (subclass of `livekit.agents.stt.STT`) that Task 8's `AgentSession` will instantiate as `stt=WhisperSTT()`.

- [ ] **Step 1: Define the custom STT plugin class**

Cell (code, tag `stt-plugin-define`):
```python
from livekit.agents import stt
from livekit.agents.utils import AudioBuffer
from livekit import rtc
import io

class WhisperSTT(stt.STT):
    def __init__(self):
        super().__init__(
            capabilities=stt.STTCapabilities(
                streaming=False,
                interim_results=False,
            )
        )

    async def _recognize_impl(self, buffer: AudioBuffer, *, language=None, conn_options=None) -> stt.SpeechEvent:
        wav_bytes = io.BytesIO(rtc.combine_audio_frames(buffer).to_wav_bytes())

        segments, _info = whisper_model.transcribe(wav_bytes, language="en")
        text = " ".join(segment.text for segment in segments).strip()

        # Empty or very short output means silence/noise rather than real
        # speech. Forward a marker instead of the raw (empty) text so the
        # LLM's system prompt can react by asking the caller to repeat,
        # rather than the LLM receiving nothing to respond to.
        if len(text) < 2:
            text = "[SILENCE_OR_UNCLEAR_AUDIO]"

        return stt.SpeechEvent(
            type=stt.SpeechEventType.FINAL_TRANSCRIPT,
            alternatives=[stt.SpeechData(language="en", text=text)],
        )

print("WhisperSTT plugin defined")
```

- [ ] **Step 2: Verify the plugin against the reference audio**

Cell (code, tag `stt-plugin-verify`):
```python
import soundfile as sf_read

pcm_data, sample_rate = sf_read.read(REFERENCE_AUDIO_PATH, dtype="int16")
frame = rtc.AudioFrame(
    data=pcm_data.tobytes(),
    sample_rate=sample_rate,
    num_channels=1,
    samples_per_channel=len(pcm_data),
)

whisper_stt_plugin = WhisperSTT()
event = await whisper_stt_plugin._recognize_impl(buffer=[frame], language="en", conn_options=None)
plugin_transcript = event.alternatives[0].text
print("Plugin transcript:", plugin_transcript)
assert REFERENCE_TRANSCRIPT_SNIPPET in plugin_transcript.lower(), f"Expected snippet not found in: {plugin_transcript}"
print("STT plugin verification PASSED")
```

Run: execute the cell.
Expected: prints the transcript and `STT plugin verification PASSED`.

- [ ] **Step 3: Commit**

```bash
git add sdr_voice_agent.ipynb
git commit -m "Add and verify custom WhisperSTT LiveKit plugin"
```

---

## Task 7: Custom TTS plugin wrapping OmniVoice

**Files:**
- Modify: `sdr_voice_agent.ipynb` (cells tagged `tts-plugin-*`)

**Interfaces:**
- Consumes: `omnivoice_model` (the `OmniVoice` instance from Task 4).
- Produces: an `OmniVoiceTTS` class (subclass of `livekit.agents.tts.TTS`) that Task 8's `AgentSession` will instantiate as `tts=OmniVoiceTTS()`.

- [ ] **Step 1: Define the custom TTS plugin class**

Cell (code, tag `tts-plugin-define`):
```python
from livekit.agents import tts
import numpy as np

SDR_VOICE_INSTRUCT = "female, medium pitch, american accent, friendly sales tone"

class OmniVoiceTTS(tts.TTS):
    def __init__(self):
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False),
            sample_rate=24000,
            num_channels=1,
        )

    def synthesize(self, text: str, *, conn_options=None) -> "tts.ChunkedStream":
        return _OmniVoiceChunkedStream(tts=self, input_text=text, conn_options=conn_options)

class _OmniVoiceChunkedStream(tts.ChunkedStream):
    async def _run(self, output_emitter: "tts.AudioEmitter") -> None:
        audio_chunks = omnivoice_model.generate(
            text=self.input_text,
            instruct=SDR_VOICE_INSTRUCT,
        )
        audio = audio_chunks[0]
        pcm16 = (audio * 32767.0).astype(np.int16)

        output_emitter.initialize(
            request_id="",
            sample_rate=24000,
            num_channels=1,
            mime_type="audio/pcm",
        )
        output_emitter.push(pcm16.tobytes())
        output_emitter.flush()

print("OmniVoiceTTS plugin defined")
```

- [ ] **Step 2: Verify the plugin produces valid audio**

Cell (code, tag `tts-plugin-verify`):
```python
omnivoice_tts_plugin = OmniVoiceTTS()
chunked_stream = omnivoice_tts_plugin.synthesize("This is a plugin verification test.")

collected_frames = []
async for synthesized_audio in chunked_stream:
    collected_frames.append(synthesized_audio.frame)

assert len(collected_frames) > 0, "No audio frames produced"
total_samples = sum(f.samples_per_channel for f in collected_frames)
duration_seconds = total_samples / 24000
print(f"Frames: {len(collected_frames)}, duration: {duration_seconds:.2f}s")
assert duration_seconds > 0.3, "Audio too short — plugin synthesis likely failed"
print("TTS plugin verification PASSED")
```

Run: execute the cell.
Expected: prints frame count and duration, and `TTS plugin verification PASSED`.

- [ ] **Step 3: Commit**

```bash
git add sdr_voice_agent.ipynb
git commit -m "Add and verify custom OmniVoiceTTS LiveKit plugin"
```

---

## Task 8: SDR persona and AgentSession assembly

**Files:**
- Modify: `sdr_voice_agent.ipynb` (cells tagged `agent-*`)

**Interfaces:**
- Consumes: `WhisperSTT` (Task 6), `OmniVoiceTTS` (Task 7), `livekit.plugins.openai.LLM` pointed at Ollama (Task 3's server).
- Produces: a `create_sdr_agent_session() -> AgentSession` factory function and an `SDR_INSTRUCTIONS` constant string, both consumed by Task 9's `entrypoint` function.

- [ ] **Step 1: Define the SDR persona system prompt**

Cell (code, tag `agent-persona`):
```python
SDR_INSTRUCTIONS = """
You are Alex, a friendly sales development rep for "Streamline", a fictional
project-management SaaS tool for small teams.

Your job on this call: briefly introduce yourself and Streamline, ask 1-2
discovery questions about how the prospect currently manages projects, and
gauge interest in a short demo. Keep every response to 1-3 sentences —
this is a voice conversation, not a chat, so avoid long monologues.

If the prospect raises an objection (too expensive, already using a tool,
not interested), acknowledge it briefly and ask one clarifying question
before moving on. If they clearly want to end the call, thank them for
their time and wrap up politely.

If you ever receive the exact message "[SILENCE_OR_UNCLEAR_AUDIO]", this
means the audio was silent or unintelligible — do not treat it as
something the prospect said. Simply and briefly ask them to repeat what
they said (e.g. "Sorry, I didn't catch that — could you say that again?").
""".strip()

print(SDR_INSTRUCTIONS)
```

- [ ] **Step 2: Define the AgentSession factory**

Cell (code, tag `agent-session-factory`):
```python
from livekit.agents import Agent, AgentSession
from livekit.plugins import openai, silero

def create_sdr_agent_session() -> AgentSession:
    return AgentSession(
        stt=WhisperSTT(),
        llm=openai.LLM.with_ollama(
            model="qwen2.5:7b-instruct",
            base_url="http://localhost:11434/v1",
        ),
        tts=OmniVoiceTTS(),
        vad=silero.VAD.load(),
    )

class SDRAgent(Agent):
    def __init__(self):
        super().__init__(instructions=SDR_INSTRUCTIONS)

print("AgentSession factory defined")
```

Run: execute both cells.
Expected: no import errors, `AgentSession factory defined` printed.

- [ ] **Step 3: Commit**

```bash
git add sdr_voice_agent.ipynb
git commit -m "Add SDR persona and AgentSession factory wiring STT/LLM/TTS/VAD"
```

---

## Task 9: Full run — start the agent worker

**Files:**
- Modify: `sdr_voice_agent.ipynb` (cells tagged `run-*`)

**Interfaces:**
- Consumes: `create_sdr_agent_session`, `SDRAgent` (Task 8), `LIVEKIT_WS_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` (Task 5).
- Produces: a running LiveKit agent worker process for the lifetime of the notebook session, and printed connection details for Task 10's manual test.

- [ ] **Step 1: Define the entrypoint function**

Cell (code, tag `run-entrypoint`):
```python
from livekit import agents
from livekit.agents import JobContext, WorkerOptions

async def entrypoint(ctx: JobContext):
    await ctx.connect()
    session = create_sdr_agent_session()
    await session.start(agent=SDRAgent(), room=ctx.room)
    await session.generate_reply(
        instructions="Greet the prospect and introduce yourself and Streamline."
    )

print("Entrypoint defined")
```

- [ ] **Step 2: Set environment variables and start the worker**

Cell (code, tag `run-start-worker`):
```python
import os
import threading

os.environ["LIVEKIT_URL"] = LIVEKIT_WS_URL
os.environ["LIVEKIT_API_KEY"] = LIVEKIT_API_KEY
os.environ["LIVEKIT_API_SECRET"] = LIVEKIT_API_SECRET

def run_worker():
    agents.cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))

worker_thread = threading.Thread(target=run_worker, daemon=True)
worker_thread.start()

import time
time.sleep(5)
print("Agent worker started in background thread")
```

Run: execute the cell.
Expected: `Agent worker started in background thread`, and worker log lines (printed to notebook output from the background thread) showing it registered with the LiveKit server without connection errors.

- [ ] **Step 3: Print connection details for manual testing**

Cell (code, tag `run-print-connection-info`):
```python
print("=" * 60)
print("Connect to the agent via LiveKit's Agents Playground:")
print("  1. Open https://agents-playground.livekit.io in your browser")
print(f"  2. Server URL: {LIVEKIT_WS_URL}")
print(f"  3. API Key:    {LIVEKIT_API_KEY}")
print(f"  4. API Secret: {LIVEKIT_API_SECRET}")
print("=" * 60)
```

Run: execute the cell.
Expected: prints the four connection lines with no placeholder values (real `LIVEKIT_WS_URL` from Task 5).

- [ ] **Step 4: Commit**

```bash
git add sdr_voice_agent.ipynb
git commit -m "Add agent worker entrypoint and background run cell"
```

---

## Task 10: Manual end-to-end conversational UAT

**Files:**
- Modify: `sdr_voice_agent.ipynb` (markdown cell tagged `uat-checklist`, no new code)

**Interfaces:**
- Consumes: the running worker from Task 9.
- Produces: nothing code-based — this is the human verification gate the whole notebook builds toward, matching the spec's Testing/Validation section exactly.

- [ ] **Step 1: Add the manual test checklist as a markdown cell**

Cell (markdown, tag `uat-checklist`):
```markdown
## Manual Conversational Test

With the agent worker running (Task 9), open
https://agents-playground.livekit.io, enter the printed Server URL / API
Key / API Secret, and connect. Work through this checklist:

- [ ] **Normal discovery flow**: let the agent greet you and ask its
      discovery question; answer naturally for 2-3 turns.
- [ ] **Interruption**: start talking while the agent is mid-sentence and
      confirm it stops and listens rather than talking over you.
- [ ] **Silence / no input**: stay silent for ~5 seconds and confirm the
      agent asks you to repeat rather than hanging or crashing.

**Success criteria** (from the design spec): natural turn-taking, no
crashes, no dead air longer than ~2-3 seconds, and the agent stays in
character as "Alex from Streamline" throughout.

If any check fails, note which one and revisit the corresponding task
above (STT = Task 6, LLM/persona = Task 8, TTS = Task 7, networking =
Task 5) before re-running this test.
```

- [ ] **Step 2: Run the manual test**

Run: perform the three checklist items above by actually talking to the agent through the Playground.
Expected: all three boxes can be checked per the success criteria. Record the outcome (pass/fail per item) in the notebook's markdown cell by checking the boxes.

- [ ] **Step 3: Commit final notebook state**

```bash
git add sdr_voice_agent.ipynb
git commit -m "Add manual conversational UAT checklist"
```
