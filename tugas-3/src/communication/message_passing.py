import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, asdict
from enum import Enum
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


class MessageType(str, Enum):
    # Raft messages
    REQUEST_VOTE = "request_vote"
    REQUEST_VOTE_RESPONSE = "request_vote_response"
    APPEND_ENTRIES = "append_entries"
    APPEND_ENTRIES_RESPONSE = "append_entries_response"

    # Lock messages
    LOCK_REQUEST = "lock_request"
    LOCK_GRANT = "lock_grant"
    LOCK_RELEASE = "lock_release"
    LOCK_DENY = "lock_deny"
    DEADLOCK_CHECK = "deadlock_check"
    DEADLOCK_RESPONSE = "deadlock_response"

    # Queue messages
    QUEUE_ENQUEUE = "queue_enqueue"
    QUEUE_DEQUEUE = "queue_dequeue"
    QUEUE_ACK = "queue_ack"
    QUEUE_REPLICATE = "queue_replicate"

    # Cache messages
    CACHE_READ = "cache_read"
    CACHE_WRITE = "cache_write"
    CACHE_INVALIDATE = "cache_invalidate"
    CACHE_FETCH = "cache_fetch"
    CACHE_RESPONSE = "cache_response"
    CACHE_STATE_CHANGE = "cache_state_change"

    # Heartbeat
    HEARTBEAT = "heartbeat"
    HEARTBEAT_ACK = "heartbeat_ack"

    # Generic
    ERROR = "error"
    ACK = "ack"


@dataclass
class Message:
    msg_id: str
    msg_type: MessageType
    sender_id: str
    receiver_id: str
    payload: Dict[str, Any]
    timestamp: float
    term: int = 0

    @classmethod
    def create(
        cls,
        msg_type: MessageType,
        sender_id: str,
        receiver_id: str,
        payload: Dict[str, Any],
        term: int = 0,
    ) -> "Message":
        return cls(
            msg_id=str(uuid.uuid4()),
            msg_type=msg_type,
            sender_id=sender_id,
            receiver_id=receiver_id,
            payload=payload,
            timestamp=time.time(),
            term=term,
        )

    def to_json(self) -> str:
        d = asdict(self)
        d["msg_type"] = self.msg_type.value
        return json.dumps(d)

    @classmethod
    def from_json(cls, data: str) -> "Message":
        d = json.loads(data)
        d["msg_type"] = MessageType(d["msg_type"])
        return cls(**d)


class NetworkChannel:
    """Simulates a network channel with optional delay and packet loss."""

    def __init__(
        self,
        delay: float = 0.001,
        loss_rate: float = 0.0,
        partition: bool = False,
    ):
        self.delay = delay
        self.loss_rate = loss_rate
        self.partition = partition
        self._queue: asyncio.Queue = asyncio.Queue()

    async def send(self, message: Message):
        import random
        if self.partition:
            return
        if random.random() < self.loss_rate:
            logger.debug(f"Packet dropped: {message.msg_type}")
            return
        if self.delay > 0:
            await asyncio.sleep(self.delay)
        await self._queue.put(message)

    async def receive(self, timeout: float = 1.0) -> Optional[Message]:
        try:
            return await asyncio.wait_for(self._queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None


class MessageBus:
    """Central message bus for inter-node communication."""

    def __init__(self):
        self._channels: Dict[str, asyncio.Queue] = {}
        self._handlers: Dict[str, Dict[MessageType, Callable]] = {}
        self._partitions: set = set()

    def register_node(self, node_id: str):
        if node_id not in self._channels:
            self._channels[node_id] = asyncio.Queue(maxsize=10000)
            self._handlers[node_id] = {}
        logger.debug(f"Registered node: {node_id}")

    def register_handler(
        self, node_id: str, msg_type: MessageType, handler: Callable
    ):
        if node_id not in self._handlers:
            self._handlers[node_id] = {}
        self._handlers[node_id][msg_type] = handler

    def partition_nodes(self, node_ids: list):
        self._partitions.update(node_ids)
        logger.warning(f"Network partition: {node_ids}")

    def heal_partition(self):
        self._partitions.clear()
        logger.info("Network partition healed")

    async def send(self, message: Message, delay: float = 0.0) -> bool:
        if message.sender_id in self._partitions or message.receiver_id in self._partitions:
            logger.debug(f"Message dropped due to partition: {message.msg_type}")
            return False

        if message.receiver_id not in self._channels:
            logger.warning(f"Unknown receiver: {message.receiver_id}")
            return False

        if delay > 0:
            await asyncio.sleep(delay)

        try:
            self._channels[message.receiver_id].put_nowait(message)
            return True
        except asyncio.QueueFull:
            logger.warning(f"Queue full for node: {message.receiver_id}")
            return False

    async def receive(self, node_id: str, timeout: float = 1.0) -> Optional[Message]:
        if node_id not in self._channels:
            return None
        try:
            return await asyncio.wait_for(
                self._channels[node_id].get(), timeout=timeout
            )
        except asyncio.TimeoutError:
            return None

    async def broadcast(
        self, message: Message, exclude: Optional[list] = None
    ):
        exclude = exclude or []
        tasks = []
        for node_id in self._channels:
            if node_id != message.sender_id and node_id not in exclude:
                msg_copy = Message(
                    msg_id=str(uuid.uuid4()),
                    msg_type=message.msg_type,
                    sender_id=message.sender_id,
                    receiver_id=node_id,
                    payload=message.payload,
                    timestamp=message.timestamp,
                    term=message.term,
                )
                tasks.append(self.send(msg_copy))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def dispatch_messages(self, node_id: str):
        """Dispatch loop: receive and route to registered handlers."""
        while True:
            try:
                msg = await self.receive(node_id, timeout=0.05)
            except asyncio.CancelledError:
                break
            if msg is None:
                continue
            handlers = self._handlers.get(node_id, {})
            handler = handlers.get(msg.msg_type)
            if handler:
                try:
                    await handler(msg)
                except Exception as e:
                    logger.error(f"Handler error [{node_id}] {msg.msg_type}: {e}")
            else:
                logger.debug(f"No handler for {msg.msg_type} on {node_id}")


global_bus = MessageBus()
