import os
import re
import subprocess
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
