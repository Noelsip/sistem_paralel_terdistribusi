import asyncio
import logging
import tempfile

from src.cluster import InProcessCluster
from src.nodes.lock_manager import LockMode

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
)
logger = logging.getLogger("demo")


async def demo_raft_election(cluster: InProcessCluster):
    print("\n" + "=" * 60)
    print("DEMO 1 — Raft Leader Election")
    print("=" * 60)
    leader_id = await cluster.wait_for_leader(timeout=10)
    print(f"Leader elected: {leader_id}")
    for nid, lm in cluster.lock_managers.items():
        info = lm.raft.get_state_info()
        print(f"  {nid}: state={info['state']} term={info['term']}")


async def demo_locks(cluster: InProcessCluster):
    print("\n" + "=" * 60)
    print("DEMO 2 — Distributed Locks")
    print("=" * 60)
    leader = cluster.leader

    granted_x = await leader.acquire("client-A", "resource-1", LockMode.EXCLUSIVE)
    print(f"Client-A EXCLUSIVE on resource-1: granted={granted_x}")

    granted_y = await leader.acquire(
        "client-B", "resource-1", LockMode.EXCLUSIVE, timeout=0.5
    )
    print(f"Client-B EXCLUSIVE on resource-1 (should fail): granted={granted_y}")

    await leader.release("client-A", "resource-1")
    print("Client-A released resource-1")

    g1 = await leader.acquire("client-C", "resource-2", LockMode.SHARED)
    g2 = await leader.acquire("client-D", "resource-2", LockMode.SHARED)
    print(f"Client-C SHARED + Client-D SHARED on resource-2: {g1=} {g2=}")


async def demo_queue(cluster: InProcessCluster):
    print("\n" + "=" * 60)
    print("DEMO 3 — Distributed Queue (Consistent Hashing)")
    print("=" * 60)
    q1 = cluster.queues["node-1"]

    msg_ids = []
    for i in range(5):
        mid = await q1.enqueue("orders", {"order_id": i, "amount": i * 10})
        msg_ids.append(mid)
    print(f"Enqueued 5 messages, IDs: {[m[:8] for m in msg_ids]}")

    for nid in cluster.node_ids:
        stats = cluster.queues[nid].get_stats()
        print(
            f"  {nid}: queues={stats['queues']} "
            f"replicas={stats['replicas']} enqueued={stats['enqueued']}"
        )

    # Dequeue from each node
    delivered = 0
    for nid, qn in cluster.queues.items():
        m = await qn.dequeue("orders")
        if m:
            delivered += 1
            print(f"  {nid} delivered msg {m.msg_id[:8]} payload={m.payload}")
            await qn.ack(m.msg_id)
    print(f"Total delivered & acked: {delivered}")


async def demo_cache(cluster: InProcessCluster):
    print("\n" + "=" * 60)
    print("DEMO 4 — Cache Coherence (MESI)")
    print("=" * 60)
    c1 = cluster.caches["node-1"]
    c2 = cluster.caches["node-2"]
    c3 = cluster.caches["node-3"]

    await c1.put("user:42", {"name": "Alice"})
    print(f"node-1 PUT user:42")

    v2 = await c2.get("user:42")
    print(f"node-2 GET user:42 -> {v2}")
    v3 = await c3.get("user:42")
    print(f"node-3 GET user:42 -> {v3}")

    await c1.put("user:42", {"name": "Alice (updated)"})
    print(f"node-1 PUT user:42 (update) — should invalidate node-2/3")

    await asyncio.sleep(0.05)
    s2 = c2.get_stats()
    s3 = c3.get_stats()
    print(f"  node-2 cache states: {s2['states']} hits={s2['hits']}")
    print(f"  node-3 cache states: {s3['states']} hits={s3['hits']}")

    v2_after = await c2.get("user:42")
    print(f"node-2 GET user:42 after invalidate -> {v2_after}")


async def demo_partition(cluster: InProcessCluster):
    print("\n" + "=" * 60)
    print("DEMO 5 — Network Partition Handling")
    print("=" * 60)
    leader = cluster.leader
    minority = leader.node_id
    cluster.partition([minority])
    print(f"Partitioned {minority} from rest of cluster")
    await asyncio.sleep(1.0)

    new_leader_id = None
    for nid, lm in cluster.lock_managers.items():
        if nid != minority and lm.is_leader:
            new_leader_id = nid
            break
    print(f"New leader after partition: {new_leader_id}")

    cluster.heal()
    print("Partition healed")
    await asyncio.sleep(0.5)


async def main():
    cluster = InProcessCluster(n=3, persistence_dir=tempfile.mkdtemp(prefix="distsync-demo-"))
    await cluster.start()
    try:
        await demo_raft_election(cluster)
        await demo_locks(cluster)
        await demo_queue(cluster)
        await demo_cache(cluster)
        await demo_partition(cluster)

        print("\n" + "=" * 60)
        print("DEMO COMPLETE — All features demonstrated")
        print("=" * 60)
    finally:
        await cluster.stop()


if __name__ == "__main__":
    asyncio.run(main())
