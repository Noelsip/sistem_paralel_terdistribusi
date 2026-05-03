import asyncio

import pytest

from src.nodes.cache_node import MESIState


@pytest.mark.asyncio
async def test_put_get_local(cluster):
    c1 = cluster.caches["node-1"]
    await c1.put("foo", "bar")
    v = await c1.get("foo")
    assert v == "bar"


@pytest.mark.asyncio
async def test_get_propagates_from_peer(cluster):
    c1 = cluster.caches["node-1"]
    c2 = cluster.caches["node-2"]
    await c1.put("shared-key", "value-1")
    await asyncio.sleep(0.05)

    v = await c2.get("shared-key")
    assert v == "value-1"

    # After remote read both nodes should be SHARED
    line1 = c1.cache.get("shared-key")
    line2 = c2.cache.get("shared-key")
    assert line1 is not None and line2 is not None
    assert line1.state == MESIState.SHARED
    assert line2.state == MESIState.SHARED


@pytest.mark.asyncio
async def test_write_invalidates_other_caches(cluster):
    c1 = cluster.caches["node-1"]
    c2 = cluster.caches["node-2"]
    await c1.put("k", "v1")
    await c2.get("k")
    await asyncio.sleep(0.05)

    await c1.put("k", "v2")
    await asyncio.sleep(0.1)

    # node-2's copy should be invalidated (popped from cache)
    line2 = c2.cache.get("k")
    assert line2 is None or line2.state == MESIState.INVALID
