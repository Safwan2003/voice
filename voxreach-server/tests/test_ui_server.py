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
