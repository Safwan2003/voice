#!/usr/bin/env python3
"""Generate a LiveKit room-join access token for manually testing the
office-server worker via office_server/index.html or the LiveKit Agents
Playground.

Reads LIVEKIT_API_KEY / LIVEKIT_API_SECRET from the environment — source
your env file first, e.g.:

    set -a; . office.env; set +a
    python scripts/generate-test-token.py
"""

import os
import sys
import uuid

from livekit import api

api_key = os.environ.get("LIVEKIT_API_KEY")
api_secret = os.environ.get("LIVEKIT_API_SECRET")
if not api_key or not api_secret:
    print("LIVEKIT_API_KEY and LIVEKIT_API_SECRET must be set in the environment.", file=sys.stderr)
    print("Source your env file first: set -a; . office.env; set +a", file=sys.stderr)
    sys.exit(1)

room_name = sys.argv[1] if len(sys.argv) > 1 else f"voxreach-test-{uuid.uuid4().hex[:8]}"

token = (
    api.AccessToken(api_key, api_secret)
    .with_identity("human-tester")
    .with_name("Human Tester")
    .with_grants(api.VideoGrants(room_join=True, room=room_name))
    .to_jwt()
)

print("Room name:", room_name)
print("Access token (paste into index.html):")
print(token)
