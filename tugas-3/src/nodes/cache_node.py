"""
Distributed Cache with MESI Coherence Protocol.

MESI states:
- M (Modified): Cache line is dirty, only this node has the latest value.
                Memory/other replicas are stale. On eviction must write back.
- E (Exclusive): Only this node has the line, value matches "memory" (origin).
                  Can transition to M without bus traffic.
- S (Shared):    Multiple nodes may hold this line, all read-only and clean.
- I (Invalid):   Cache line is not valid here. Read miss.

Bus transactions modeled:
- BusRd  (read miss):           ask peers, transition based on responses.
- BusRdX (write/upgrade):       invalidate all other copies.
- Invalidate:                   pure invalidation broadcast.

Eviction: LRU (default) or LFU.
"""

import asyncio
import logging
import time
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from src.communication.message_passing import (
    Message,
    MessageType,
    MessageBus,
    global_bus,
)
from src.nodes.base_node import BaseNode
from src.utils.metrics import registry

logger = logging.getLogger(__name__)


class MESIState(str, Enum):
    MODIFIED = "M"
    EXCLUSIVE = "E"
    SHARED = "S"
    INVALID = "I"


@dataclass
class CacheLine:
    key: str
    value: Any
    state: MESIState = MESIState.INVALID
    version: int = 0
    last_access: float = field(default_factory=time.time)
    access_count: int = 0


class EvictionPolicy:
    def access(self, key: str):
        raise NotImplementedError

    def insert(self, key: str):
        raise NotImplementedError

    def remove(self, key: str):
        raise NotImplementedError

    def evict(self) -> Optional[str]:
        raise NotImplementedError


class LRUPolicy(EvictionPolicy):
    def __init__(self):
        self._od: OrderedDict = OrderedDict()

    def access(self, key: str):
        if key in self._od:
            self._od.move_to_end(key)

    def insert(self, key: str):
        self._od[key] = None
        self._od.move_to_end(key)

    def remove(self, key: str):
        self._od.pop(key, None)

    def evict(self) -> Optional[str]:
        if not self._od:
            return None
        key, _ = self._od.popitem(last=False)
        return key


class LFUPolicy(EvictionPolicy):
    def __init__(self):
        self._counts: Dict[str, int] = defaultdict(int)

    def access(self, key: str):
        self._counts[key] = self._counts.get(key, 0) + 1

    def insert(self, key: str):
        self._counts.setdefault(key, 1)

    def remove(self, key: str):
        self._counts.pop(key, None)

    def evict(self) -> Optional[str]:
        if not self._counts:
            return None
        key = min(self._counts.items(), key=lambda kv: kv[1])[0]
        self._counts.pop(key, None)
        return key


class CacheNode(BaseNode):
    def __init__(
        self,
        node_id: str,
        peers: List[str],
        bus: Optional[MessageBus] = None,
        max_size: int = 1000,
        eviction_policy: str = "LRU",
    ):
        super().__init__(node_id, peers, bus)
        self.max_size = max_size
        self.cache: Dict[str, CacheLine] = {}
        self.policy: EvictionPolicy = (
            LFUPolicy() if eviction_policy.upper() == "LFU" else LRUPolicy()
        )

        # Pending bus reads waiting for responses
        self._pending_reads: Dict[str, asyncio.Future] = {}

        # Metrics
        self.m_hits = registry.counter(f"cache_{node_id}_hits", "cache hits")
        self.m_misses = registry.counter(f"cache_{node_id}_misses", "cache misses")
        self.m_invalidations = registry.counter(
            f"cache_{node_id}_invalidations", "cache invalidations sent"
        )
        self.m_evictions = registry.counter(
            f"cache_{node_id}_evictions", "cache evictions"
        )
        self.m_writebacks = registry.counter(
            f"cache_{node_id}_writebacks", "cache writebacks"
        )
        self.m_latency = registry.histogram(
            f"cache_{node_id}_latency", "cache op latency seconds"
        )
        self.m_size = registry.gauge(f"cache_{node_id}_size", "cache size")

    async def _on_start(self):
        self.bus.register_handler(
            self.node_id, MessageType.CACHE_FETCH, self._handle_fetch
        )
        self.bus.register_handler(
            self.node_id, MessageType.CACHE_INVALIDATE, self._handle_invalidate
        )
        self.bus.register_handler(
            self.node_id, MessageType.CACHE_RESPONSE, self._handle_response
        )
        self.bus.register_handler(
            self.node_id,
            MessageType.CACHE_STATE_CHANGE,
            self._handle_state_change,
        )
        self._tasks.append(asyncio.create_task(self.bus.dispatch_messages(self.node_id)))

    async def _on_stop(self):
        pass

    def _ensure_capacity(self):
        while len(self.cache) >= self.max_size:
            victim_key = self.policy.evict()
            if victim_key is None:
                break
            line = self.cache.pop(victim_key, None)
            self.m_evictions.inc()
            if line and line.state == MESIState.MODIFIED:
                # Writeback (logged; in a real system would persist)
                self.m_writebacks.inc()
                logger.debug(
                    f"[{self.node_id}] WB key={victim_key} v={line.version}"
                )
            self.m_size.set(len(self.cache))

    async def get(self, key: str) -> Optional[Any]:
        start = time.time()
        line = self.cache.get(key)
        if line and line.state != MESIState.INVALID:
            line.last_access = time.time()
            line.access_count += 1
            self.policy.access(key)
            self.m_hits.inc()
            self.m_latency.observe(time.time() - start)
            return line.value

        # Miss — issue BusRd to peers
        self.m_misses.inc()
        value = await self._bus_read(key)
        # If still nothing, read from "memory" (origin) — here we just return None
        if value is not None:
            self._ensure_capacity()
            new_state = (
                MESIState.SHARED if value.get("shared") else MESIState.EXCLUSIVE
            )
            self.cache[key] = CacheLine(
                key=key,
                value=value["value"],
                state=new_state,
                version=value["version"],
            )
            self.policy.insert(key)
            self.m_size.set(len(self.cache))
            self.m_latency.observe(time.time() - start)
            return value["value"]
        self.m_latency.observe(time.time() - start)
        return None

    async def put(self, key: str, value: Any) -> bool:
        start = time.time()
        line = self.cache.get(key)

        # Issue BusRdX — invalidate all other copies
        await self._broadcast_invalidate(key)

        if line is None:
            self._ensure_capacity()
            line = CacheLine(key=key, value=value, state=MESIState.MODIFIED, version=1)
            self.cache[key] = line
            self.policy.insert(key)
        else:
            line.value = value
            line.state = MESIState.MODIFIED
            line.version += 1
            line.last_access = time.time()
            self.policy.access(key)

        self.m_size.set(len(self.cache))
        self.m_latency.observe(time.time() - start)
        return True

    async def delete(self, key: str) -> bool:
        await self._broadcast_invalidate(key)
        line = self.cache.pop(key, None)
        self.policy.remove(key)
        self.m_size.set(len(self.cache))
        return line is not None

    async def _broadcast_invalidate(self, key: str):
        for peer in self.peers:
            msg = Message.create(
                msg_type=MessageType.CACHE_INVALIDATE,
                sender_id=self.node_id,
                receiver_id=peer,
                payload={"key": key},
            )
            await self.bus.send(msg)
            self.m_invalidations.inc()

    async def _bus_read(self, key: str) -> Optional[Dict[str, Any]]:
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending_reads[key] = fut
        for peer in self.peers:
            msg = Message.create(
                msg_type=MessageType.CACHE_FETCH,
                sender_id=self.node_id,
                receiver_id=peer,
                payload={"key": key},
            )
            await self.bus.send(msg)
        try:
            return await asyncio.wait_for(fut, timeout=0.5)
        except asyncio.TimeoutError:
            self._pending_reads.pop(key, None)
            return None

    async def _handle_fetch(self, m: Message):
        key = m.payload["key"]
        line = self.cache.get(key)
        if line is None or line.state == MESIState.INVALID:
            return
        # We have a copy. Transition: M/E -> S, S stays S
        if line.state == MESIState.MODIFIED:
            # Writeback (model)
            self.m_writebacks.inc()
        prev_state = line.state
        line.state = MESIState.SHARED

        response = Message.create(
            msg_type=MessageType.CACHE_RESPONSE,
            sender_id=self.node_id,
            receiver_id=m.sender_id,
            payload={
                "key": key,
                "value": line.value,
                "version": line.version,
                "shared": prev_state in (MESIState.SHARED, MESIState.MODIFIED),
            },
        )
        await self.bus.send(response)

    async def _handle_response(self, m: Message):
        key = m.payload["key"]
        fut = self._pending_reads.pop(key, None)
        if fut and not fut.done():
            fut.set_result(
                {
                    "value": m.payload["value"],
                    "version": m.payload["version"],
                    "shared": m.payload.get("shared", True),
                }
            )

    async def _handle_invalidate(self, m: Message):
        key = m.payload["key"]
        line = self.cache.get(key)
        if line:
            line.state = MESIState.INVALID
            self.policy.remove(key)
            # Don't pop — keep the line so we can detect M->I writeback
            if line.state != MESIState.MODIFIED:
                self.cache.pop(key, None)
            self.m_size.set(len(self.cache))

    async def _handle_state_change(self, m: Message):
        # Optional: peers announce M->S transition etc.
        pass

    def get_stats(self) -> Dict[str, Any]:
        states = defaultdict(int)
        for line in self.cache.values():
            states[line.state.value] += 1
        return {
            "node_id": self.node_id,
            "size": len(self.cache),
            "max_size": self.max_size,
            "hits": int(self.m_hits.value),
            "misses": int(self.m_misses.value),
            "hit_ratio": (
                self.m_hits.value / (self.m_hits.value + self.m_misses.value)
                if (self.m_hits.value + self.m_misses.value) > 0
                else 0.0
            ),
            "invalidations": int(self.m_invalidations.value),
            "evictions": int(self.m_evictions.value),
            "writebacks": int(self.m_writebacks.value),
            "states": dict(states),
            "avg_latency_ms": self.m_latency.mean * 1000,
            "p99_latency_ms": self.m_latency.p99 * 1000,
        }
