import asyncio

import pytest

from src.nodes.lock_manager import LockMode


@pytest.mark.asyncio
async def test_exclusive_blocks_exclusive(cluster):
    leader = cluster.leader
    g1 = await leader.acquire("c1", "x", LockMode.EXCLUSIVE, timeout=1.0)
    assert g1 is True
    g2 = await leader.acquire("c2", "x", LockMode.EXCLUSIVE, timeout=0.3)
    assert g2 is False


@pytest.mark.asyncio
async def test_shared_locks_compatible(cluster):
    leader = cluster.leader
    g1 = await leader.acquire("c1", "y", LockMode.SHARED, timeout=1.0)
    g2 = await leader.acquire("c2", "y", LockMode.SHARED, timeout=1.0)
    assert g1 and g2


@pytest.mark.asyncio
async def test_shared_blocks_exclusive(cluster):
    leader = cluster.leader
    await leader.acquire("c1", "z", LockMode.SHARED, timeout=1.0)
    g2 = await leader.acquire("c2", "z", LockMode.EXCLUSIVE, timeout=0.3)
    assert g2 is False


@pytest.mark.asyncio
async def test_release_unblocks_waiter(cluster):
    leader = cluster.leader
    await leader.acquire("c1", "w", LockMode.EXCLUSIVE, timeout=1.0)
    await leader.release("c1", "w")
    g2 = await leader.acquire("c2", "w", LockMode.EXCLUSIVE, timeout=1.0)
    assert g2 is True
