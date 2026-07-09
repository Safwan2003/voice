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
