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
