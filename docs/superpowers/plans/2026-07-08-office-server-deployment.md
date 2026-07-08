# Office Server Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port the validated Colab SDR voice agent pipeline (`sdr_voice_agent.ipynb`) into a production-appropriate Python package plus systemd/config deployment artifacts that run on a self-hosted office server, per `docs/superpowers/specs/2026-07-07-office-server-deployment-design.md`, with the tenant-scoping seams from `docs/superpowers/specs/2026-07-08-multi-tenant-foundation-design.md` built in from the start.

**Architecture:** A new `office_server/` project (separate from, and non-modifying of, the Colab notebook) containing a `sdr_agent` Python package (STT/TTS plugins, a local JSON-backed tenant/persona store, `AgentSession` factory, worker entrypoint — logic ported unchanged from the notebook, only re-wired for dependency injection so it's unit-testable without a GPU) plus a `deploy/` directory of systemd units and config templates for `vllm`, the agent worker(s), and `livekit-server`. All hardware-dependent knobs are environment variables, never hardcoded. The worker resolves which tenant's persona/greeting to use from the LiveKit job's metadata, defaulting to a single `"default"` tenant today — no dashboard or database exists yet to set anything else, but the plumbing is real.

**Tech Stack:** Python 3.10+, `livekit-agents~=1.0`, `livekit-plugins-openai~=1.0`, `livekit-plugins-silero~=1.0`, `faster-whisper`, `omnivoice` (k2-fsa), `vLLM` (separate service, not a Python dependency of this package), systemd, `envsubst` (gettext), pytest + pytest-asyncio for tests.

## Global Constraints

- `livekit-agents~=1.0`, `livekit-plugins-openai~=1.0`, `livekit-plugins-silero~=1.0` — exact version floors carried over from the Colab prototype's proven dependency set (spec: "no code written against LiveKit's client APIs... changes").
- STT/TTS plugin logic, persona text, and `AgentSession` wiring are **behaviorally unchanged** from the notebook (spec: "The logic itself does not change") — only the LLM's `base_url`/model name changes (Ollama → vLLM), and model instances move from notebook globals to constructor-injected dependencies for testability.
- Persona/greeting text is **data, not code** (multi-tenant-foundation spec) — it lives in a `Tenant` record resolved by `tenant_id`, not a module-level constant. The `"default"` tenant's persona/greeting content is byte-for-byte the same text the notebook used; only its storage location changes.
- `tenant_id` flows from the call itself (`ctx.job.metadata`), never from a global or hardcoded default baked into application logic — the fallback to `"default"` when metadata is empty is the one and only place that constant is assumed.
- All hardware-dependent values (`OFFICE_LLM_MODEL`, `OFFICE_VLLM_GPU_MEM_UTIL`, `OFFICE_NUM_WORKERS`, `OFFICE_VLLM_BASE_URL`, `OFFICE_LOAD_THRESHOLD`, `OFFICE_DOMAIN`, `TENANTS_DATA_PATH`, Whisper/OmniVoice device+precision knobs) must be environment-driven, never hardcoded in code or committed config (spec Components section + Deliverables).
- vLLM and worker processes run under systemd with `Restart=on-failure` (spec Error Handling section).
- Networking must support TLS (`wss://`) via a real domain + certificate — no ngrok/LiveKit Cloud (spec Components §1).
- `sdr_voice_agent.ipynb` is not modified by any task in this plan (spec Non-Goals).
- Do not commit real LiveKit/API credentials — `deploy/env/office.env.example` ships with placeholder values only.

---

## File Structure

```
office_server/
  pyproject.toml
  src/
    sdr_agent/
      __init__.py
      config.py       # env-var loading + validation (OfficeConfig dataclass)
      stt.py           # WhisperSTT plugin (ported, model injected via constructor)
      tts.py           # OmniVoiceTTS plugin (ported, model injected via constructor)
      tenants.py        # Tenant dataclass + JsonTenantStore (local JSON "database")
      session.py         # create_sdr_agent_session() factory + SDRAgent(tenant)
      worker.py           # model loading, tenant resolution, entrypoint, CLI main()
  data/
    tenants.json           # seed tenant records (id, name, persona/greeting text)
  deploy/
    env/
      office.env.example
    systemd/
      vllm.service
      sdr-worker@.service
      livekit-server.service
      scale-workers.sh
    livekit/
      livekit-server.yaml.template
  tests/
    test_config.py
    test_stt.py
    test_tts.py
    test_tenants.py
    test_session.py
    test_worker.py
    test_deploy_files.py
```

---

### Task 1: Project scaffold + config module

**Files:**
- Create: `office_server/pyproject.toml`
- Create: `office_server/src/sdr_agent/__init__.py`
- Create: `office_server/src/sdr_agent/config.py`
- Test: `office_server/tests/test_config.py`

**Interfaces:**
- Produces: `sdr_agent.config.OfficeConfig` (frozen dataclass with fields `livekit_url, livekit_api_key, livekit_api_secret, llm_model, vllm_base_url, load_threshold, whisper_model_size, whisper_compute_type, whisper_device, omnivoice_model_id, omnivoice_device, tenants_data_path`), `sdr_agent.config.load_config() -> OfficeConfig`, `sdr_agent.config.ConfigError`, `sdr_agent.config.REQUIRED_ENV_VARS: tuple[str, ...]`, `sdr_agent.config.OPTIONAL_ENV_VARS: tuple[str, ...]`.

- [ ] **Step 1: Create the project directory and pyproject.toml**

```bash
mkdir -p office_server/src/sdr_agent office_server/tests office_server/deploy/env office_server/deploy/systemd office_server/deploy/livekit
```

Create `office_server/pyproject.toml`:

```toml
[project]
name = "sdr-agent"
version = "0.1.0"
description = "Office server production deployment of the SDR voice agent"
requires-python = ">=3.10"
dependencies = [
    "livekit-agents~=1.0",
    "livekit-plugins-openai~=1.0",
    "livekit-plugins-silero~=1.0",
    "faster-whisper",
    "soundfile",
    "numpy",
]
# omnivoice has no reliable PyPI release; install separately:
#   pip install omnivoice || pip install "git+https://github.com/k2-fsa/OmniVoice.git"

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "pyyaml>=6.0",
]

[project.scripts]
sdr-worker = "sdr_agent.worker:main"

[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

Create empty `office_server/src/sdr_agent/__init__.py`.

- [ ] **Step 2: Install the package in editable/dev mode**

```bash
cd office_server && pip install -e ".[dev]"
```

Expected: installs successfully (network required for `livekit-agents` etc.; if unavailable in this environment, note it and proceed — Steps 3+ below only need `pytest` itself to run since `config.py` has no livekit imports).

- [ ] **Step 3: Write the failing tests**

Create `office_server/tests/test_config.py`:

```python
import pytest

from sdr_agent.config import ConfigError, load_config


REQUIRED = {
    "LIVEKIT_URL": "wss://voice.example-office.com",
    "LIVEKIT_API_KEY": "test-key",
    "LIVEKIT_API_SECRET": "test-secret",
}


def _set_required(monkeypatch):
    for name, value in REQUIRED.items():
        monkeypatch.setenv(name, value)


def _clear_optional(monkeypatch):
    for name in (
        "OFFICE_LLM_MODEL",
        "OFFICE_VLLM_BASE_URL",
        "OFFICE_LOAD_THRESHOLD",
        "WHISPER_MODEL_SIZE",
        "WHISPER_COMPUTE_TYPE",
        "WHISPER_DEVICE",
        "OMNIVOICE_MODEL_ID",
        "OMNIVOICE_DEVICE",
        "TENANTS_DATA_PATH",
    ):
        monkeypatch.delenv(name, raising=False)


def test_load_config_raises_when_required_var_missing(monkeypatch):
    for name in REQUIRED:
        monkeypatch.delenv(name, raising=False)
    _clear_optional(monkeypatch)

    with pytest.raises(ConfigError):
        load_config()


def test_load_config_applies_defaults_for_optional_vars(monkeypatch):
    _set_required(monkeypatch)
    _clear_optional(monkeypatch)

    config = load_config()

    assert config.livekit_url == REQUIRED["LIVEKIT_URL"]
    assert config.llm_model == "Qwen/Qwen2.5-3B-Instruct-AWQ"
    assert config.vllm_base_url == "http://localhost:8000/v1"
    assert config.load_threshold == 0.8
    assert config.whisper_model_size == "large-v3-turbo"
    assert config.whisper_compute_type == "int8_float16"
    assert config.whisper_device == "cuda"
    assert config.omnivoice_model_id == "k2-fsa/OmniVoice"
    assert config.omnivoice_device == "cuda:0"
    assert config.tenants_data_path == "data/tenants.json"


def test_load_config_respects_explicit_overrides(monkeypatch):
    _set_required(monkeypatch)
    monkeypatch.setenv("OFFICE_LLM_MODEL", "Qwen/Qwen2.5-7B-Instruct-AWQ")
    monkeypatch.setenv("OFFICE_LOAD_THRESHOLD", "0.5")

    config = load_config()

    assert config.llm_model == "Qwen/Qwen2.5-7B-Instruct-AWQ"
    assert config.load_threshold == 0.5


def test_required_and_optional_env_var_lists_are_disjoint():
    from sdr_agent.config import OPTIONAL_ENV_VARS, REQUIRED_ENV_VARS

    assert set(REQUIRED_ENV_VARS).isdisjoint(OPTIONAL_ENV_VARS)
    assert REQUIRED_ENV_VARS == ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET")
```

- [ ] **Step 4: Run tests to verify they fail**

```bash
cd office_server && pytest tests/test_config.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'sdr_agent.config'` (or `ImportError`).

- [ ] **Step 5: Write `office_server/src/sdr_agent/config.py`**

```python
from __future__ import annotations

import os
from dataclasses import dataclass


class ConfigError(RuntimeError):
    pass


REQUIRED_ENV_VARS = ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET")
OPTIONAL_ENV_VARS = (
    "OFFICE_LLM_MODEL",
    "OFFICE_VLLM_BASE_URL",
    "OFFICE_LOAD_THRESHOLD",
    "WHISPER_MODEL_SIZE",
    "WHISPER_COMPUTE_TYPE",
    "WHISPER_DEVICE",
    "OMNIVOICE_MODEL_ID",
    "OMNIVOICE_DEVICE",
    "TENANTS_DATA_PATH",
)


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ConfigError(f"Required environment variable {name} is not set")
    return value


def _optional(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class OfficeConfig:
    livekit_url: str
    livekit_api_key: str
    livekit_api_secret: str
    llm_model: str
    vllm_base_url: str
    load_threshold: float
    whisper_model_size: str
    whisper_compute_type: str
    whisper_device: str
    omnivoice_model_id: str
    omnivoice_device: str
    tenants_data_path: str


def load_config() -> OfficeConfig:
    return OfficeConfig(
        livekit_url=_require("LIVEKIT_URL"),
        livekit_api_key=_require("LIVEKIT_API_KEY"),
        livekit_api_secret=_require("LIVEKIT_API_SECRET"),
        llm_model=_optional("OFFICE_LLM_MODEL", "Qwen/Qwen2.5-3B-Instruct-AWQ"),
        vllm_base_url=_optional("OFFICE_VLLM_BASE_URL", "http://localhost:8000/v1"),
        load_threshold=float(_optional("OFFICE_LOAD_THRESHOLD", "0.8")),
        whisper_model_size=_optional("WHISPER_MODEL_SIZE", "large-v3-turbo"),
        whisper_compute_type=_optional("WHISPER_COMPUTE_TYPE", "int8_float16"),
        whisper_device=_optional("WHISPER_DEVICE", "cuda"),
        omnivoice_model_id=_optional("OMNIVOICE_MODEL_ID", "k2-fsa/OmniVoice"),
        omnivoice_device=_optional("OMNIVOICE_DEVICE", "cuda:0"),
        tenants_data_path=_optional("TENANTS_DATA_PATH", "data/tenants.json"),
    )
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
cd office_server && pytest tests/test_config.py -v
```

Expected: 4 passed.

- [ ] **Step 7: Commit**

```bash
git add office_server/pyproject.toml office_server/src/sdr_agent/__init__.py office_server/src/sdr_agent/config.py office_server/tests/test_config.py
git commit -m "Add office-server project scaffold and env-driven config module"
```

---

### Task 2: WhisperSTT plugin

**Files:**
- Create: `office_server/src/sdr_agent/stt.py`
- Test: `office_server/tests/test_stt.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `sdr_agent.stt.WhisperSTT(model)` (constructor takes a `faster_whisper.WhisperModel`-shaped object with a `.transcribe(wav_bytes, language="en") -> (segments, info)` method), `sdr_agent.stt.SILENCE_MARKER: str`, `sdr_agent.stt.MIN_TRANSCRIPT_LENGTH: int`.

- [ ] **Step 1: Write the failing tests**

Create `office_server/tests/test_stt.py`:

```python
from dataclasses import dataclass

import pytest

from sdr_agent.stt import SILENCE_MARKER, WhisperSTT


@dataclass
class FakeSegment:
    text: str


class FakeWhisperModel:
    def __init__(self, segments):
        self._segments = segments

    def transcribe(self, wav_bytes, language="en"):
        return self._segments, {}


class FakeCombined:
    def to_wav_bytes(self):
        return b"fake-wav-bytes"


def _patch_combine_audio_frames(monkeypatch):
    monkeypatch.setattr("sdr_agent.stt.rtc.combine_audio_frames", lambda buffer: FakeCombined())


@pytest.mark.asyncio
async def test_recognize_returns_transcribed_text(monkeypatch):
    _patch_combine_audio_frames(monkeypatch)
    model = FakeWhisperModel([FakeSegment("Hello there"), FakeSegment("how are you")])
    plugin = WhisperSTT(model)

    event = await plugin._recognize_impl(buffer=[], language="en", conn_options=None)

    assert event.alternatives[0].text == "Hello there how are you"


@pytest.mark.asyncio
async def test_recognize_returns_silence_marker_for_empty_transcript(monkeypatch):
    _patch_combine_audio_frames(monkeypatch)
    model = FakeWhisperModel([FakeSegment("")])
    plugin = WhisperSTT(model)

    event = await plugin._recognize_impl(buffer=[], language="en", conn_options=None)

    assert event.alternatives[0].text == SILENCE_MARKER


@pytest.mark.asyncio
async def test_recognize_returns_silence_marker_for_single_char_noise(monkeypatch):
    _patch_combine_audio_frames(monkeypatch)
    model = FakeWhisperModel([FakeSegment("h")])
    plugin = WhisperSTT(model)

    event = await plugin._recognize_impl(buffer=[], language="en", conn_options=None)

    assert event.alternatives[0].text == SILENCE_MARKER
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd office_server && pytest tests/test_stt.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'sdr_agent.stt'`.

- [ ] **Step 3: Write `office_server/src/sdr_agent/stt.py`**

```python
import io

from livekit import rtc
from livekit.agents import stt
from livekit.agents.utils import AudioBuffer

SILENCE_MARKER = "[SILENCE_OR_UNCLEAR_AUDIO]"
MIN_TRANSCRIPT_LENGTH = 2


class WhisperSTT(stt.STT):
    def __init__(self, model):
        super().__init__(
            capabilities=stt.STTCapabilities(
                streaming=False,
                interim_results=False,
            )
        )
        self._model = model

    async def _recognize_impl(
        self, buffer: AudioBuffer, *, language=None, conn_options=None
    ) -> stt.SpeechEvent:
        wav_bytes = io.BytesIO(rtc.combine_audio_frames(buffer).to_wav_bytes())

        segments, _info = self._model.transcribe(wav_bytes, language="en")
        text = " ".join(segment.text for segment in segments).strip()

        # Empty or very short output means silence/noise rather than real
        # speech. Forward a marker instead of the raw (empty) text so the
        # LLM's system prompt can react by asking the caller to repeat,
        # rather than the LLM receiving nothing to respond to.
        if len(text) < MIN_TRANSCRIPT_LENGTH:
            text = SILENCE_MARKER

        return stt.SpeechEvent(
            type=stt.SpeechEventType.FINAL_TRANSCRIPT,
            alternatives=[stt.SpeechData(language="en", text=text)],
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd office_server && pytest tests/test_stt.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add office_server/src/sdr_agent/stt.py office_server/tests/test_stt.py
git commit -m "Port WhisperSTT plugin with injected model for testability"
```

---

### Task 3: OmniVoiceTTS plugin

**Files:**
- Create: `office_server/src/sdr_agent/tts.py`
- Test: `office_server/tests/test_tts.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `sdr_agent.tts.OmniVoiceTTS(model)` (constructor takes an object with `.generate(text=..., instruct=...) -> list[np.ndarray]`), `sdr_agent.tts.VOICE_INSTRUCT: str`, `sdr_agent.tts.SAMPLE_RATE: int`, `sdr_agent.tts._OmniVoiceChunkedStream`.

- [ ] **Step 1: Write the failing tests**

Create `office_server/tests/test_tts.py`:

```python
import numpy as np
import pytest

from sdr_agent.tts import SAMPLE_RATE, VOICE_INSTRUCT, OmniVoiceTTS, _OmniVoiceChunkedStream


class FakeOmniVoiceModel:
    def __init__(self, samples):
        self._samples = samples
        self.calls = []

    def generate(self, text, instruct):
        self.calls.append((text, instruct))
        return [self._samples]


class FakeTTSHolder:
    def __init__(self, model):
        self._model = model


class FakeEmitter:
    def __init__(self):
        self.initialized = None
        self.pushed = b""
        self.flushed = False

    def initialize(self, **kwargs):
        self.initialized = kwargs

    def push(self, data):
        self.pushed += data

    def flush(self):
        self.flushed = True


@pytest.mark.asyncio
async def test_run_synthesizes_and_emits_pcm16():
    samples = np.array([0.0, 0.5, -0.5], dtype=np.float32)
    model = FakeOmniVoiceModel(samples)

    stream = _OmniVoiceChunkedStream.__new__(_OmniVoiceChunkedStream)
    stream._tts = FakeTTSHolder(model)
    stream.input_text = "Hello prospect"

    emitter = FakeEmitter()
    await stream._run(emitter)

    assert model.calls == [("Hello prospect", VOICE_INSTRUCT)]
    assert emitter.initialized == {
        "request_id": "",
        "sample_rate": SAMPLE_RATE,
        "num_channels": 1,
        "mime_type": "audio/pcm",
    }
    expected_pcm16 = (samples * 32767.0).astype(np.int16).tobytes()
    assert emitter.pushed == expected_pcm16
    assert emitter.flushed is True


def test_synthesize_returns_chunked_stream_with_input_text():
    model = FakeOmniVoiceModel(np.array([0.0], dtype=np.float32))
    plugin = OmniVoiceTTS(model)

    stream = plugin.synthesize("This is a test.")

    assert isinstance(stream, _OmniVoiceChunkedStream)
    assert stream.input_text == "This is a test."
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd office_server && pytest tests/test_tts.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'sdr_agent.tts'`.

- [ ] **Step 3: Write `office_server/src/sdr_agent/tts.py`**

```python
import numpy as np
from livekit.agents import DEFAULT_API_CONNECT_OPTIONS, APIConnectOptions, tts

VOICE_INSTRUCT = "female, moderate pitch, american accent"
SAMPLE_RATE = 24000


class OmniVoiceTTS(tts.TTS):
    def __init__(self, model):
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False),
            sample_rate=SAMPLE_RATE,
            num_channels=1,
        )
        self._model = model

    def synthesize(
        self, text: str, *, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS
    ) -> "tts.ChunkedStream":
        return _OmniVoiceChunkedStream(tts=self, input_text=text, conn_options=conn_options)


class _OmniVoiceChunkedStream(tts.ChunkedStream):
    async def _run(self, output_emitter: "tts.AudioEmitter") -> None:
        audio_chunks = self._tts._model.generate(
            text=self.input_text,
            instruct=VOICE_INSTRUCT,
        )
        audio = audio_chunks[0]
        pcm16 = (audio * 32767.0).astype(np.int16)

        output_emitter.initialize(
            request_id="",
            sample_rate=SAMPLE_RATE,
            num_channels=1,
            mime_type="audio/pcm",
        )
        output_emitter.push(pcm16.tobytes())
        output_emitter.flush()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd office_server && pytest tests/test_tts.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add office_server/src/sdr_agent/tts.py office_server/tests/test_tts.py
git commit -m "Port OmniVoiceTTS plugin with injected model for testability"
```

---

### Task 4: Tenant store + AgentSession factory

**Files:**
- Create: `office_server/src/sdr_agent/tenants.py`
- Create: `office_server/data/tenants.json`
- Create: `office_server/src/sdr_agent/session.py`
- Test: `office_server/tests/test_tenants.py`
- Test: `office_server/tests/test_session.py`

**Interfaces:**
- Consumes: `sdr_agent.stt.WhisperSTT` (Task 2), `sdr_agent.tts.OmniVoiceTTS` (Task 3), `sdr_agent.config.OfficeConfig` (Task 1).
- Produces: `sdr_agent.tenants.Tenant` (frozen dataclass: `id, name, persona_instructions, greeting_instructions`), `sdr_agent.tenants.TenantNotFoundError`, `sdr_agent.tenants.DEFAULT_TENANT_ID: str = "default"`, `sdr_agent.tenants.JsonTenantStore(path).get_tenant(tenant_id) -> Tenant`, `sdr_agent.session.create_sdr_agent_session(config, whisper_model, omnivoice_model, vad) -> AgentSession`, `sdr_agent.session.SDRAgent(tenant: Tenant)`.

- [ ] **Step 1: Write the failing tests for the tenant store**

Create `office_server/tests/test_tenants.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd office_server && pytest tests/test_tenants.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'sdr_agent.tenants'`.

- [ ] **Step 3: Write `office_server/src/sdr_agent/tenants.py`**

```python
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
```

- [ ] **Step 4: Create the seed data file `office_server/data/tenants.json`**

Generate it with a script rather than hand-typing escaped JSON, so the
persona text is byte-for-byte the notebook's original (no transcription
risk):

```bash
python3 <<'PYEOF'
import json
from pathlib import Path

persona_instructions = """You are Alex, a friendly sales development rep for "Streamline", a fictional
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
they said (e.g. "Sorry, I didn't catch that — could you say that again?")."""

data = {
    "tenants": [
        {
            "id": "default",
            "name": "Streamline (demo tenant)",
            "persona_instructions": persona_instructions,
            "greeting_instructions": "Greet the prospect and introduce yourself and Streamline.",
        }
    ]
}

path = Path("office_server/data/tenants.json")
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(data, indent=2) + "\n")
print("wrote", path)
PYEOF
```

- [ ] **Step 5: Run the tenant store tests to verify they pass**

```bash
cd office_server && pytest tests/test_tenants.py -v
```

Expected: 3 passed.

- [ ] **Step 6: Write the failing tests for the session factory**

Create `office_server/tests/test_session.py`:

```python
from sdr_agent.config import OfficeConfig
from sdr_agent.tenants import Tenant


def _config(**overrides):
    defaults = dict(
        livekit_url="wss://example.com",
        livekit_api_key="key",
        livekit_api_secret="secret",
        llm_model="Qwen/Qwen2.5-3B-Instruct-AWQ",
        vllm_base_url="http://localhost:8000/v1",
        load_threshold=0.8,
        whisper_model_size="large-v3-turbo",
        whisper_compute_type="int8_float16",
        whisper_device="cuda",
        omnivoice_model_id="k2-fsa/OmniVoice",
        omnivoice_device="cuda:0",
        tenants_data_path="data/tenants.json",
    )
    defaults.update(overrides)
    return OfficeConfig(**defaults)


def _tenant(**overrides):
    defaults = dict(
        id="acme",
        name="Acme Corp",
        persona_instructions="You are Sam from Acme.",
        greeting_instructions="Greet the prospect and introduce yourself and Acme.",
    )
    defaults.update(overrides)
    return Tenant(**defaults)


def test_sdr_agent_uses_tenant_persona_instructions():
    from sdr_agent.session import SDRAgent

    tenant = _tenant(persona_instructions="You are Sam from Acme, selling widgets.")
    agent = SDRAgent(tenant)

    assert agent.instructions == "You are Sam from Acme, selling widgets."


def test_create_sdr_agent_session_wires_components(monkeypatch):
    calls = {}

    class FakeWhisperSTT:
        def __init__(self, model):
            calls["stt_model"] = model

    class FakeOmniVoiceTTS:
        def __init__(self, model):
            calls["tts_model"] = model

    class FakeLLM:
        def __init__(self, *, model, base_url, api_key):
            calls["llm"] = {"model": model, "base_url": base_url, "api_key": api_key}

    class FakeAgentSession:
        def __init__(self, *, stt, llm, tts, vad):
            calls["session"] = {"stt": stt, "llm": llm, "tts": tts, "vad": vad}

    import sdr_agent.session as session_module

    monkeypatch.setattr(session_module, "WhisperSTT", FakeWhisperSTT)
    monkeypatch.setattr(session_module, "OmniVoiceTTS", FakeOmniVoiceTTS)
    monkeypatch.setattr(session_module.openai, "LLM", FakeLLM)
    monkeypatch.setattr(session_module, "AgentSession", FakeAgentSession)

    config = _config(llm_model="test-model", vllm_base_url="http://vllm.local/v1")
    whisper_model, omnivoice_model, vad = object(), object(), object()

    session_module.create_sdr_agent_session(config, whisper_model, omnivoice_model, vad)

    assert calls["stt_model"] is whisper_model
    assert calls["tts_model"] is omnivoice_model
    assert calls["llm"] == {
        "model": "test-model",
        "base_url": "http://vllm.local/v1",
        "api_key": "not-needed",
    }
    assert calls["session"]["vad"] is vad
```

- [ ] **Step 7: Run tests to verify they fail**

```bash
cd office_server && pytest tests/test_session.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'sdr_agent.session'`.

- [ ] **Step 8: Write `office_server/src/sdr_agent/session.py`**

```python
from livekit.agents import Agent, AgentSession
from livekit.plugins import openai

from .config import OfficeConfig
from .stt import WhisperSTT
from .tenants import Tenant
from .tts import OmniVoiceTTS


def create_sdr_agent_session(
    config: OfficeConfig, whisper_model, omnivoice_model, vad
) -> AgentSession:
    return AgentSession(
        stt=WhisperSTT(whisper_model),
        llm=openai.LLM(
            model=config.llm_model,
            base_url=config.vllm_base_url,
            api_key="not-needed",
        ),
        tts=OmniVoiceTTS(omnivoice_model),
        vad=vad,
    )


class SDRAgent(Agent):
    def __init__(self, tenant: Tenant):
        super().__init__(instructions=tenant.persona_instructions)
```

- [ ] **Step 9: Run tests to verify they pass**

```bash
cd office_server && pytest tests/test_tenants.py tests/test_session.py -v
```

Expected: 5 passed.

- [ ] **Step 10: Commit**

```bash
git add office_server/src/sdr_agent/tenants.py office_server/data/tenants.json office_server/src/sdr_agent/session.py office_server/tests/test_tenants.py office_server/tests/test_session.py
git commit -m "Add local JSON tenant store and wire AgentSession/SDRAgent to resolved tenants"
```

---

### Task 5: Model loading + worker entrypoint + CLI main

**Files:**
- Create: `office_server/src/sdr_agent/worker.py`
- Test: `office_server/tests/test_worker.py`

**Interfaces:**
- Consumes: `sdr_agent.config.load_config` (Task 1), `sdr_agent.session.create_sdr_agent_session`, `sdr_agent.session.SDRAgent` (Task 4), `sdr_agent.tenants.JsonTenantStore`, `sdr_agent.tenants.DEFAULT_TENANT_ID` (Task 4).
- Produces: `sdr_agent.worker.load_models(config) -> tuple[whisper_model, omnivoice_model, vad]`, `sdr_agent.worker.build_entrypoint(config, whisper_model, omnivoice_model, vad, tenant_store) -> Callable[[JobContext], Awaitable[None]]`, `sdr_agent.worker.main() -> None`.

- [ ] **Step 1: Write the failing tests**

Create `office_server/tests/test_worker.py`:

```python
import pytest

from sdr_agent.session import SDRAgent
from sdr_agent.tenants import DEFAULT_TENANT_ID, Tenant
from sdr_agent.worker import build_entrypoint


class FakeJob:
    def __init__(self, metadata):
        self.metadata = metadata


class FakeCtx:
    def __init__(self, metadata=""):
        self.connected = False
        self.room = object()
        self.job = FakeJob(metadata)

    async def connect(self):
        self.connected = True


class FakeSession:
    def __init__(self):
        self.start_call = None
        self.generate_reply_instructions = None

    async def start(self, *, agent, room):
        self.start_call = {"agent": agent, "room": room}

    async def generate_reply(self, *, instructions):
        self.generate_reply_instructions = instructions


class FakeTenantStore:
    def __init__(self, tenants_by_id):
        self._tenants_by_id = tenants_by_id
        self.requested_ids = []

    def get_tenant(self, tenant_id):
        self.requested_ids.append(tenant_id)
        return self._tenants_by_id[tenant_id]


ACME_TENANT = Tenant(
    id="acme",
    name="Acme Corp",
    persona_instructions="You are Sam from Acme.",
    greeting_instructions="Greet the prospect and introduce yourself and Acme.",
)

DEFAULT_TENANT = Tenant(
    id=DEFAULT_TENANT_ID,
    name="Streamline (demo tenant)",
    persona_instructions="You are Alex from Streamline.",
    greeting_instructions="Greet the prospect and introduce yourself and Streamline.",
)


@pytest.mark.asyncio
async def test_entrypoint_resolves_tenant_from_job_metadata_and_greets(monkeypatch):
    fake_session = FakeSession()
    create_session_args = {}

    def fake_create_session(config, whisper_model, omnivoice_model, vad):
        create_session_args["args"] = (config, whisper_model, omnivoice_model, vad)
        return fake_session

    import sdr_agent.worker as worker_module

    monkeypatch.setattr(worker_module, "create_sdr_agent_session", fake_create_session)

    tenant_store = FakeTenantStore({"acme": ACME_TENANT})
    config, whisper_model, omnivoice_model, vad = object(), object(), object(), object()
    entrypoint = build_entrypoint(config, whisper_model, omnivoice_model, vad, tenant_store)

    ctx = FakeCtx(metadata="acme")
    await entrypoint(ctx)

    assert ctx.connected is True
    assert tenant_store.requested_ids == ["acme"]
    assert create_session_args["args"] == (config, whisper_model, omnivoice_model, vad)
    assert isinstance(fake_session.start_call["agent"], SDRAgent)
    assert fake_session.start_call["agent"].instructions == ACME_TENANT.persona_instructions
    assert fake_session.start_call["room"] is ctx.room
    assert fake_session.generate_reply_instructions == ACME_TENANT.greeting_instructions


@pytest.mark.asyncio
async def test_entrypoint_falls_back_to_default_tenant_when_metadata_empty(monkeypatch):
    fake_session = FakeSession()

    def fake_create_session(config, whisper_model, omnivoice_model, vad):
        return fake_session

    import sdr_agent.worker as worker_module

    monkeypatch.setattr(worker_module, "create_sdr_agent_session", fake_create_session)

    tenant_store = FakeTenantStore({DEFAULT_TENANT_ID: DEFAULT_TENANT})
    config, whisper_model, omnivoice_model, vad = object(), object(), object(), object()
    entrypoint = build_entrypoint(config, whisper_model, omnivoice_model, vad, tenant_store)

    ctx = FakeCtx(metadata="")
    await entrypoint(ctx)

    assert tenant_store.requested_ids == [DEFAULT_TENANT_ID]
    assert fake_session.generate_reply_instructions == DEFAULT_TENANT.greeting_instructions
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd office_server && pytest tests/test_worker.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'sdr_agent.worker'`.

- [ ] **Step 3: Write `office_server/src/sdr_agent/worker.py`**

```python
from pathlib import Path

from livekit import agents
from livekit.agents import JobContext, WorkerOptions

from .config import load_config
from .session import SDRAgent, create_sdr_agent_session
from .tenants import DEFAULT_TENANT_ID, JsonTenantStore


def load_models(config):
    import torch
    from faster_whisper import WhisperModel
    from livekit.plugins import silero
    from omnivoice import OmniVoice

    # Load order matters: Whisper and OmniVoice must claim their VRAM
    # before vLLM (a separate process/service) starts, so vLLM's
    # gpu-memory-utilization budget correctly accounts for what's already
    # resident (see office-server-deployment-design.md Capacity Analysis).
    whisper_model = WhisperModel(
        config.whisper_model_size,
        device=config.whisper_device,
        compute_type=config.whisper_compute_type,
    )
    omnivoice_model = OmniVoice.from_pretrained(
        config.omnivoice_model_id,
        device_map=config.omnivoice_device,
        dtype=torch.float16,
    )
    torch.cuda.empty_cache()
    vad = silero.VAD.load()
    return whisper_model, omnivoice_model, vad


def build_entrypoint(config, whisper_model, omnivoice_model, vad, tenant_store):
    async def entrypoint(ctx: JobContext):
        await ctx.connect()
        tenant_id = (ctx.job.metadata or "").strip() or DEFAULT_TENANT_ID
        tenant = tenant_store.get_tenant(tenant_id)

        session = create_sdr_agent_session(config, whisper_model, omnivoice_model, vad)
        await session.start(agent=SDRAgent(tenant), room=ctx.room)
        await session.generate_reply(instructions=tenant.greeting_instructions)

    return entrypoint


def main() -> None:
    config = load_config()
    tenant_store = JsonTenantStore(Path(config.tenants_data_path))
    whisper_model, omnivoice_model, vad = load_models(config)
    entrypoint = build_entrypoint(config, whisper_model, omnivoice_model, vad, tenant_store)
    agents.cli.run_app(
        WorkerOptions(entrypoint_fnc=entrypoint, load_threshold=config.load_threshold)
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd office_server && pytest tests/test_worker.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add office_server/src/sdr_agent/worker.py office_server/tests/test_worker.py
git commit -m "Resolve tenant from job metadata in worker entrypoint, with default fallback"
```

---

### Task 6: Deploy env file + vLLM systemd unit

**Files:**
- Create: `office_server/deploy/env/office.env.example`
- Create: `office_server/deploy/systemd/vllm.service`
- Test: `office_server/tests/test_deploy_files.py` (new file — this task starts it)

**Interfaces:**
- Consumes: `sdr_agent.config.REQUIRED_ENV_VARS`, `sdr_agent.config.OPTIONAL_ENV_VARS` (Task 1), to keep the env file and code in sync.
- Produces: `office_server/deploy/env/office.env.example`, `office_server/deploy/systemd/vllm.service`, plus reusable test helpers `_read(path)` and `_parse_env_file(text)` in `test_deploy_files.py` that later tasks' tests will also use.

- [ ] **Step 1: Write the failing test**

Create `office_server/tests/test_deploy_files.py`:

```python
import re
from pathlib import Path

DEPLOY_DIR = Path(__file__).resolve().parent.parent / "deploy"


def _read(relative_path: str) -> str:
    path = DEPLOY_DIR / relative_path
    assert path.exists(), f"missing deploy file: {relative_path}"
    return path.read_text()


def _parse_env_file(text: str) -> dict[str, str]:
    result = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        result[key.strip()] = value.strip()
    return result


def test_office_env_example_covers_all_config_vars():
    from sdr_agent.config import OPTIONAL_ENV_VARS, REQUIRED_ENV_VARS

    env_vars = _parse_env_file(_read("env/office.env.example"))

    deploy_only_vars = {"OFFICE_NUM_WORKERS", "OFFICE_VLLM_GPU_MEM_UTIL", "OFFICE_DOMAIN"}
    expected = set(REQUIRED_ENV_VARS) | set(OPTIONAL_ENV_VARS) | deploy_only_vars

    assert expected.issubset(env_vars.keys())


def test_vllm_service_reads_env_file_and_restarts_on_failure():
    unit = _read("systemd/vllm.service")

    assert "EnvironmentFile=/etc/sdr-agent/office.env" in unit
    assert "Restart=on-failure" in unit
    assert re.search(r"ExecStart=.*\$\{OFFICE_LLM_MODEL\}", unit)
    assert re.search(r"ExecStart=.*\$\{OFFICE_VLLM_GPU_MEM_UTIL\}", unit)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd office_server && pytest tests/test_deploy_files.py -v
```

Expected: FAIL — `AssertionError: missing deploy file: env/office.env.example`.

- [ ] **Step 3: Create `office_server/deploy/env/office.env.example`**

```bash
# LiveKit server connection (required — no defaults; used by both the
# agent worker and, for the key pair, the livekit-server config template)
LIVEKIT_URL=wss://voice.example-office.com
LIVEKIT_API_KEY=CHANGE_ME
LIVEKIT_API_SECRET=CHANGE_ME

# LLM serving (vLLM) — see Capacity Analysis in
# docs/superpowers/specs/2026-07-07-office-server-deployment-design.md
# for why 3B is the day-one default on a shared 12GB card
OFFICE_LLM_MODEL=Qwen/Qwen2.5-3B-Instruct-AWQ
OFFICE_VLLM_BASE_URL=http://localhost:8000/v1
OFFICE_VLLM_GPU_MEM_UTIL=0.6

# Worker scaling and backpressure
OFFICE_NUM_WORKERS=1
OFFICE_LOAD_THRESHOLD=0.8

# STT (faster-whisper)
WHISPER_MODEL_SIZE=large-v3-turbo
WHISPER_COMPUTE_TYPE=int8_float16
WHISPER_DEVICE=cuda

# TTS (OmniVoice)
OMNIVOICE_MODEL_ID=k2-fsa/OmniVoice
OMNIVOICE_DEVICE=cuda:0

# Tenant/persona data store — local JSON file today (see
# docs/superpowers/specs/2026-07-08-multi-tenant-foundation-design.md);
# path is absolute here since the worker's systemd WorkingDirectory may
# differ from this repo's layout
TENANTS_DATA_PATH=/opt/sdr-agent/data/tenants.json

# livekit-server TLS — domain must have valid certs at
# /etc/letsencrypt/live/$OFFICE_DOMAIN/ (see livekit-server.yaml.template)
OFFICE_DOMAIN=voice.example-office.com
```

- [ ] **Step 4: Create `office_server/deploy/systemd/vllm.service`**

```ini
[Unit]
Description=vLLM OpenAI-compatible LLM server for SDR voice agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
EnvironmentFile=/etc/sdr-agent/office.env
ExecStart=/opt/sdr-agent/venv-vllm/bin/vllm serve ${OFFICE_LLM_MODEL} --port 8000 --gpu-memory-utilization ${OFFICE_VLLM_GPU_MEM_UTIL}
Restart=on-failure
RestartSec=5
User=sdr-agent

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 5: Run test to verify it passes**

```bash
cd office_server && pytest tests/test_deploy_files.py -v
```

Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add office_server/deploy/env/office.env.example office_server/deploy/systemd/vllm.service office_server/tests/test_deploy_files.py
git commit -m "Add deploy env template and vLLM systemd service"
```

---

### Task 7: Agent worker systemd template + scaling script

**Files:**
- Create: `office_server/deploy/systemd/sdr-worker@.service`
- Create: `office_server/deploy/systemd/scale-workers.sh`
- Modify: `office_server/tests/test_deploy_files.py`

**Interfaces:**
- Consumes: `_read`, `_parse_env_file` helpers already in `test_deploy_files.py` (Task 6).
- Produces: `office_server/deploy/systemd/sdr-worker@.service`, `office_server/deploy/systemd/scale-workers.sh` (reads `OFFICE_NUM_WORKERS` from an env file passed as `$1`, calls `systemctl enable --now sdr-worker@N.service` for `N` in `1..OFFICE_NUM_WORKERS`).

- [ ] **Step 1: Write the failing tests**

Append to `office_server/tests/test_deploy_files.py`:

```python
import os
import subprocess
import sys


def test_sdr_worker_service_reads_env_file_and_restarts_on_failure():
    unit = _read("systemd/sdr-worker@.service")

    assert "EnvironmentFile=/etc/sdr-agent/office.env" in unit
    assert "Restart=on-failure" in unit
    assert "Requires=vllm.service" in unit
    assert "sdr_agent.worker" in unit


def test_scale_workers_enables_one_instance_per_configured_worker(tmp_path):
    script = DEPLOY_DIR / "systemd" / "scale-workers.sh"
    assert script.exists()

    env_file = tmp_path / "office.env"
    env_file.write_text("OFFICE_NUM_WORKERS=3\n")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_file = tmp_path / "systemctl.log"
    stub = bin_dir / "systemctl"
    stub.write_text(f'#!/bin/sh\necho "$@" >> "{log_file}"\n')
    stub.chmod(0o755)

    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"

    result = subprocess.run(
        ["sh", str(script), str(env_file)],
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    logged_calls = log_file.read_text().splitlines()
    assert logged_calls == [
        "enable --now sdr-worker@1.service",
        "enable --now sdr-worker@2.service",
        "enable --now sdr-worker@3.service",
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd office_server && pytest tests/test_deploy_files.py -v -k "sdr_worker or scale_workers"
```

Expected: FAIL — missing files.

- [ ] **Step 3: Create `office_server/deploy/systemd/sdr-worker@.service`**

```ini
[Unit]
Description=SDR voice agent worker (%i)
After=network-online.target vllm.service
Wants=network-online.target
Requires=vllm.service

[Service]
Type=simple
EnvironmentFile=/etc/sdr-agent/office.env
ExecStart=/opt/sdr-agent/venv/bin/python -m sdr_agent.worker
Restart=on-failure
RestartSec=5
User=sdr-agent

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 4: Create `office_server/deploy/systemd/scale-workers.sh`**

```bash
#!/bin/sh
set -eu

ENV_FILE="${1:-/etc/sdr-agent/office.env}"
if [ ! -f "$ENV_FILE" ]; then
  echo "Env file not found: $ENV_FILE" >&2
  exit 1
fi

# shellcheck disable=SC1090
. "$ENV_FILE"
NUM_WORKERS="${OFFICE_NUM_WORKERS:-1}"

i=1
while [ "$i" -le "$NUM_WORKERS" ]; do
  systemctl enable --now "sdr-worker@${i}.service"
  i=$((i + 1))
done

echo "Enabled and started ${NUM_WORKERS} sdr-worker instance(s)"
```

```bash
chmod +x office_server/deploy/systemd/scale-workers.sh
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd office_server && pytest tests/test_deploy_files.py -v
```

Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add office_server/deploy/systemd/sdr-worker@.service office_server/deploy/systemd/scale-workers.sh office_server/tests/test_deploy_files.py
git commit -m "Add templated worker systemd unit and OFFICE_NUM_WORKERS scaling script"
```

---

### Task 8: livekit-server config template + systemd unit

**Files:**
- Create: `office_server/deploy/livekit/livekit-server.yaml.template`
- Create: `office_server/deploy/systemd/livekit-server.service`
- Modify: `office_server/tests/test_deploy_files.py`

**Interfaces:**
- Consumes: `_read`, `_parse_env_file` helpers (Task 6), `OFFICE_DOMAIN`/`LIVEKIT_API_KEY`/`LIVEKIT_API_SECRET` from `office.env.example` (Task 6).
- Produces: `office_server/deploy/livekit/livekit-server.yaml.template`, `office_server/deploy/systemd/livekit-server.service`.

- [ ] **Step 1: Write the failing tests**

Append to `office_server/tests/test_deploy_files.py`:

```python
import shutil

import yaml


def test_livekit_server_service_renders_template_and_restarts_on_failure():
    unit = _read("systemd/livekit-server.service")

    assert "EnvironmentFile=/etc/sdr-agent/office.env" in unit
    assert "Restart=on-failure" in unit
    assert "envsubst" in unit
    assert "livekit-server.yaml.template" in unit
    assert "--config /etc/livekit/livekit-server.yaml" in unit


def test_livekit_server_template_renders_to_valid_yaml_with_tls_and_keys(tmp_path):
    if shutil.which("envsubst") is None:
        import pytest

        pytest.skip("envsubst not available in this environment")

    template_path = DEPLOY_DIR / "livekit" / "livekit-server.yaml.template"
    assert template_path.exists()

    env = dict(os.environ)
    env.update(
        {
            "LIVEKIT_API_KEY": "testkey",
            "LIVEKIT_API_SECRET": "testsecret",
            "OFFICE_DOMAIN": "voice.example-office.com",
        }
    )

    result = subprocess.run(
        ["sh", "-c", f"envsubst < {template_path}"],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    rendered = yaml.safe_load(result.stdout)

    assert rendered["keys"] == {"testkey": "testsecret"}
    assert rendered["tls"]["cert_file"] == (
        "/etc/letsencrypt/live/voice.example-office.com/fullchain.pem"
    )
    assert rendered["rtc"]["tcp_port"] == 7881
    assert rendered["rtc"]["use_external_ip"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd office_server && pytest tests/test_deploy_files.py -v -k livekit_server
```

Expected: FAIL — missing files.

- [ ] **Step 3: Create `office_server/deploy/livekit/livekit-server.yaml.template`**

```yaml
port: 7880
rtc:
  tcp_port: 7881
  port_range_start: 50000
  port_range_end: 60000
  use_external_ip: true

keys:
  ${LIVEKIT_API_KEY}: ${LIVEKIT_API_SECRET}

tls:
  cert_file: /etc/letsencrypt/live/${OFFICE_DOMAIN}/fullchain.pem
  key_file: /etc/letsencrypt/live/${OFFICE_DOMAIN}/privkey.pem

logging:
  level: info
```

- [ ] **Step 4: Create `office_server/deploy/systemd/livekit-server.service`**

```ini
[Unit]
Description=Self-hosted LiveKit signaling/media server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
EnvironmentFile=/etc/sdr-agent/office.env
ExecStartPre=/bin/sh -c 'envsubst < /opt/sdr-agent/deploy/livekit/livekit-server.yaml.template > /etc/livekit/livekit-server.yaml'
ExecStart=/usr/local/bin/livekit-server --config /etc/livekit/livekit-server.yaml
Restart=on-failure
RestartSec=5
User=sdr-agent

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd office_server && pytest tests/test_deploy_files.py -v
```

Expected: 6 passed (or 5 passed + 1 skipped if `envsubst` is unavailable in the execution environment).

- [ ] **Step 6: Commit**

```bash
git add office_server/deploy/livekit/livekit-server.yaml.template office_server/deploy/systemd/livekit-server.service office_server/tests/test_deploy_files.py
git commit -m "Add livekit-server config template and systemd unit with TLS"
```

---

### Task 9: Full test suite run + final review pass

**Files:** none created — verification only.

**Interfaces:** none.

- [ ] **Step 1: Run the full test suite**

```bash
cd office_server && pytest -v
```

Expected: all tests from Tasks 1-8 pass (22 tests, or 21 passed + 1 skipped if `envsubst` unavailable).

- [ ] **Step 2: Confirm the Colab notebook was untouched**

```bash
git status sdr_voice_agent.ipynb
```

Expected: no output (notebook is git-ignored and this plan never touched it — matches spec's Non-Goal).

- [ ] **Step 3: Commit a final marker if any stray files exist**

```bash
git status
```

If clean (all prior task commits already captured everything), no action needed. Otherwise stage and commit remaining files with a descriptive message.

---

## Deferred to a human (cannot be done in this plan)

Per the design spec's Testing/Validation section, once real office-server hardware exists:

1. Run the same manual conversational UAT as the Colab prototype's Task 10 (normal discovery flow, interruption, silence handling) against this deployment.
2. Open 2-4 simultaneous test calls (the `index.html` tester at the repo root can be reused/pointed at the office server's `LIVEKIT_URL`) and confirm response latency holds up — this validates the spec's "2-4 concurrent calls on Qwen2.5-3B" capacity estimate for real.

Neither can be executed in a sandboxed dev environment (no GPU, no real domain/TLS cert, no vLLM/livekit-server binaries installed).
