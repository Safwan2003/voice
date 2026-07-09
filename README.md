# Voxreach

AI voice agent platform — an outbound SDR voice pipeline (speech-to-text,
LLM, text-to-speech over LiveKit's real-time transport).

Two tracks in this repo:

- **Colab prototype** (`colab/`) — the validated proof of concept, runs on
  Google Colab's free GPU. See
  `docs/superpowers/plans/2026-07-06-sdr-voice-agent-colab.md`.
- **Office server deployment** (`voxreach-server/`) — the production
  package, meant for a self-hosted server with a GPU. See
  [`voxreach-server/README.md`](voxreach-server/README.md) for how to run
  it (`./deploy/container/run-local.sh` gives you a one-command local
  test via Podman), and `docs/superpowers/specs/` for the design docs.

Each track has its own browser-based LiveKit connection tester
(`colab/index.html`, `voxreach-server/ui/index.html`) for manually trying
that pipeline.
