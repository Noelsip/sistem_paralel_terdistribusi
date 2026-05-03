import asyncio

import pytest

from src.communication.message_passing import global_bus


@pytest.mark.asyncio
async def test_leader_elected(cluster):
    leader_id = await cluster.wait_for_leader(timeout=5)
    leaders = [
        nid for nid, lm in cluster.lock_managers.items() if lm.is_leader
    ]
    assert len(leaders) == 1
    assert leaders[0] == leader_id


@pytest.mark.asyncio
async def test_log_replication(cluster):
    leader = cluster.leader
    granted = await leader.acquire("c1", "r1", timeout=2.0)
    assert granted is True

    # Wait for replication to followers
    await asyncio.sleep(0.3)
    for nid, lm in cluster.lock_managers.items():
        assert lm.raft.persistent.log, f"{nid} has empty log"


@pytest.mark.asyncio
async def test_partition_majority_continues(cluster):
    leader_id = await cluster.wait_for_leader(timeout=5)
    cluster.partition([leader_id])
    await asyncio.sleep(1.0)

    # The remaining 2 nodes should elect a new leader from the majority side
    new_leaders = [
        nid for nid, lm in cluster.lock_managers.items()
        if lm.is_leader and nid != leader_id
    ]
    assert len(new_leaders) == 1
    cluster.heal()
