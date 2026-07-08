import asyncio
import pytest


def pytest_configure(config):
    """Ensure an event loop is available before tests run."""
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
