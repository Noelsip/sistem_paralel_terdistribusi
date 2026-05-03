import asyncio
import sys
import os

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.cluster import InProcessCluster
from src.communication.message_passing import global_bus


@pytest_asyncio.fixture
async def cluster(tmp_path):
    # Reset global bus state between tests
    global_bus._channels.clear()
    global_bus._handlers.clear()
    global_bus._partitions.clear()

    c = InProcessCluster(n=3, persistence_dir=str(tmp_path / "queues"))
    await c.start()
    try:
        await c.wait_for_leader(timeout=5.0)
    except TimeoutError:
        pass
    yield c
    await c.stop()
