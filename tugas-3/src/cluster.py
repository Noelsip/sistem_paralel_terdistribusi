"""
In-process multi-node cluster runner.
Useful for local demos, integration tests, and benchmarks without Docker.
Spawns N nodes sharing the global MessageBus inside one event loop.
"""

import asyncio
import logging
from typing import Dict, List

from src.communication.message_passing import global_bus
from src.nodes.cache_node import CacheNode
from src.nodes.lock_manager import LockManagerNode
from src.nodes.queue_node import QueueNode

logger = logging.getLogger(__name__)


class InProcessCluster:
    def __init__(self, n: int = 3, persistence_dir: str = "/tmp/queue_data_demo"):
        self.node_ids: List[str] = [f"node-{i+1}" for i in range(n)]
        self.lock_managers: Dict[str, LockManagerNode] = {}
        self.queues: Dict[str, QueueNode] = {}
        self.caches: Dict[str, CacheNode] = {}
        self.persistence_dir = persistence_dir

        for nid in self.node_ids:
            peers = [p for p in self.node_ids if p != nid]
            self.lock_managers[nid] = LockManagerNode(nid, peers, bus=global_bus)
            self.queues[nid] = QueueNode(
                nid, peers, bus=global_bus, persistence_dir=persistence_dir
            )
            self.caches[nid] = CacheNode(nid, peers, bus=global_bus)

    async def start(self):
        for nid in self.node_ids:
            await self.lock_managers[nid].start()
            await self.queues[nid].start()
            await self.caches[nid].start()
        logger.info(f"Cluster started: {self.node_ids}")

    async def stop(self):
        for nid in self.node_ids:
            await self.lock_managers[nid].stop()
            await self.queues[nid].stop()
            await self.caches[nid].stop()

    async def wait_for_leader(self, timeout: float = 5.0) -> str:
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            for nid, lm in self.lock_managers.items():
                if lm.is_leader:
                    return nid
            await asyncio.sleep(0.05)
        raise TimeoutError("No leader elected within timeout")

    @property
    def leader(self) -> LockManagerNode:
        for lm in self.lock_managers.values():
            if lm.is_leader:
                return lm
        raise RuntimeError("No leader available")

    def partition(self, node_ids: List[str]):
        global_bus.partition_nodes(node_ids)

    def heal(self):
        global_bus.heal_partition()
