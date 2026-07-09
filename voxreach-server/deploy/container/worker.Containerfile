# Builds the sdr_agent worker (STT + TTS, GPU-resident; LLM is a hosted
# API call, no local process). Model weights (Whisper, OmniVoice) are
# NOT baked in here - HF_HOME points at a path meant to be mounted from
# the host as a volume, so an image rebuild never re-downloads them.
ARG CUDA_IMAGE=nvidia/cuda:12.4.1-runtime-ubuntu22.04
FROM ${CUDA_IMAGE} AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/sdr-agent

COPY pyproject.toml ./
COPY src ./src

RUN pip install --no-cache-dir -e . \
    && (pip install --no-cache-dir omnivoice || pip install --no-cache-dir "git+https://github.com/k2-fsa/OmniVoice.git")

ENV HF_HOME=/root/.cache/huggingface

ENTRYPOINT ["python3", "-m", "sdr_agent.worker"]
