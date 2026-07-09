import os
import shutil
import subprocess
from pathlib import Path

import yaml

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

    deploy_only_vars = {
        "OFFICE_NUM_WORKERS",
        "OFFICE_DOMAIN",
        "UI_PORT",
        "UI_ACCESS_SECRET",
    }
    expected = set(REQUIRED_ENV_VARS) | set(OPTIONAL_ENV_VARS) | deploy_only_vars

    assert expected.issubset(env_vars.keys())


def test_vllm_service_was_removed():
    # vLLM self-hosting was removed — the LLM is always a hosted API now
    # (OFFICE_LLM_PROVIDER=groq/openai/anthropic). See git history if
    # self-hosting needs to come back.
    assert not (DEPLOY_DIR / "systemd" / "vllm.service").exists()


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


def test_ui_containerfile_installs_requirements_and_runs_flask_app():
    containerfile = _read("container/ui.Containerfile")

    assert "requirements.txt" in containerfile
    assert "pip install" in containerfile
    assert "ui_server/app.py" in containerfile
    assert "EXPOSE" in containerfile
