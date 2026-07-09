# Builds the UI + token-issuing service. Deliberately lightweight: no
# CUDA, no torch, no faster-whisper/omnivoice - this is a separate
# Python environment from the worker (see ui_server/requirements.txt),
# so the worker image never gains Flask and this image never gains the
# worker's multi-GB ML dependency stack.
FROM python:3.12-slim

WORKDIR /opt/voxreach-ui

COPY ui_server/requirements.txt ./ui_server/requirements.txt
RUN pip install --no-cache-dir -r ui_server/requirements.txt

COPY ui_server ./ui_server
COPY ui ./ui

ENV UI_PORT=8080
EXPOSE 8080

ENTRYPOINT ["python3", "ui_server/app.py"]
