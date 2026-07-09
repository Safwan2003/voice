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
        "LIVEKIT_TURN_HOST",
        "LIVEKIT_TURN_USERNAME",
        "LIVEKIT_TURN_CREDENTIAL",
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


def test_livekit_server_template_renders_to_valid_yaml_with_turn_relay_and_keys(tmp_path):
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
            "LIVEKIT_TURN_HOST": "turn.example-office.com",
            "LIVEKIT_TURN_USERNAME": "turnuser",
            "LIVEKIT_TURN_CREDENTIAL": "turnpass",
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
    # No self-hosted TLS - Cloudflare Tunnel terminates TLS at the edge for
    # the WS signaling hostname, so livekit-server never holds its own cert.
    assert "tls" not in rendered
    assert rendered["rtc"]["tcp_port"] == 7881
    # No reachable public IP behind the tunnel-only office network - media
    # relays through the external TURN server instead of advertising a
    # useless direct candidate.
    assert rendered["rtc"]["use_external_ip"] is False
    turn_server = rendered["rtc"]["turn_servers"][0]
    assert turn_server["host"] == "turn.example-office.com"
    assert turn_server["protocol"] == "tls"
    assert turn_server["username"] == "turnuser"
    assert turn_server["credential"] == "turnpass"


def test_coturn_config_has_static_credential_and_tls():
    conf = _read("turn/turnserver.conf.example")

    assert "lt-cred-mech" in conf
    assert "tls-listening-port=5349" in conf
    assert "user=" in conf
    assert "cert=" in conf and "pkey=" in conf


def test_deploy_office_script_has_valid_shell_syntax_and_checks_placeholders():
    script = DEPLOY_DIR / "systemd" / "deploy-office.sh"
    assert script.exists()

    result = subprocess.run(["sh", "-n", str(script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr

    content = script.read_text()
    # Must refuse to deploy with unfilled office.env placeholders rather
    # than silently starting services with broken/missing credentials.
    assert "CHANGE_ME" in content
    assert "LIVEKIT_TURN_HOST" in content
    assert "scale-workers.sh" in content


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
