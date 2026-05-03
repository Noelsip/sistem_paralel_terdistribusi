"""
Performance benchmarks (in-process). Measures throughput and latency for
cache, queue, and lock operations under concurrent load.

Run with:
    pytest tests/performance -s
"""

import asyncio
import time

import pytest


@pytest.mark.asyncio
async def test_cache_throughput(cluster):
    c1 = cluster.caches["node-1"]
    n = 1000
    start = time.time()
    for i in range(n):
        await c1.put(f"k{i}", i)
    write_dur = time.time() - start

    start = time.time()
    for i in range(n):
        await c1.get(f"k{i}")
    read_dur = time.time() - start

    write_rps = n / write_dur
    read_rps = n / read_dur
    print(
        f"\nCache: write={write_rps:.0f} ops/s read={read_rps:.0f} ops/s"
    )
    assert read_rps > 100  # very loose lower bound


@pytest.mark.asyncio
async def test_queue_throughput(cluster):
    q = cluster.queues["node-1"]
    n = 500
    start = time.time()
    for i in range(n):
        await q.enqueue("perf", {"i": i})
    dur = time.time() - start
    rps = n / dur
    print(f"\nQueue enqueue: {rps:.0f} ops/s")
    assert rps > 50


@pytest.mark.asyncio
async def test_lock_throughput(cluster):
    leader = cluster.leader
    n = 100
    start = time.time()
    for i in range(n):
        await leader.acquire(f"client-{i}", f"resource-{i}", timeout=2.0)
    dur = time.time() - start
    rps = n / dur
    print(f"\nLock acquire: {rps:.0f} ops/s")
    assert rps > 5
