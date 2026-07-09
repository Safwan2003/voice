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
