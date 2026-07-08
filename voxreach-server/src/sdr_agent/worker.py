from pathlib import Path

from livekit import agents
from livekit.agents import JobContext, WorkerOptions

from .config import load_config
from .session import SDRAgent, create_sdr_agent_session
from .tenants import DEFAULT_TENANT_ID, JsonTenantStore


def load_models(config):
    import torch
    from faster_whisper import WhisperModel
    from livekit.plugins import silero
    from omnivoice import OmniVoice

    # Load order matters: Whisper and OmniVoice must claim their VRAM
    # before vLLM (a separate process/service) starts, so vLLM's
    # gpu-memory-utilization budget correctly accounts for what's already
    # resident (see office-server-deployment-design.md Capacity Analysis).
    whisper_model = WhisperModel(
        config.whisper_model_size,
        device=config.whisper_device,
        compute_type=config.whisper_compute_type,
    )
    omnivoice_model = OmniVoice.from_pretrained(
        config.omnivoice_model_id,
        device_map=config.omnivoice_device,
        dtype=torch.float16,
    )
    torch.cuda.empty_cache()
    vad = silero.VAD.load()
    return whisper_model, omnivoice_model, vad


def build_entrypoint(config, whisper_model, omnivoice_model, vad, tenant_store):
    async def entrypoint(ctx: JobContext):
        await ctx.connect()
        tenant_id = (ctx.job.metadata or "").strip() or DEFAULT_TENANT_ID
        tenant = tenant_store.get_tenant(tenant_id)

        session = create_sdr_agent_session(config, whisper_model, omnivoice_model, vad)
        await session.start(agent=SDRAgent(tenant), room=ctx.room)
        await session.generate_reply(instructions=tenant.greeting_instructions)

    return entrypoint


def main() -> None:
    config = load_config()
    tenant_store = JsonTenantStore(Path(config.tenants_data_path))
    whisper_model, omnivoice_model, vad = load_models(config)
    entrypoint = build_entrypoint(config, whisper_model, omnivoice_model, vad, tenant_store)
    agents.cli.run_app(
        WorkerOptions(entrypoint_fnc=entrypoint, load_threshold=config.load_threshold)
    )


if __name__ == "__main__":
    main()
