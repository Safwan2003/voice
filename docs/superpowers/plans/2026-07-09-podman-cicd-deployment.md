# Podman Containerization + CI/CD Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Containerize the `sdr_agent` worker and a new UI+token-issuing service with Podman, wire them into systemd via Quadlets, add a GitHub Actions pipeline that tests every push and builds+publishes images on merge to `main`, and replace `start.sh` with a Podman-based local runner — per `docs/superpowers/specs/2026-07-09-podman-cicd-deployment-design.md`.

**Architecture:** Two new container images (`worker`, `ui`) built from Containerfiles under `voxreach-server/deploy/container/`. The UI image runs a small Flask app (`voxreach-server/ui_server/app.py`) serving the existing `ui/index.html` plus a `POST /api/token` route gated by a shared secret. Both images are wired into systemd via Podman Quadlets (`.container` files) replacing/adding to `voxreach-server/deploy/systemd/`. `start.sh` is deleted; `deploy/container/run-local.sh` replaces it, running the same images locally via `podman run` with GPU auto-detection. `livekit-server` is untouched. GitHub Actions (`.github/workflows/ci.yml`) runs the existing pytest suite on every push/PR and builds+pushes both images to GHCR on merge to `main`; the final "deploy to the real box" step stays a documented manual command since the office-server hardware doesn't exist yet.

**Tech Stack:** Podman (Quadlets, `podman build`/`run`), Flask (UI/token service — kept out of the worker's dependency tree via a separate `ui_server/requirements.txt`), `livekit-api` (lightweight token-generation package, already installed transitively today), GitHub Actions (`docker/build-push-action` works with Podman-built OCI images), pytest (existing suite + new tests).

## Global Constraints

- **`docs/superpowers/specs/2026-07-09-podman-cicd-deployment-design.md` is the source of truth** — every task below implements a specific section of it; deviate only if a task's steps say why.
- Model weights (Whisper, OmniVoice) are never baked into the worker image — always mounted from a host/volume path (`HF_HOME`/Hugging Face cache convention) so an image rebuild never re-downloads multi-GB weights.
- The UI/token service is a separate Python environment from the worker (`ui_server/requirements.txt`, not `voxreach-server/pyproject.toml`) — it must never pull Flask or `livekit-api` into the GPU worker's image, and the worker must never pull Flask into its image.
- No real user accounts/login — the token endpoint's only protection is a single shared secret (`UI_ACCESS_SECRET`), read from the same `office.env`/`EnvironmentFile` every other component already uses.
- No Kubernetes, no blue/green deploys, no linter — explicitly out of scope per the spec's Non-Goals.
- Container images are tagged and pushed to GHCR as `ghcr.io/safwan2003/voice/sdr-worker` and `ghcr.io/safwan2003/voice/sdr-ui`, both `:latest` and `:<git-sha>`.
- The actual "pull new image + restart on the real office box" step is **not automated** in this plan — it's a documented manual runbook (no hardware exists yet to automate against).
- Existing `sdr_agent` package behavior (config.py, session.py, worker.py, stt.py, tts.py) is untouched by this plan — only how it's packaged and deployed changes.
- Follow the existing test convention in `voxreach-server/tests/test_deploy_files.py`: config/unit/workflow files too infrastructure-heavy to execute in CI are tested via text/YAML content assertions, not by actually running them.

---

## File Structure

```
voxreach-server/
  deploy/
    container/
      worker.Containerfile      # NEW
      ui.Containerfile          # NEW
      run-local.sh              # NEW — replaces start.sh
    systemd/
      sdr-worker@.container     # NEW (Quadlet) — replaces sdr-worker@.service
      sdr-worker@.service       # DELETED
      voxreach-ui.container     # NEW (Quadlet)
    env/
      office.env.example        # MODIFIED — add UI_PORT, UI_ACCESS_SECRET
  ui_server/
    app.py                      # NEW — Flask app: GET / + POST /api/token
    requirements.txt            # NEW — flask + livekit-api only
  ui/
    index.html                  # MODIFIED — add secret input + Get Token button + JS
  office.env                    # MODIFIED — add UI_PORT, UI_ACCESS_SECRET
  start.sh                      # DELETED
  README.md                     # MODIFIED — reflect containers/Quadlets/run-local.sh
  tests/
    test_ui_server.py           # NEW
    test_ui_html.py             # NEW
    test_deploy_files.py        # MODIFIED — add Containerfile/Quadlet/workflow tests
.github/
  workflows/
    ci.yml                      # NEW — test + build jobs
```

---

### Task 1: Worker Containerfile

**Files:**
- Create: `voxreach-server/deploy/container/worker.Containerfile`
- Modify: `voxreach-server/tests/test_deploy_files.py`

**Interfaces:**
- Consumes: `voxreach-server/pyproject.toml`, `voxreach-server/src/sdr_agent/` (existing package — unchanged).
- Produces: a buildable Containerfile at the path above; later tasks (CI, Quadlet, run-local.sh) reference this exact path and its `ENTRYPOINT`.

- [ ] **Step 1: Write the failing test**

Add to `voxreach-server/tests/test_deploy_files.py` (new top-level function, append to end of file):

```python
def test_worker_containerfile_builds_from_cuda_and_does_not_bake_weights():
    containerfile = _read("container/worker.Containerfile")

    assert "FROM" in containerfile and "cuda" in containerfile.lower()
    assert "pip install" in containerfile
    assert "ENTRYPOINT" in containerfile
    assert "sdr_agent.worker" in containerfile
    # Model weights must never be COPY'd into the image — they're
    # mounted from the host at runtime (see HF_HOME below).
    assert "COPY" not in containerfile.split("ENTRYPOINT")[0].replace(
        "COPY pyproject.toml", ""
    ).replace("COPY src", "")
    assert "HF_HOME" in containerfile
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd voxreach-server && pytest tests/test_deploy_files.py::test_worker_containerfile_builds_from_cuda_and_does_not_bake_weights -v`
Expected: FAIL — `AssertionError: missing deploy file: container/worker.Containerfile`

- [ ] **Step 3: Create `voxreach-server/deploy/container/worker.Containerfile`**

```dockerfile
# Builds the sdr_agent worker (STT + TTS, GPU-resident; LLM is a hosted
# API call, no local process). Model weights (Whisper, OmniVoice) are
# NOT baked in here - HF_HOME points at a path meant to be mounted from
# the host as a volume, so an image rebuild never re-downloads them.
ARG CUDA_IMAGE=nvidia/cuda:12.4.1-runtime-ubuntu22.04
FROM ${CUDA_IMAGE} AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/sdr-agent

COPY pyproject.toml ./
COPY src ./src

RUN pip install --no-cache-dir -e . \
    && (pip install --no-cache-dir omnivoice || pip install --no-cache-dir "git+https://github.com/k2-fsa/OmniVoice.git")

ENV HF_HOME=/root/.cache/huggingface

ENTRYPOINT ["python3", "-m", "sdr_agent.worker"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd voxreach-server && pytest tests/test_deploy_files.py::test_worker_containerfile_builds_from_cuda_and_does_not_bake_weights -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add voxreach-server/deploy/container/worker.Containerfile voxreach-server/tests/test_deploy_files.py
git commit -m "Add worker Containerfile (CUDA runtime, weights mounted not baked in)"
```

---

### Task 2: UI/token Flask app

**Files:**
- Create: `voxreach-server/ui_server/app.py`
- Create: `voxreach-server/ui_server/requirements.txt`
- Test: `voxreach-server/tests/test_ui_server.py`

**Interfaces:**
- Consumes: `voxreach-server/ui/index.html` (served as static content, unchanged file itself — Task 3 edits it), environment variables `UI_ACCESS_SECRET`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, `LIVEKIT_URL`, `UI_PORT`.
- Produces: `ui_server.app.create_app() -> flask.Flask` — a factory function (not a module-level `app` global) so tests can construct fresh instances with different env vars per test.

- [ ] **Step 1: Write the failing tests**

Create `voxreach-server/tests/test_ui_server.py`:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ui_server"))

import pytest
from app import create_app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("UI_ACCESS_SECRET", "test-secret")
    monkeypatch.setenv("LIVEKIT_API_KEY", "test-key")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "test-api-secret")
    monkeypatch.setenv("LIVEKIT_URL", "ws://localhost:7880")
    app = create_app()
    app.testing = True
    return app.test_client()


def test_index_serves_ui_html(client):
    response = client.get("/")

    assert response.status_code == 200
    assert b"<!doctype html>" in response.data.lower()


def test_token_endpoint_rejects_missing_secret(client):
    response = client.post("/api/token", json={})

    assert response.status_code == 401


def test_token_endpoint_rejects_wrong_secret(client):
    response = client.post("/api/token", json={"secret": "wrong"})

    assert response.status_code == 401


def test_token_endpoint_issues_token_for_correct_secret(client):
    response = client.post("/api/token", json={"secret": "test-secret"})

    assert response.status_code == 200
    data = response.get_json()
    assert data["url"] == "ws://localhost:7880"
    assert data["token"]
    assert data["room"].startswith("voxreach-")


def test_token_endpoint_500s_when_secret_not_configured_on_server(client, monkeypatch):
    monkeypatch.delenv("UI_ACCESS_SECRET", raising=False)

    response = client.post("/api/token", json={"secret": "anything"})

    assert response.status_code == 500
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd voxreach-server && pip install flask livekit-api && pytest tests/test_ui_server.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app'` (the `ui_server/app.py` module doesn't exist yet)

- [ ] **Step 3: Write `voxreach-server/ui_server/requirements.txt`**

```
flask>=3.0
livekit-api>=1.0
```

- [ ] **Step 4: Write `voxreach-server/ui_server/app.py`**

```python
"""Minimal token-issuing web app for the Voxreach browser tester.

Serves ui/index.html at GET / and issues fresh LiveKit room-join tokens
at POST /api/token, gated by a shared secret (UI_ACCESS_SECRET) so the
endpoint isn't usable by anyone who simply finds the URL. Kept out of
the sdr_agent package on purpose: this runs in a separate, much lighter
container (deploy/container/ui.Containerfile) that never needs the
worker's CUDA/torch/faster-whisper dependencies.
"""

import os
import uuid
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from livekit import api

UI_DIR = Path(__file__).resolve().parent.parent / "ui"


def create_app() -> Flask:
    app = Flask(__name__, static_folder=None)

    @app.get("/")
    def index():
        return send_from_directory(UI_DIR, "index.html")

    @app.post("/api/token")
    def issue_token():
        expected_secret = os.environ.get("UI_ACCESS_SECRET")
        if not expected_secret:
            return jsonify(error="UI_ACCESS_SECRET is not configured on the server"), 500

        payload = request.get_json(silent=True) or {}
        if payload.get("secret") != expected_secret:
            return jsonify(error="Invalid secret"), 401

        api_key = os.environ.get("LIVEKIT_API_KEY")
        api_secret = os.environ.get("LIVEKIT_API_SECRET")
        livekit_url = os.environ.get("LIVEKIT_URL")
        if not api_key or not api_secret or not livekit_url:
            return jsonify(error="Server is missing LIVEKIT_URL/API_KEY/API_SECRET"), 500

        room_name = f"voxreach-{uuid.uuid4().hex[:8]}"
        token = (
            api.AccessToken(api_key, api_secret)
            .with_identity("human-tester")
            .with_name("Human Tester")
            .with_grants(api.VideoGrants(room_join=True, room=room_name))
            .to_jwt()
        )
        return jsonify(room=room_name, token=token, url=livekit_url)

    return app


if __name__ == "__main__":
    port = int(os.environ.get("UI_PORT", "8080"))
    create_app().run(host="0.0.0.0", port=port)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd voxreach-server && pytest tests/test_ui_server.py -v`
Expected: 5 passed

- [ ] **Step 6: Commit**

```bash
git add voxreach-server/ui_server voxreach-server/tests/test_ui_server.py
git commit -m "Add UI/token Flask app (GET / + POST /api/token, shared-secret gated)"
```

---

### Task 3: Wire the browser UI to the token endpoint

**Files:**
- Modify: `voxreach-server/ui/index.html`
- Test: `voxreach-server/tests/test_ui_html.py`

**Interfaces:**
- Consumes: `POST /api/token` (Task 2) — request body `{"secret": str}`, response `{"room": str, "token": str, "url": str}` on success or `{"error": str}` with 401/500 on failure.
- Produces: nothing new consumed by later tasks — this is a leaf change (existing `getConnSettings()`/`saveConnSettings()`/`connUrl`/`connToken` elements are reused, not renamed).

- [ ] **Step 1: Write the failing tests**

Create `voxreach-server/tests/test_ui_html.py`:

```python
from pathlib import Path

UI_HTML = Path(__file__).resolve().parent.parent / "ui" / "index.html"


def test_ui_has_secret_input_and_get_token_button():
    html = UI_HTML.read_text()

    assert 'id="uiSecret"' in html
    assert "requestToken()" in html


def test_ui_request_token_function_calls_token_endpoint():
    html = UI_HTML.read_text()

    assert "async function requestToken()" in html
    assert "fetch('/api/token'" in html
    assert "document.getElementById('connUrl').value = data.url" in html
    assert "document.getElementById('connToken').value = data.token" in html
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd voxreach-server && pytest tests/test_ui_html.py -v`
Expected: FAIL — both assertions fail, `id="uiSecret"` and `requestToken()` don't exist yet

- [ ] **Step 3: Add the secret input + button to the connection bar**

In `voxreach-server/ui/index.html`, find this block (currently around line 329-333):

```html
      <div class="conn-bar">
        <input id="connUrl" placeholder="Server URL (ws://localhost:7880 for local dev, wss://your-domain for production)" style="flex:1;min-width:220px">
        <input id="connToken" placeholder="Access token (run scripts/generate-test-token.py)" style="flex:2;min-width:280px">
        <button class="bt bt-gh bt-sm" onclick="saveConnSettings()"><i class="fas fa-floppy-disk"></i> Save</button>
      </div>
```

Replace it with:

```html
      <div class="conn-bar">
        <input id="connUrl" placeholder="Server URL (ws://localhost:7880 for local dev, wss://your-domain for production)" style="flex:1;min-width:220px">
        <input id="connToken" placeholder="Access token (or use Get Token below)" style="flex:2;min-width:280px">
        <input id="uiSecret" type="password" placeholder="Shared secret" style="flex:1;min-width:140px">
        <button class="bt bt-am bt-sm" onclick="requestToken()"><i class="fas fa-key"></i> Get Token</button>
        <button class="bt bt-gh bt-sm" onclick="saveConnSettings()"><i class="fas fa-floppy-disk"></i> Save</button>
      </div>
```

- [ ] **Step 4: Add the `requestToken()` function**

In `voxreach-server/ui/index.html`, find `function saveConnSettings(){` (currently around line 497) and insert a new function immediately **before** it:

```html
async function requestToken(){
  const secret = document.getElementById('uiSecret').value.trim();
  if(!secret){toast('Enter the shared secret first','err');return}
  try{
    const res = await fetch('/api/token', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({secret}),
    });
    const data = await res.json();
    if(!res.ok){toast(data.error || 'Failed to get token','err');return}
    document.getElementById('connUrl').value = data.url;
    document.getElementById('connToken').value = data.token;
    saveConnSettings();
    toast('Token acquired — ready to call','ok');
  }catch(e){
    toast('Could not reach token endpoint: ' + e.message, 'err');
  }
}
function saveConnSettings(){
```

(The last line above is the existing line — this step only inserts the new function directly above it, `saveConnSettings` itself is unchanged.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd voxreach-server && pytest tests/test_ui_html.py -v`
Expected: 2 passed

- [ ] **Step 6: Commit**

```bash
git add voxreach-server/ui/index.html voxreach-server/tests/test_ui_html.py
git commit -m "Wire browser UI to self-service token endpoint (shared secret, no manual script)"
```

---

### Task 4: UI Containerfile

**Files:**
- Create: `voxreach-server/deploy/container/ui.Containerfile`
- Modify: `voxreach-server/tests/test_deploy_files.py`

**Interfaces:**
- Consumes: `voxreach-server/ui_server/` (Task 2), `voxreach-server/ui/index.html` (Task 3).
- Produces: a buildable Containerfile; later tasks (CI, Quadlet, run-local.sh) reference this exact path.

- [ ] **Step 1: Write the failing test**

Append to `voxreach-server/tests/test_deploy_files.py`:

```python
def test_ui_containerfile_installs_requirements_and_runs_flask_app():
    containerfile = _read("container/ui.Containerfile")

    assert "requirements.txt" in containerfile
    assert "pip install" in containerfile
    assert "ui_server/app.py" in containerfile
    assert "EXPOSE" in containerfile
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd voxreach-server && pytest tests/test_deploy_files.py::test_ui_containerfile_installs_requirements_and_runs_flask_app -v`
Expected: FAIL — `AssertionError: missing deploy file: container/ui.Containerfile`

- [ ] **Step 3: Create `voxreach-server/deploy/container/ui.Containerfile`**

```dockerfile
# Builds the UI + token-issuing service. Deliberately lightweight: no
# CUDA, no torch, no faster-whisper/omnivoice - this is a separate
# Python environment from the worker (see ui_server/requirements.txt),
# so the worker image never gains Flask and this image never gains the
# worker's multi-GB ML dependency stack.
FROM python:3.12-slim

WORKDIR /opt/voxreach-ui

COPY ui_server/requirements.txt ./ui_server/requirements.txt
RUN pip install --no-cache-dir -r ui_server/requirements.txt

COPY ui_server ./ui_server
COPY ui ./ui

ENV UI_PORT=8080
EXPOSE 8080

ENTRYPOINT ["python3", "ui_server/app.py"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd voxreach-server && pytest tests/test_deploy_files.py::test_ui_containerfile_installs_requirements_and_runs_flask_app -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add voxreach-server/deploy/container/ui.Containerfile voxreach-server/tests/test_deploy_files.py
git commit -m "Add UI Containerfile (lightweight, separate from worker's ML deps)"
```

---

### Task 5: Podman Quadlets for worker and UI

**Files:**
- Create: `voxreach-server/deploy/systemd/sdr-worker@.container`
- Create: `voxreach-server/deploy/systemd/voxreach-ui.container`
- Delete: `voxreach-server/deploy/systemd/sdr-worker@.service`
- Modify: `voxreach-server/tests/test_deploy_files.py`

**Interfaces:**
- Consumes: `ghcr.io/safwan2003/voice/sdr-worker:latest` and `ghcr.io/safwan2003/voice/sdr-ui:latest` (image names Task 7's CI job publishes to — must match exactly).
- Produces: nothing consumed by later tasks in this plan; these are the actual production deploy units.

- [ ] **Step 1: Write the failing tests**

In `voxreach-server/tests/test_deploy_files.py`, replace the existing `test_sdr_worker_service_reads_env_file_and_restarts_on_failure` function (it currently reads `systemd/sdr-worker@.service`, which this task deletes) with:

```python
def test_sdr_worker_quadlet_pulls_image_mounts_hf_cache_and_restarts():
    unit = _read("systemd/sdr-worker@.container")

    assert "Image=ghcr.io/safwan2003/voice/sdr-worker:latest" in unit
    assert "EnvironmentFile=/etc/sdr-agent/office.env" in unit
    assert "AddDevice=nvidia.com/gpu=all" in unit
    assert "Volume=" in unit and "huggingface" in unit
    assert "Restart=on-failure" in unit


def test_ui_quadlet_publishes_port_and_restarts():
    unit = _read("systemd/voxreach-ui.container")

    assert "Image=ghcr.io/safwan2003/voice/sdr-ui:latest" in unit
    assert "EnvironmentFile=/etc/sdr-agent/office.env" in unit
    assert "PublishPort=" in unit
    assert "Restart=on-failure" in unit


def test_worker_service_file_was_removed():
    # Replaced by the Quadlet above - the worker is now a container, not
    # a bare `python -m sdr_agent.worker` process.
    assert not (DEPLOY_DIR / "systemd" / "sdr-worker@.service").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd voxreach-server && pytest tests/test_deploy_files.py -v -k "quadlet or worker_service_file"`
Expected: FAIL — missing `.container` files; the "removed" test also fails since the old `.service` file still exists

- [ ] **Step 3: Delete the old worker service unit**

```bash
git rm voxreach-server/deploy/systemd/sdr-worker@.service
```

- [ ] **Step 4: Create `voxreach-server/deploy/systemd/sdr-worker@.container`**

```ini
[Unit]
Description=SDR voice agent worker (%i)
After=network-online.target
Wants=network-online.target

[Container]
Image=ghcr.io/safwan2003/voice/sdr-worker:latest
EnvironmentFile=/etc/sdr-agent/office.env
Volume=/opt/sdr-agent/hf-cache:/root/.cache/huggingface:Z
AddDevice=nvidia.com/gpu=all

[Service]
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 5: Create `voxreach-server/deploy/systemd/voxreach-ui.container`**

```ini
[Unit]
Description=Voxreach browser tester + token endpoint
After=network-online.target
Wants=network-online.target

[Container]
Image=ghcr.io/safwan2003/voice/sdr-ui:latest
EnvironmentFile=/etc/sdr-agent/office.env
PublishPort=8080:8080

[Service]
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd voxreach-server && pytest tests/test_deploy_files.py -v`
Expected: all pass (existing tests + the new/replaced ones above)

- [ ] **Step 7: Commit**

```bash
git add voxreach-server/deploy/systemd/sdr-worker@.container voxreach-server/deploy/systemd/voxreach-ui.container voxreach-server/tests/test_deploy_files.py
git commit -m "Replace worker systemd unit with a Podman Quadlet; add UI Quadlet"
```

---

### Task 6: `UI_PORT` / `UI_ACCESS_SECRET` env vars

**Files:**
- Modify: `voxreach-server/deploy/env/office.env.example`
- Modify: `voxreach-server/office.env`
- Modify: `voxreach-server/tests/test_deploy_files.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `UI_PORT`, `UI_ACCESS_SECRET` — read by `ui_server/app.py` (Task 2, already reads `os.environ.get("UI_ACCESS_SECRET")` / `UI_PORT`) and by `run-local.sh` (Task 8).

- [ ] **Step 1: Write the failing test**

In `voxreach-server/tests/test_deploy_files.py`, update `test_office_env_example_covers_all_config_vars`'s `deploy_only_vars` set:

```python
def test_office_env_example_covers_all_config_vars():
    from sdr_agent.config import OPTIONAL_ENV_VARS, REQUIRED_ENV_VARS

    env_vars = _parse_env_file(_read("env/office.env.example"))

    deploy_only_vars = {
        "OFFICE_NUM_WORKERS",
        "OFFICE_DOMAIN",
        "UI_PORT",
        "UI_ACCESS_SECRET",
    }
    expected = set(REQUIRED_ENV_VARS) | set(OPTIONAL_ENV_VARS) | deploy_only_vars

    assert expected.issubset(env_vars.keys())
```

(This replaces the existing `deploy_only_vars` line in that test — same function, just the one set literal changes.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd voxreach-server && pytest tests/test_deploy_files.py::test_office_env_example_covers_all_config_vars -v`
Expected: FAIL — `UI_PORT`/`UI_ACCESS_SECRET` not present in `office.env.example`

- [ ] **Step 3: Add the vars to `voxreach-server/deploy/env/office.env.example`**

Find the `OFFICE_NUM_WORKERS`/`OFFICE_LOAD_THRESHOLD` block and add directly after it:

```bash
# UI + self-service token endpoint (deploy/container/ui.Containerfile).
# UI_ACCESS_SECRET gates POST /api/token - anyone who knows this secret
# can get a working LiveKit connection token, so treat it like a
# password. run-local.sh auto-generates one if left as CHANGE_ME.
UI_PORT=8080
UI_ACCESS_SECRET=CHANGE_ME
```

- [ ] **Step 4: Add the same vars to `voxreach-server/office.env`**

Add the same two lines (with a real, non-placeholder `UI_ACCESS_SECRET` value of your choosing) to the local `office.env` file, in the same location relative to `OFFICE_NUM_WORKERS`.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd voxreach-server && pytest tests/test_deploy_files.py::test_office_env_example_covers_all_config_vars -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add voxreach-server/deploy/env/office.env.example voxreach-server/tests/test_deploy_files.py
git commit -m "Add UI_PORT and UI_ACCESS_SECRET env vars"
```

(`voxreach-server/office.env` is gitignored — nothing to commit there, just edit it locally.)

---

### Task 7: GitHub Actions CI (test + build)

**Files:**
- Create: `.github/workflows/ci.yml`
- Test: `voxreach-server/tests/test_ci_workflow.py`

**Interfaces:**
- Consumes: Containerfiles from Tasks 1 and 4.
- Produces: `ghcr.io/safwan2003/voice/sdr-worker:latest`/`:<sha>` and `ghcr.io/safwan2003/voice/sdr-ui:latest`/`:<sha>` — the exact image references Task 5's Quadlets already hardcode.

- [ ] **Step 1: Write the failing tests**

Create `voxreach-server/tests/test_ci_workflow.py`:

```python
from pathlib import Path

import yaml

WORKFLOW_PATH = (
    Path(__file__).resolve().parent.parent.parent / ".github" / "workflows" / "ci.yml"
)


def _load_workflow():
    assert WORKFLOW_PATH.exists(), f"missing workflow file: {WORKFLOW_PATH}"
    return yaml.safe_load(WORKFLOW_PATH.read_text())


def test_ci_workflow_has_test_and_build_jobs():
    workflow = _load_workflow()

    assert "test" in workflow["jobs"]
    assert "build" in workflow["jobs"]


def test_build_job_depends_on_test_and_only_runs_on_main_push():
    workflow = _load_workflow()
    build = workflow["jobs"]["build"]

    assert build["needs"] == "test"
    assert "refs/heads/main" in build["if"]


def test_build_job_publishes_both_images_to_ghcr():
    workflow = _load_workflow()
    build_yaml = yaml.dump(workflow["jobs"]["build"])

    assert "ghcr.io/safwan2003/voice/sdr-worker" in build_yaml
    assert "ghcr.io/safwan2003/voice/sdr-ui" in build_yaml
    assert "worker.Containerfile" in build_yaml
    assert "ui.Containerfile" in build_yaml
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd voxreach-server && pytest tests/test_ci_workflow.py -v`
Expected: FAIL — `AssertionError: missing workflow file`

- [ ] **Step 3: Create `.github/workflows/ci.yml`**

```yaml
name: CI

on:
  push:
    branches: ["**"]
  pull_request:
    branches: ["**"]

jobs:
  test:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: voxreach-server
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -e ".[dev]"
      - run: pytest tests/ -v

  build:
    needs: test
    if: github.ref == 'refs/heads/main' && github.event_name == 'push'
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
    steps:
      - uses: actions/checkout@v4
      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - uses: docker/build-push-action@v6
        with:
          context: voxreach-server
          file: voxreach-server/deploy/container/worker.Containerfile
          push: true
          tags: |
            ghcr.io/safwan2003/voice/sdr-worker:latest
            ghcr.io/safwan2003/voice/sdr-worker:${{ github.sha }}
      - uses: docker/build-push-action@v6
        with:
          context: voxreach-server
          file: voxreach-server/deploy/container/ui.Containerfile
          push: true
          tags: |
            ghcr.io/safwan2003/voice/sdr-ui:latest
            ghcr.io/safwan2003/voice/sdr-ui:${{ github.sha }}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd voxreach-server && pytest tests/test_ci_workflow.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/ci.yml voxreach-server/tests/test_ci_workflow.py
git commit -m "Add CI: test on every push/PR, build+push both images to GHCR on main"
```

---

### Task 8: `run-local.sh` (replaces `start.sh`)

**Files:**
- Create: `voxreach-server/deploy/container/run-local.sh`
- Delete: `voxreach-server/start.sh`
- Test: `voxreach-server/tests/test_deploy_files.py`

**Interfaces:**
- Consumes: images built by Tasks 1 and 4 (built locally by this script when `SKIP_BUILD` isn't set), `office.env` (Task 6's new vars included).
- Produces: nothing consumed by later tasks — this is a leaf, local-dev-only script.

- [ ] **Step 1: Write the failing test**

Append to `voxreach-server/tests/test_deploy_files.py`:

```python
def test_run_local_script_has_valid_shell_syntax():
    script = DEPLOY_DIR / "container" / "run-local.sh"
    assert script.exists()

    result = subprocess.run(["sh", "-n", str(script)], capture_output=True, text=True)

    assert result.returncode == 0, result.stderr


def test_start_sh_was_removed():
    # Replaced by run-local.sh - once the worker/UI are containers,
    # "run it locally" and "run it in production" are the same
    # mechanism, so the old native-process script is redundant.
    repo_root = DEPLOY_DIR.parent
    assert not (repo_root / "start.sh").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd voxreach-server && pytest tests/test_deploy_files.py -v -k "run_local or start_sh"`
Expected: FAIL — `run-local.sh` doesn't exist; `start.sh` still exists

- [ ] **Step 3: Delete `start.sh`**

```bash
git rm voxreach-server/start.sh
```

- [ ] **Step 4: Create `voxreach-server/deploy/container/run-local.sh`**

```sh
#!/bin/sh
set -eu

# Local dev runner - replaces start.sh. Runs the same container images
# used in production via `podman run` instead of native processes, so
# "test locally" and "run in production" are the same mechanism.
#
# GPU is auto-detected: if `nvidia-smi` is available, the worker
# container gets GPU passthrough and runs real STT/TTS. If not, the
# worker still runs, but in CPU mode (WHISPER_DEVICE=cpu) - correctness
# testing only, far too slow for a real conversation. This does not
# grant GPU access that doesn't exist; it automates the same
# CPU-fallback option that already existed via WHISPER_DEVICE=cpu.
#
# Usage: ./deploy/container/run-local.sh [path-to-env-file]
# Default env file: ./office.env (copy deploy/env/office.env.example first).
# Set SKIP_BUILD=1 to reuse already-built local images instead of rebuilding.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PUBLIC_HOST="${PUBLIC_HOST:-localhost}"

ENV_FILE="${1:-$REPO_ROOT/office.env}"
if [ ! -f "$ENV_FILE" ]; then
  echo "Env file not found: $ENV_FILE" >&2
  echo "Copy deploy/env/office.env.example to $ENV_FILE, fill in real values, and re-run." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

: "${LIVEKIT_API_KEY:?LIVEKIT_API_KEY must be set in $ENV_FILE}"
: "${LIVEKIT_API_SECRET:?LIVEKIT_API_SECRET must be set in $ENV_FILE}"
: "${UI_ACCESS_SECRET:?UI_ACCESS_SECRET must be set in $ENV_FILE}"

UI_PORT="${UI_PORT:-8080}"
LIVEKIT_CONTAINER_NAME="voxreach-livekit-server"
UI_CONTAINER_NAME="voxreach-ui"
WORKER_CONTAINER_NAME="voxreach-worker"

if [ "$LIVEKIT_API_KEY" = "CHANGE_ME" ] || [ "$LIVEKIT_API_SECRET" = "CHANGE_ME" ]; then
  echo "LIVEKIT_API_KEY/LIVEKIT_API_SECRET are still CHANGE_ME — generating a real pair..." >&2
  if command -v livekit-server >/dev/null 2>&1; then
    KEYGEN_OUTPUT="$(livekit-server generate-keys)"
  else
    KEYGEN_OUTPUT="$(podman run --rm docker.io/livekit/livekit-server:latest generate-keys)"
  fi
  NEW_KEY="$(echo "$KEYGEN_OUTPUT" | awk -F': *' '/API Key:/{print $2}')"
  NEW_SECRET="$(echo "$KEYGEN_OUTPUT" | awk -F': *' '/API Secret:/{print $2}')"
  sed -i "s/^LIVEKIT_API_KEY=.*/LIVEKIT_API_KEY=${NEW_KEY}/" "$ENV_FILE"
  sed -i "s/^LIVEKIT_API_SECRET=.*/LIVEKIT_API_SECRET=${NEW_SECRET}/" "$ENV_FILE"
  LIVEKIT_API_KEY="$NEW_KEY"
  LIVEKIT_API_SECRET="$NEW_SECRET"
  echo "Generated and saved a new key/secret pair to $ENV_FILE."
fi

if [ "$UI_ACCESS_SECRET" = "CHANGE_ME" ]; then
  NEW_UI_SECRET="$(head -c16 /dev/urandom | od -An -tx1 | tr -d ' \n')"
  sed -i "s/^UI_ACCESS_SECRET=.*/UI_ACCESS_SECRET=${NEW_UI_SECRET}/" "$ENV_FILE"
  UI_ACCESS_SECRET="$NEW_UI_SECRET"
  echo "Generated and saved a new UI_ACCESS_SECRET to $ENV_FILE: $NEW_UI_SECRET"
fi

cleanup() {
  echo "Stopping services..."
  podman stop "$LIVEKIT_CONTAINER_NAME" "$UI_CONTAINER_NAME" "$WORKER_CONTAINER_NAME" >/dev/null 2>&1 || true
  podman rm "$LIVEKIT_CONTAINER_NAME" "$UI_CONTAINER_NAME" "$WORKER_CONTAINER_NAME" >/dev/null 2>&1 || true
}
trap cleanup INT TERM EXIT

echo "[1/3] Building images (set SKIP_BUILD=1 to reuse existing ones)..."
if [ "${SKIP_BUILD:-0}" != "1" ]; then
  podman build -t voxreach-worker:local -f "$SCRIPT_DIR/worker.Containerfile" "$REPO_ROOT"
  podman build -t voxreach-ui:local -f "$SCRIPT_DIR/ui.Containerfile" "$REPO_ROOT"
fi

echo "[2/3] Starting livekit-server, UI, and worker..."
podman rm -f "$LIVEKIT_CONTAINER_NAME" "$UI_CONTAINER_NAME" "$WORKER_CONTAINER_NAME" >/dev/null 2>&1 || true

podman run -d --name "$LIVEKIT_CONTAINER_NAME" --network host \
  --env LIVEKIT_KEYS="${LIVEKIT_API_KEY}: ${LIVEKIT_API_SECRET}" \
  docker.io/livekit/livekit-server:latest --bind 0.0.0.0 >/dev/null

podman run -d --name "$UI_CONTAINER_NAME" --network host \
  --env-file "$ENV_FILE" \
  voxreach-ui:local >/dev/null

mkdir -p "$REPO_ROOT/.hf-cache"
if command -v nvidia-smi >/dev/null 2>&1; then
  echo "GPU detected — running worker with GPU passthrough."
  podman run -d --name "$WORKER_CONTAINER_NAME" --network host \
    --device nvidia.com/gpu=all \
    --env-file "$ENV_FILE" \
    --env LIVEKIT_URL="ws://localhost:7880" \
    -v "$REPO_ROOT/.hf-cache:/root/.cache/huggingface" \
    voxreach-worker:local >/dev/null
else
  echo "No GPU detected — running worker in CPU mode (WHISPER_DEVICE=cpu)." >&2
  echo "STT/TTS will be too slow for a real call, but the code path is testable." >&2
  podman run -d --name "$WORKER_CONTAINER_NAME" --network host \
    --env-file "$ENV_FILE" \
    --env LIVEKIT_URL="ws://localhost:7880" \
    --env WHISPER_DEVICE=cpu \
    -v "$REPO_ROOT/.hf-cache:/root/.cache/huggingface" \
    voxreach-worker:local >/dev/null
fi

sleep 2
echo ""
echo "[3/3] Ready."
echo "  UI:  http://${PUBLIC_HOST}:${UI_PORT}"
echo "  Enter the shared secret (UI_ACCESS_SECRET in $ENV_FILE) and click 'Get Token' to connect."
echo "Press Ctrl+C to stop everything."
podman wait "$LIVEKIT_CONTAINER_NAME" "$UI_CONTAINER_NAME" "$WORKER_CONTAINER_NAME"
```

```bash
chmod +x voxreach-server/deploy/container/run-local.sh
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd voxreach-server && pytest tests/test_deploy_files.py -v -k "run_local or start_sh"`
Expected: 2 passed

- [ ] **Step 6: Commit**

```bash
git add voxreach-server/deploy/container/run-local.sh voxreach-server/tests/test_deploy_files.py
git commit -m "Replace start.sh with Podman-based run-local.sh (GPU auto-detected)"
```

---

### Task 9: README updates

**Files:**
- Modify: `voxreach-server/README.md`

**Interfaces:** none — documentation only.

- [ ] **Step 1: Update the "Run it locally" section**

Replace every reference to `./start.sh` with `./deploy/container/run-local.sh`, and replace the `pip install -e .` / `pip install omnivoice` local-install instructions with a note that `run-local.sh` builds the images itself (no local Python environment setup needed beyond Podman).

- [ ] **Step 2: Update the "Deploy to production" section**

Add the two new Quadlet units to the `sudo cp deploy/systemd/*.service /etc/systemd/system/` step — Quadlets install differently (they go in `/etc/containers/systemd/` or `~/.config/containers/systemd/`, not `/etc/systemd/system/`, and are picked up by `podman-system-generator` on the next `systemctl daemon-reload`). Document:

```bash
sudo mkdir -p /etc/containers/systemd
sudo cp deploy/systemd/sdr-worker@.container deploy/systemd/voxreach-ui.container /etc/containers/systemd/
sudo cp deploy/systemd/livekit-server.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now livekit-server.service
sudo systemctl enable --now voxreach-ui.service
./deploy/systemd/scale-workers.sh /etc/sdr-agent/office.env
```

(Quadlet-generated unit names drop the `.container` extension — `sdr-worker@.container` becomes the runtime unit `sdr-worker@N.service`, `voxreach-ui.container` becomes `voxreach-ui.service` — `scale-workers.sh` needs no changes since it already just calls `systemctl enable --now sdr-worker@${i}.service`.)

- [ ] **Step 3: Add the manual image-update runbook**

```markdown
## Updating a running deployment

CI builds and pushes new images automatically on every merge to `main`.
Getting a new image running on the office server is currently a manual
step (no hardware exists yet to automate this against):

\`\`\`bash
podman pull ghcr.io/safwan2003/voice/sdr-worker:latest
podman pull ghcr.io/safwan2003/voice/sdr-ui:latest
sudo systemctl restart sdr-worker@1.service   # repeat per worker instance
sudo systemctl restart voxreach-ui.service
\`\`\`
```

- [ ] **Step 4: Update the `.env` keys table**

Add two rows:

```markdown
| `UI_PORT` | optional (default `8080`) | Port the UI/token service listens on |
| `UI_ACCESS_SECRET` | required for the UI service | Shared secret gating `POST /api/token` — treat like a password |
```

- [ ] **Step 5: Commit**

```bash
git add voxreach-server/README.md
git commit -m "Update README for Podman/Quadlet deployment and run-local.sh"
```

---

### Task 10: Full test suite run + final review

**Files:** none created — verification only.

**Interfaces:** none.

- [ ] **Step 1: Run the full test suite**

```bash
cd voxreach-server && pytest tests/ -v
```

Expected: all tests pass — the pre-existing 29 plus the new ones from Tasks 2, 3, 4, 5, 6, 7, 8 (roughly 20 new tests).

- [ ] **Step 2: Confirm no stray references to `start.sh` or the old `sdr-worker@.service` remain**

```bash
grep -rn "start\.sh" voxreach-server/ --include="*.md" --include="*.sh" --include="*.py" --include="*.yml"
grep -rln "sdr-worker@\.service" voxreach-server/
```

Expected: no output from either command (the first `grep` may legitimately match historical spec docs under `docs/superpowers/specs/` — those are out of scope, don't edit them).

- [ ] **Step 3: Confirm `git status` is clean**

```bash
git status
```

If clean (all prior task commits already captured everything), no action needed. Otherwise stage and commit remaining files with a descriptive message.

---

## Deferred to a human (cannot be done in this plan)

Per the design spec's Testing/Validation section, once real office-server
hardware exists:

1. Verify GPU passthrough actually works: `podman run --rm --device
   nvidia.com/gpu=all nvidia/cuda:12.4.1-runtime-ubuntu22.04 nvidia-smi`
   before trusting the worker Quadlet with real calls.
2. Confirm the CUDA base image version (`ARG CUDA_IMAGE` in
   `worker.Containerfile`) actually matches the box's installed NVIDIA
   driver — adjust the build arg if not.
3. Run the same manual conversational UAT this project has used at every
   prior deployment stage (normal discovery flow, interruption, silence
   handling) against the containerized worker specifically, to confirm
   containerizing it didn't change runtime behavior.
4. Wire up the deferred "automate the deploy step" follow-up (self-hosted
   GitHub Actions runner on the box, triggered on a successful `build`)
   once there's a real box to run it on.

None of these can be executed in a sandboxed dev environment (no GPU, no
real office-server hardware, no Podman/NVIDIA Container Toolkit installed
here).
