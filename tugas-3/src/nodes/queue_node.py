"""
Distributed Queue System.

Architecture:
- Consistent hashing ring distributes messages across nodes by partition key.
- Each message is replicated to N successors (replication factor).
- At-least-once delivery: consumer ACKs remove the message; un-ACKed messages
  are re-delivered after visibility timeout.
- Persistence: append-only log on disk; replayed on restart.
- Node failure: data on a dead node is recovered from replicas held by
  successor nodes on the ring.
"""

import asyncio
import bisect
import hashlib
import json
import logging
import os
import time
import uuid
from collections import deque
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Set, Tuple

from src.communication.message_passing import (
    Message,
    MessageType,
    MessageBus,
    global_bus,
)
from src.nodes.base_node import BaseNode

logger = logging.getLogger(__name__)


@dataclass
class QueueMessage:
    msg_id: str
    queue: str
    partition_key: str
    payload: Any
    timestamp: float = field(default_factory=time.time)
    delivery_count: int = 0
    visibility_timeout_until: float = 0.0
    primary_node: Optional[str] = None
    replicas: List[str] = field(default_factory=list)


class ConsistentHashRing:
    """
    Consistent hash ring with virtual nodes.
    Each physical node owns multiple positions on the ring to balance load.
    """

    def __init__(self, virtual_nodes: int = 150):
        self.virtual_nodes = virtual_nodes
        self._ring: List[Tuple[int, str]] = []  # (hash, node_id)
        self._nodes: Set[str] = set()

    @staticmethod
    def _hash(key: str) -> int:
        return int(hashlib.md5(key.encode()).hexdigest(), 16)

    def add_node(self, node_id: str):
        if node_id in self._nodes:
            return
        self._nodes.add(node_id)
        for i in range(self.virtual_nodes):
            h = self._hash(f"{node_id}:vn{i}")
            bisect.insort(self._ring, (h, node_id))

    def remove_node(self, node_id: str):
        if node_id not in self._nodes:
            return
        self._nodes.discard(node_id)
        self._ring = [(h, n) for h, n in self._ring if n != node_id]

    def get_node(self, key: str) -> Optional[str]:
        if not self._ring:
            return None
        h = self._hash(key)
        idx = bisect.bisect_right(self._ring, (h, "\xff"))
        if idx == len(self._ring):
            idx = 0
        return self._ring[idx][1]

    def get_n_nodes(self, key: str, n: int) -> List[str]:
        """Return the primary plus n-1 replicas (distinct physical nodes)."""
        if not self._ring:
            return []
        h = self._hash(key)
        idx = bisect.bisect_right(self._ring, (h, "\xff"))
        result: List[str] = []
        seen: Set[str] = set()
        i = idx
        while len(result) < n and len(seen) < len(self._nodes):
            if i >= len(self._ring):
                i = 0
            node_id = self._ring[i][1]
            if node_id not in seen:
                seen.add(node_id)
                result.append(node_id)
            i += 1
            if i == idx and result:
                break
        return result

    @property
    def nodes(self) -> List[str]:
        return list(self._nodes)


class PersistentLog:
    """Append-only on-disk log for durability."""

    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._lock = asyncio.Lock()
        self.redis_enabled = os.getenv("REDIS_ENABLED", "false").lower() == "true"
        self.redis_key = f"distsync:queue-log:{os.path.splitext(os.path.basename(path))[0]}"
        self._redis = None
        self._redis_failed = False

    async def _redis_client(self):
        if not self.redis_enabled or self._redis_failed:
            return None
        if self._redis is None:
            try:
                import redis.asyncio as redis

                password = os.getenv("REDIS_PASSWORD") or None
                self._redis = redis.Redis(
                    host=os.getenv("REDIS_HOST", "localhost"),
                    port=int(os.getenv("REDIS_PORT", "6379")),
                    db=int(os.getenv("REDIS_DB", "0")),
                    password=password,
                    decode_responses=True,
                )
                await self._redis.ping()
            except Exception as exc:
                self._redis_failed = True
                logger.warning("Redis queue log mirror disabled: %s", exc)
                return None
        return self._redis

    async def append(self, record: Dict[str, Any]):
        encoded = json.dumps(record)
        async with self._lock:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(encoded + "\n")
                f.flush()
                os.fsync(f.fileno())
            client = await self._redis_client()
            if client:
                await client.rpush(self.redis_key, encoded)

    def replay(self) -> List[Dict[str, Any]]:
        if not os.path.exists(self.path):
            return []
        records = []
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return records

    async def truncate(self):
        async with self._lock:
            open(self.path, "w").close()
            client = await self._redis_client()
            if client:
                await client.delete(self.redis_key)


class QueueNode(BaseNode):
    def __init__(
        self,
        node_id: str,
        peers: List[str],
        bus: Optional[MessageBus] = None,
        virtual_nodes: int = 150,
        replication_factor: int = 2,
        persistence_dir: str = "/tmp/queue_data",
        visibility_timeout: float = 30.0,
    ):
        super().__init__(node_id, peers, bus)
        self.replication_factor = replication_factor
        self.visibility_timeout = visibility_timeout
        self.ring = ConsistentHashRing(virtual_nodes)
        for peer in peers:
            self.ring.add_node(peer)
        self.ring.add_node(node_id)

        # Local queue storage: queue_name -> deque of QueueMessage
        self.queues: Dict[str, deque] = {}
        # Inflight messages waiting for ACK: msg_id -> QueueMessage
        self.inflight: Dict[str, QueueMessage] = {}
        # Replicas stored on this node (mirror of primary on another node)
        self.replicas: Dict[str, QueueMessage] = {}

        os.makedirs(persistence_dir, exist_ok=True)
        self.log = PersistentLog(
            os.path.join(persistence_dir, f"{node_id}.log")
        )

        self.stats = {
            "enqueued": 0,
            "dequeued": 0,
            "acked": 0,
            "redelivered": 0,
            "replicated": 0,
        }

    async def _on_start(self):
        # Replay persisted log
        records = self.log.replay()
        for rec in records:
            self._apply_log_record(rec)
        logger.info(f"[{self.node_id}] replayed {len(records)} log entries")

        # Register message handlers
        self.bus.register_handler(
            self.node_id, MessageType.QUEUE_ENQUEUE, self._handle_enqueue
        )
        self.bus.register_handler(
            self.node_id, MessageType.QUEUE_REPLICATE, self._handle_replicate
        )
        self.bus.register_handler(
            self.node_id, MessageType.QUEUE_DEQUEUE, self._handle_dequeue
        )
        self.bus.register_handler(
            self.node_id, MessageType.QUEUE_ACK, self._handle_ack
        )

        self._tasks.append(asyncio.create_task(self.bus.dispatch_messages(self.node_id)))
        self._tasks.append(asyncio.create_task(self._visibility_timeout_loop()))

        # Failure-driven re-replication
        self.failure_detector.on_failure(self._on_peer_failure)

    async def _on_stop(self):
        pass

    def _apply_log_record(self, rec: Dict[str, Any]):
        op = rec.get("op")
        if op == "enqueue":
            msg = QueueMessage(**rec["message"])
            queue = self.queues.setdefault(msg.queue, deque())
            queue.append(msg)
        elif op == "ack":
            self.inflight.pop(rec["msg_id"], None)
        elif op == "replicate":
            msg = QueueMessage(**rec["message"])
            self.replicas[msg.msg_id] = msg

    async def _on_peer_failure(self, peer_id: str):
        logger.warning(f"[{self.node_id}] peer {peer_id} failed — promoting replicas")
        promoted = 0
        for msg_id, msg in list(self.replicas.items()):
            if msg.primary_node == peer_id:
                queue = self.queues.setdefault(msg.queue, deque())
                msg.primary_node = self.node_id
                queue.append(msg)
                self.replicas.pop(msg_id, None)
                promoted += 1
        if promoted:
            logger.info(f"[{self.node_id}] promoted {promoted} replicas from {peer_id}")

    async def enqueue(
        self, queue: str, payload: Any, partition_key: Optional[str] = None
    ) -> str:
        msg_id = str(uuid.uuid4())
        partition_key = partition_key or msg_id
        nodes = self.ring.get_n_nodes(partition_key, self.replication_factor)
        if not nodes:
            return ""
        primary = nodes[0]
        replicas = nodes[1:]

        msg = QueueMessage(
            msg_id=msg_id,
            queue=queue,
            partition_key=partition_key,
            payload=payload,
            primary_node=primary,
            replicas=replicas,
        )

        if primary == self.node_id:
            await self._store_local(msg)
        else:
            forward = Message.create(
                msg_type=MessageType.QUEUE_ENQUEUE,
                sender_id=self.node_id,
                receiver_id=primary,
                payload={"message": asdict(msg)},
            )
            await self.bus.send(forward)

        # Send replicas
        for replica_node in replicas:
            if replica_node == self.node_id:
                self.replicas[msg_id] = msg
                await self.log.append({"op": "replicate", "message": asdict(msg)})
            else:
                rep_msg = Message.create(
                    msg_type=MessageType.QUEUE_REPLICATE,
                    sender_id=self.node_id,
                    receiver_id=replica_node,
                    payload={"message": asdict(msg)},
                )
                await self.bus.send(rep_msg)

        # In the in-process transport used by tests and demos, replication
        # handlers run in background dispatch tasks. Yield briefly so enqueue
        # returns after queued replica messages have a chance to be applied.
        await asyncio.sleep(0.001)
        self.stats["enqueued"] += 1
        self.stats["replicated"] += len(replicas)
        return msg_id

    async def _store_local(self, msg: QueueMessage):
        queue = self.queues.setdefault(msg.queue, deque())
        queue.append(msg)
        await self.log.append({"op": "enqueue", "message": asdict(msg)})

    async def _handle_enqueue(self, m: Message):
        msg_data = m.payload["message"]
        msg = QueueMessage(**msg_data)
        await self._store_local(msg)

    async def _handle_replicate(self, m: Message):
        msg_data = m.payload["message"]
        msg = QueueMessage(**msg_data)
        self.replicas[msg.msg_id] = msg
        await self.log.append({"op": "replicate", "message": asdict(msg)})

    async def dequeue(self, queue: str) -> Optional[QueueMessage]:
        """Pull-based dequeue. Returns next visible message in any node's
        local queue; routes to the primary if needed."""
        self._requeue_expired_inflight()
        # Local first
        msg = self._pop_local(queue)
        if msg:
            return msg
        # Try peers
        for peer in self.peers:
            req = Message.create(
                msg_type=MessageType.QUEUE_DEQUEUE,
                sender_id=self.node_id,
                receiver_id=peer,
                payload={"queue": queue},
            )
            await self.bus.send(req)
        return None

    def _pop_local(self, queue: str) -> Optional[QueueMessage]:
        q = self.queues.get(queue)
        if not q:
            return None
        now = time.time()
        for _ in range(len(q)):
            msg = q.popleft()
            if msg.visibility_timeout_until > now:
                q.append(msg)
                continue
            msg.delivery_count += 1
            msg.visibility_timeout_until = now + self.visibility_timeout
            self.inflight[msg.msg_id] = msg
            self.stats["dequeued"] += 1
            return msg
        return None

    async def _handle_dequeue(self, m: Message):
        queue = m.payload["queue"]
        msg = self._pop_local(queue)
        if msg:
            response = Message.create(
                msg_type=MessageType.QUEUE_ENQUEUE,
                sender_id=self.node_id,
                receiver_id=m.sender_id,
                payload={"message": asdict(msg), "delivered": True},
            )
            await self.bus.send(response)

    async def ack(self, msg_id: str) -> bool:
        if msg_id in self.inflight:
            msg = self.inflight.pop(msg_id)
            await self.log.append({"op": "ack", "msg_id": msg_id})
            self.stats["acked"] += 1
            # Notify replicas to remove
            for replica_node in msg.replicas:
                if replica_node != self.node_id:
                    ack_msg = Message.create(
                        msg_type=MessageType.QUEUE_ACK,
                        sender_id=self.node_id,
                        receiver_id=replica_node,
                        payload={"msg_id": msg_id},
                    )
                    await self.bus.send(ack_msg)
                else:
                    self.replicas.pop(msg_id, None)
            return True
        return False

    async def _handle_ack(self, m: Message):
        msg_id = m.payload["msg_id"]
        self.replicas.pop(msg_id, None)
        await self.log.append({"op": "ack", "msg_id": msg_id})

    async def _visibility_timeout_loop(self):
        while self._running:
            await asyncio.sleep(max(0.05, min(1.0, self.visibility_timeout / 2)))
            self._requeue_expired_inflight()

    def _requeue_expired_inflight(self):
        now = time.time()
        for msg_id, msg in list(self.inflight.items()):
            if msg.visibility_timeout_until < now:
                # Re-deliver: put back into queue
                self.inflight.pop(msg_id, None)
                queue = self.queues.setdefault(msg.queue, deque())
                msg.visibility_timeout_until = 0.0
                queue.append(msg)
                self.stats["redelivered"] += 1
                logger.info(
                    f"Re-delivering msg {msg_id} (count={msg.delivery_count})"
                )

    def get_stats(self) -> Dict[str, Any]:
        return {
            **self.stats,
            "queues": {q: len(d) for q, d in self.queues.items()},
            "inflight": len(self.inflight),
            "replicas": len(self.replicas),
            "ring_nodes": self.ring.nodes,
        }
