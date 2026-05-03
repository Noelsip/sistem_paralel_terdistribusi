import asyncio

import pytest


@pytest.mark.asyncio
async def test_enqueue_dequeue_basic(cluster):
    q = cluster.queues["node-1"]
    mid = await q.enqueue("orders", {"v": 1})
    assert mid

    # Wait for replication propagation
    await asyncio.sleep(0.05)

    # Try dequeueing from any node
    for nid in cluster.node_ids:
        m = await cluster.queues[nid].dequeue("orders")
        if m and m.payload.get("v") == 1:
            await cluster.queues[nid].ack(m.msg_id)
            return
    pytest.fail("Message was never delivered")


@pytest.mark.asyncio
async def test_replication_factor(cluster):
    q = cluster.queues["node-1"]
    for i in range(10):
        await q.enqueue("rep", {"i": i})
    await asyncio.sleep(0.1)

    total_replicas = sum(
        len(cluster.queues[nid].replicas) for nid in cluster.node_ids
    )
    # 10 messages * (replication_factor - 1) replicas each
    assert total_replicas >= 10


@pytest.mark.asyncio
async def test_at_least_once_redelivery(cluster):
    q = cluster.queues["node-1"]
    q.visibility_timeout = 0.2
    mid = await q.enqueue("redeliver-test", {"v": 99}, partition_key="node-1-key")
    await asyncio.sleep(0.05)

    m = await q.dequeue("redeliver-test")
    if m is None:
        # message went to peer; pull it locally for the test
        for nid in cluster.node_ids:
            m = await cluster.queues[nid].dequeue("redeliver-test")
            if m:
                q = cluster.queues[nid]
                break
    assert m is not None
    initial_count = m.delivery_count

    # Don't ACK — wait for visibility timeout
    await asyncio.sleep(0.4)

    m2 = await q.dequeue("redeliver-test")
    assert m2 is not None
    assert m2.msg_id == m.msg_id
    assert m2.delivery_count > initial_count
    await q.ack(m2.msg_id)
