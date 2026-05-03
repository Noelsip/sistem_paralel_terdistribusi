import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class NodeStatus(str, Enum):
    ALIVE = "alive"
    SUSPECTED = "suspected"
    DEAD = "dead"
    UNKNOWN = "unknown"


@dataclass
class NodeHealth:
    node_id: str
    status: NodeStatus = NodeStatus.UNKNOWN
    last_heartbeat: float = field(default_factory=time.time)
    missed_heartbeats: int = 0
    latency_ms: float = 0.0


class PhiAccrualFailureDetector:

    def __init__(self, phi_threshold: float = 8.0, window_size: int = 200):
        self.phi_threshold = phi_threshold
        self.window_size = window_size
        self._heartbeats: Dict[str, list] = {}
        self._last_heartbeat: Dict[str, float] = {}

    def heartbeat(self, node_id: str):
        now = time.time()
        if node_id in self._last_heartbeat:
            interval = now - self._last_heartbeat[node_id]
            if node_id not in self._heartbeats:
                self._heartbeats[node_id] = []
            self._heartbeats[node_id].append(interval)
            if len(self._heartbeats[node_id]) > self.window_size:
                self._heartbeats[node_id].pop(0)
        self._last_heartbeat[node_id] = now

    def phi(self, node_id: str) -> float:
        if node_id not in self._last_heartbeat:
            return float("inf")
        intervals = self._heartbeats.get(node_id, [])
        if not intervals:
            return 0.0
        import math
        elapsed = time.time() - self._last_heartbeat[node_id]
        mean = sum(intervals) / len(intervals)
        variance = sum((x - mean) ** 2 for x in intervals) / len(intervals)
        std = math.sqrt(max(variance, 1e-9))
        y = (elapsed - mean) / std
        # Approximate CDF using logistic regression
        phi = -math.log10(1 / (1 + math.exp(-y * 1.5976)))
        return phi

    def is_alive(self, node_id: str) -> bool:
        return self.phi(node_id) < self.phi_threshold

    def is_suspected(self, node_id: str) -> bool:
        p = self.phi(node_id)
        return self.phi_threshold <= p < self.phi_threshold * 2


class FailureDetector:
    def __init__(
        self,
        node_id: str,
        peers: List[str],
        heartbeat_interval: float = 0.5,
        timeout: float = 2.0,
        max_missed: int = 3,
    ):
        self.node_id = node_id
        self.peers = peers
        self.heartbeat_interval = heartbeat_interval
        self.timeout = timeout
        self.max_missed = max_missed

        self._health: Dict[str, NodeHealth] = {
            p: NodeHealth(node_id=p) for p in peers
        }
        self._phi_detector = PhiAccrualFailureDetector()
        self._on_failure_callbacks: List[Callable] = []
        self._on_recovery_callbacks: List[Callable] = []
        self._running = False
        self._task: Optional[asyncio.Task] = None

    def on_failure(self, callback: Callable):
        self._on_failure_callbacks.append(callback)

    def on_recovery(self, callback: Callable):
        self._on_recovery_callbacks.append(callback)

    def record_heartbeat(self, peer_id: str, latency_ms: float = 0.0):
        self._phi_detector.heartbeat(peer_id)
        if peer_id in self._health:
            prev = self._health[peer_id].status
            self._health[peer_id].last_heartbeat = time.time()
            self._health[peer_id].missed_heartbeats = 0
            self._health[peer_id].latency_ms = latency_ms
            if prev in (NodeStatus.SUSPECTED, NodeStatus.DEAD):
                self._health[peer_id].status = NodeStatus.ALIVE
                logger.info(f"Node {peer_id} recovered")
                for cb in self._on_recovery_callbacks:
                    asyncio.create_task(cb(peer_id) if asyncio.iscoroutinefunction(cb) else asyncio.coroutine(cb)(peer_id))
            else:
                self._health[peer_id].status = NodeStatus.ALIVE

    def get_status(self, peer_id: str) -> NodeStatus:
        return self._health.get(peer_id, NodeHealth(peer_id)).status

    def get_alive_nodes(self) -> List[str]:
        return [p for p in self.peers if self.get_status(p) == NodeStatus.ALIVE]

    def get_dead_nodes(self) -> List[str]:
        return [p for p in self.peers if self.get_status(p) == NodeStatus.DEAD]

    def get_all_health(self) -> Dict[str, NodeHealth]:
        return dict(self._health)

    async def _check_loop(self):
        while self._running:
            await asyncio.sleep(self.heartbeat_interval)
            now = time.time()
            for peer_id, health in self._health.items():
                elapsed = now - health.last_heartbeat
                if elapsed > self.timeout:
                    health.missed_heartbeats += 1
                    if health.missed_heartbeats >= self.max_missed:
                        if health.status != NodeStatus.DEAD:
                            health.status = NodeStatus.DEAD
                            logger.warning(f"Node {peer_id} declared DEAD")
                            for cb in self._on_failure_callbacks:
                                asyncio.create_task(
                                    cb(peer_id)
                                    if asyncio.iscoroutinefunction(cb)
                                    else asyncio.coroutine(cb)(peer_id)
                                )
                    elif health.status == NodeStatus.ALIVE:
                        health.status = NodeStatus.SUSPECTED
                        logger.warning(f"Node {peer_id} SUSPECTED")

    def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._check_loop())

    def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None
