#!/usr/bin/env python3
"""Generate a LiveKit room-join access token for manually testing the
voxreach-server worker via ui/index.html or the LiveKit Agents Playground.

Reads LIVEKIT_API_KEY / LIVEKIT_API_SECRET from the environment — source
your env file first, e.g.:

    set -a; . office.env; set +a
    python scripts/generate-test-token.py

Pass --raw to print only the bare token (no labels) — useful for scripting or
building custom test links.
"""

import argparse
import os
import sys
import uuid

from livekit import api

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("room_name", nargs="?", help="Room name (default: random)")
parser.add_argument(
    "--raw", action="store_true", help="Print only the token, no labels — for scripting"
)
args = parser.parse_args()

api_key = os.environ.get("LIVEKIT_API_KEY")
api_secret = os.environ.get("LIVEKIT_API_SECRET")
if not api_key or not api_secret:
    print("LIVEKIT_API_KEY and LIVEKIT_API_SECRET must be set in the environment.", file=sys.stderr)
    print("Source your env file first: set -a; . office.env; set +a", file=sys.stderr)
    sys.exit(1)

room_name = args.room_name or f"voxreach-test-{uuid.uuid4().hex[:8]}"

token = (
    api.AccessToken(api_key, api_secret)
    .with_identity("human-tester")
    .with_name("Human Tester")
    .with_grants(api.VideoGrants(room_join=True, room=room_name))
    .to_jwt()
)

if args.raw:
    print(token)
else:
    print("Room name:", room_name)
    print("Access token (paste into ui/index.html):")
    print(token)
