"""
Distributed Lock Manager built on Raft Consensus.

Features:
- Shared (read) and Exclusive (write) locks
- Lock acquisition coordinated via Raft replicated log
- Deadlock detection using wait-for-graph (WFG) cycle detection
- Network partition handling — only Raft leader's majority side can grant locks
- Lock leases with timeout to prevent permanent deadlock from crashed clients
"""

import asyncio
import logging
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from src.communication.message_passing import MessageBus, global_bus
from src.consensus.raft import RaftNode
from src.nodes.base_node import BaseNode

logger = logging.getLogger(__name__)


class LockMode(str, Enum):
    SHARED = "shared"
    EXCLUSIVE = "exclusive"


@dataclass
class LockHolder:
    client_id: str
    mode: LockMode
    acquired_at: float
    lease_until: float


@dataclass
class LockState:
    resource: str
    holders: Dict[str, LockHolder] = field(default_factory=dict)
    waiters: deque = field(default_factory=deque)

    @property
    def is_held(self) -> bool:
        return len(self.holders) > 0

    @property
    def mode(self) -> Optional[LockMode]:
        if not self.holders:
            return None
        # If any exclusive, mode is exclusive
        for h in self.holders.values():
            if h.mode == LockMode.EXCLUSIVE:
                return LockMode.EXCLUSIVE
        return LockMode.SHARED


@dataclass
class LockRequest:
    request_id: str
    client_id: str
    resource: str
    mode: LockMode
    timestamp: float = field(default_factory=time.time)


class DeadlockDetector:
    """
    Detects deadlocks via wait-for-graph (WFG) cycle detection.
    A cycle in WFG = deadlock. Victim selection: youngest transaction.
    """

    def __init__(self):
        # client -> set of clients it is waiting for
        self.wait_for: Dict[str, Set[str]] = defaultdict(set)
        # client -> request timestamp
        self.client_age: Dict[str, float] = {}

    def add_wait(self, waiter: str, holder: str):
        if waiter == holder:
            return
        self.wait_for[waiter].add(holder)

    def remove_client(self, client: str):
        self.wait_for.pop(client, None)
        self.client_age.pop(client, None)
        for w in list(self.wait_for.keys()):
            self.wait_for[w].discard(client)
            if not self.wait_for[w]:
                self.wait_for.pop(w, None)

    def set_client_age(self, client: str, ts: float):
        if client not in self.client_age:
            self.client_age[client] = ts

    def detect_cycle(self) -> Optional[List[str]]:
        """Return one cycle (list of clients) or None."""
        WHITE, GRAY, BLACK = 0, 1, 2
        color: Dict[str, int] = defaultdict(lambda: WHITE)
        parent: Dict[str, Optional[str]] = {}

        def dfs(u: str) -> Optional[List[str]]:
            color[u] = GRAY
            for v in self.wait_for.get(u, set()):
                if color[v] == GRAY:
                    # Found cycle, reconstruct
                    cycle = [v]
                    cur = u
                    while cur != v and cur is not None:
                        cycle.append(cur)
                        cur = parent.get(cur)
                    cycle.append(v)
                    return list(reversed(cycle))
                if color[v] == WHITE:
                    parent[v] = u
                    res = dfs(v)
                    if res:
                        return res
            color[u] = BLACK
            return None

        for node in list(self.wait_for.keys()):
            if color[node] == WHITE:
                cycle = dfs(node)
                if cycle:
                    return cycle
        return None

    def select_victim(self, cycle: List[str]) -> str:
        """Pick the youngest transaction in the cycle as victim."""
        return max(cycle, key=lambda c: self.client_age.get(c, 0.0))


class LockManagerNode(BaseNode):
    def __init__(
        self,
        node_id: str,
        peers: List[str],
        bus: Optional[MessageBus] = None,
        default_lease: float = 30.0,
    ):
        super().__init__(node_id, peers, bus)
        self.default_lease = default_lease
        self.locks: Dict[str, LockState] = {}
        self.client_locks: Dict[str, Set[str]] = defaultdict(set)
        self.deadlock_detector = DeadlockDetector()
        self.raft = RaftNode(
            node_id=node_id,
            peers=peers,
            bus=self.bus,
            apply_callback=self._apply_command,
        )

    async def _on_start(self):
        await self.raft.start()
        self._tasks.append(asyncio.create_task(self._lease_expiry_loop()))
        self._tasks.append(asyncio.create_task(self._deadlock_detection_loop()))

    async def _on_stop(self):
        await self.raft.stop()

    @property
    def is_leader(self) -> bool:
        return self.raft.is_leader

    async def _apply_command(self, command: Dict[str, Any]) -> Any:
        op = command.get("op")
        if op == "acquire":
            return self._do_acquire(
                command["client_id"],
                command["resource"],
                LockMode(command["mode"]),
                command.get("lease", self.default_lease),
            )
        elif op == "release":
            return self._do_release(command["client_id"], command["resource"])
        elif op == "release_all":
            return self._do_release_all(command["client_id"])
        elif op == "abort":
            return self._do_release_all(command["client_id"])
        return None

    def _do_acquire(
        self, client_id: str, resource: str, mode: LockMode, lease: float
    ) -> bool:
        state = self.locks.setdefault(resource, LockState(resource=resource))
        self.deadlock_detector.set_client_age(client_id, time.time())

        if not state.is_held:
            state.holders[client_id] = LockHolder(
                client_id=client_id,
                mode=mode,
                acquired_at=time.time(),
                lease_until=time.time() + lease,
            )
            self.client_locks[client_id].add(resource)
            return True

        # Already held
        if mode == LockMode.SHARED and state.mode == LockMode.SHARED:
            state.holders[client_id] = LockHolder(
                client_id=client_id,
                mode=mode,
                acquired_at=time.time(),
                lease_until=time.time() + lease,
            )
            self.client_locks[client_id].add(resource)
            return True

        # Lock conflict — record wait-for edges
        for holder_id in state.holders:
            if holder_id != client_id:
                self.deadlock_detector.add_wait(client_id, holder_id)
        if not any(w.client_id == client_id for w in state.waiters):
            state.waiters.append(
                LockRequest(
                    request_id=str(uuid.uuid4()),
                    client_id=client_id,
                    resource=resource,
                    mode=mode,
                )
            )
        return False

    def _do_release(self, client_id: str, resource: str) -> bool:
        state = self.locks.get(resource)
        if not state:
            return False
        if client_id not in state.holders:
            return False
        del state.holders[client_id]
        self.client_locks[client_id].discard(resource)
        if not state.is_held:
            self.deadlock_detector.remove_client(client_id)
        # Promote waiters
        self._promote_waiters(state)
        return True

    def _do_release_all(self, client_id: str) -> int:
        count = 0
        for resource in list(self.client_locks.get(client_id, set())):
            if self._do_release(client_id, resource):
                count += 1
        self.deadlock_detector.remove_client(client_id)
        return count

    def _promote_waiters(self, state: LockState):
        while state.waiters:
            req = state.waiters[0]
            if not state.is_held:
                state.holders[req.client_id] = LockHolder(
                    client_id=req.client_id,
                    mode=req.mode,
                    acquired_at=time.time(),
                    lease_until=time.time() + self.default_lease,
                )
                self.client_locks[req.client_id].add(state.resource)
                state.waiters.popleft()
            elif (
                req.mode == LockMode.SHARED and state.mode == LockMode.SHARED
            ):
                state.holders[req.client_id] = LockHolder(
                    client_id=req.client_id,
                    mode=req.mode,
                    acquired_at=time.time(),
                    lease_until=time.time() + self.default_lease,
                )
                self.client_locks[req.client_id].add(state.resource)
                state.waiters.popleft()
            else:
                break

    async def acquire(
        self,
        client_id: str,
        resource: str,
        mode: LockMode = LockMode.EXCLUSIVE,
        timeout: float = 10.0,
        lease: Optional[float] = None,
    ) -> bool:
        """Client API: acquire lock. Blocks until granted or timeout."""
        if not self.is_leader:
            return False
        deadline = time.time() + timeout
        lease = lease if lease is not None else self.default_lease
        while time.time() < deadline:
            granted = await self.raft.submit(
                {
                    "op": "acquire",
                    "client_id": client_id,
                    "resource": resource,
                    "mode": mode.value,
                    "lease": lease,
                },
                timeout=2.0,
            )
            if granted:
                return True
            await asyncio.sleep(0.05)
        return False

    async def release(self, client_id: str, resource: str) -> bool:
        if not self.is_leader:
            return False
        result = await self.raft.submit(
            {"op": "release", "client_id": client_id, "resource": resource}
        )
        return bool(result)

    async def release_all(self, client_id: str) -> int:
        if not self.is_leader:
            return 0
        result = await self.raft.submit(
            {"op": "release_all", "client_id": client_id}
        )
        return result or 0

    async def _lease_expiry_loop(self):
        while self._running:
            await asyncio.sleep(1.0)
            if not self.is_leader:
                continue
            now = time.time()
            for resource, state in list(self.locks.items()):
                expired = [
                    h.client_id
                    for h in state.holders.values()
                    if h.lease_until < now
                ]
                for client_id in expired:
                    logger.warning(
                        f"Lease expired: client={client_id} resource={resource}"
                    )
                    await self.raft.submit(
                        {
                            "op": "release",
                            "client_id": client_id,
                            "resource": resource,
                        }
                    )

    async def _deadlock_detection_loop(self):
        while self._running:
            await asyncio.sleep(2.0)
            if not self.is_leader:
                continue
            cycle = self.deadlock_detector.detect_cycle()
            if cycle:
                victim = self.deadlock_detector.select_victim(cycle)
                logger.warning(
                    f"Deadlock detected: cycle={cycle} victim={victim}"
                )
                await self.raft.submit({"op": "abort", "client_id": victim})

    def get_lock_table(self) -> Dict[str, Any]:
        return {
            resource: {
                "mode": state.mode.value if state.mode else None,
                "holders": [
                    {
                        "client_id": h.client_id,
                        "mode": h.mode.value,
                        "acquired_at": h.acquired_at,
                        "lease_until": h.lease_until,
                    }
                    for h in state.holders.values()
                ],
                "waiters": [
                    {"client_id": w.client_id, "mode": w.mode.value}
                    for w in state.waiters
                ],
            }
            for resource, state in self.locks.items()
        }
