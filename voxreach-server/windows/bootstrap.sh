#!/bin/bash
# Voxreach WSL2 bootstrap — installs prerequisites, clones/updates the repo,
# sets up the Python venv, and prepares office.env. Run inside WSL2/Ubuntu by
# install-and-run.bat; not meant to be run directly on a non-WSL Linux box
# (use ../start.sh directly there instead — this script exists specifically
# to keep the Windows .bat file simple rather than embedding this logic in
# a fragile single cmd.exe-quoted line).
set -e

echo "=== Voxreach WSL2 bootstrap ==="

echo "--- Installing system packages ---"
sudo apt-get update -y
sudo apt-get install -y python3 python3-pip python3-venv git curl podman

echo "--- Cloning/updating the repo ---"
if [ -d "$HOME/voice" ]; then
  (cd "$HOME/voice" && git pull)
else
  git clone https://github.com/Safwan2003/voice.git "$HOME/voice"
fi

cd "$HOME/voice/voxreach-server"

echo "--- Setting up the Python virtual environment ---"
python3 -m venv .venv
# shellcheck disable=SC1091
. .venv/bin/activate
pip install --upgrade pip
pip install -e .
pip install vllm
pip install omnivoice || pip install "git+https://github.com/k2-fsa/OmniVoice.git"

echo "--- Preparing office.env ---"
if [ ! -f office.env ]; then
  cp deploy/env/office.env.example office.env
  echo "Created office.env from the template (GPU defaults already set)."
else
  echo "office.env already exists, leaving it as-is."
fi

chmod +x start.sh

echo "=== Bootstrap complete ==="
