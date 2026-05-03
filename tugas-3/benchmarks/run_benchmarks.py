"""
Run in-process benchmarks and produce a performance summary.

Usage:
    python benchmarks/run_benchmarks.py
"""

import asyncio
import json
import os
import sys
import time
from statistics import mean, median

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.cluster import InProcessCluster
from src.communication.message_passing import global_bus
from src.nodes.lock_manager import LockMode

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")
os.makedirs(RESULTS_DIR, exist_ok=True)


async def bench_cache(cluster: InProcessCluster, n: int = 1000):
    print(f"\n[Cache benchmark, n={n}]")
    c1 = cluster.caches["node-1"]

    write_lats = []
    start = time.time()
    for i in range(n):
        t0 = time.time()
        await c1.put(f"k{i}", {"value": i, "data": "x" * 32})
        write_lats.append((time.time() - t0) * 1000)
    write_dur = time.time() - start

    read_lats = []
    start = time.time()
    for i in range(n):
        t0 = time.time()
        await c1.get(f"k{i}")
        read_lats.append((time.time() - t0) * 1000)
    read_dur = time.time() - start

    return {
        "n": n,
        "write_ops_per_sec": n / write_dur,
        "write_latency_ms_mean": mean(write_lats),
        "write_latency_ms_p99": sorted(write_lats)[int(0.99 * n)],
        "read_ops_per_sec": n / read_dur,
        "read_latency_ms_mean": mean(read_lats),
        "read_latency_ms_p99": sorted(read_lats)[int(0.99 * n)],
        "stats": cluster.caches["node-1"].get_stats(),
    }


async def bench_queue(cluster: InProcessCluster, n: int = 500):
    print(f"\n[Queue benchmark, n={n}]")
    q = cluster.queues["node-1"]
    enqueue_lats = []
    start = time.time()
    for i in range(n):
        t0 = time.time()
        await q.enqueue("bench", {"i": i})
        enqueue_lats.append((time.time() - t0) * 1000)
    enq_dur = time.time() - start

    deq_lats = []
    start = time.time()
    delivered = 0
    for _ in range(n):
        for nid in cluster.node_ids:
            t0 = time.time()
            m = await cluster.queues[nid].dequeue("bench")
            deq_lats.append((time.time() - t0) * 1000)
            if m:
                await cluster.queues[nid].ack(m.msg_id)
                delivered += 1
                break
    deq_dur = time.time() - start

    return {
        "n": n,
        "enqueue_ops_per_sec": n / enq_dur,
        "enqueue_p99_ms": sorted(enqueue_lats)[int(0.99 * len(enqueue_lats))]
        if enqueue_lats
        else 0,
        "dequeue_delivered": delivered,
        "dequeue_ops_per_sec": delivered / deq_dur if deq_dur > 0 else 0,
    }


async def bench_lock(cluster: InProcessCluster, n: int = 100):
    print(f"\n[Lock benchmark, n={n}]")
    await cluster.wait_for_leader(timeout=5.0)
    leader = cluster.leader
    lats = []
    successful = 0
    start = time.time()
    for i in range(n):
        t0 = time.time()
        granted = await leader.acquire(
            f"client-{i}", f"res-{i}", LockMode.EXCLUSIVE, timeout=2.0
        )
        if granted:
            successful += 1
        lats.append((time.time() - t0) * 1000)
    dur = time.time() - start

    for i in range(n):
        await leader.release(f"client-{i}", f"res-{i}")

    return {
        "n": n,
        "successful_acquires": successful,
        "acquire_ops_per_sec": n / dur,
        "acquire_latency_ms_mean": mean(lats),
        "acquire_latency_ms_p99": sorted(lats)[int(0.99 * n)],
    }


async def main():
    cluster = InProcessCluster(n=3, persistence_dir="/tmp/queue_bench")
    await cluster.start()
    try:
        await cluster.wait_for_leader(timeout=5.0)
    except TimeoutError:
        print("WARNING: no leader elected, skipping lock benchmark")

    results = {
        "started_at": time.time(),
        "cluster_size": len(cluster.node_ids),
    }

    results["cache"] = await bench_cache(cluster)
    results["queue"] = await bench_queue(cluster)
    try:
        results["lock"] = await bench_lock(cluster)
    except Exception as e:
        results["lock"] = {"error": str(e)}

    await cluster.stop()

    out = os.path.join(RESULTS_DIR, f"bench-{int(time.time())}.json")
    with open(out, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults written to {out}")
    print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
