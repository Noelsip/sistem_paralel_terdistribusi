import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

from src.communication.message_passing import Message, MessageType, MessageBus

logger = logging.getLogger(__name__)


class PBFTPhase(str, Enum):
    PRE_PREPARE = "pre_prepare"
    PREPARE = "prepare"
    COMMIT = "commit"
    REPLY = "reply"


@dataclass
class PBFTRequest:
    request_id: str
    client_id: str
    operation: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)


@dataclass
class PBFTLogEntry:
    seq_num: int
    view: int
    request: PBFTRequest
    digest: str
    pre_prepare_received: bool = False
    prepares: Set[str] = field(default_factory=set)
    commits: Set[str] = field(default_factory=set)
    committed: bool = False


def compute_digest(data: Any) -> str:
    return hashlib.sha256(str(data).encode()).hexdigest()


class PBFTNode:
    def __init__(
        self,
        node_id: str,
        peers: List[str],
        bus: MessageBus,
        apply_callback: Optional[Callable] = None,
    ):
        self.node_id = node_id
        self.peers = peers
        self.bus = bus
        self.apply_callback = apply_callback

        self.all_nodes = sorted([node_id] + list(peers))
        self.n = len(self.all_nodes)
        self.f = (self.n - 1) // 3

        self.view: int = 0
        self.seq_num: int = 0
        self.log: Dict[int, PBFTLogEntry] = {}
        self.applied: Set[int] = set()
        self._byzantine: bool = False  # If true, send conflicting messages

        self.bus.register_node(self.node_id)
        self.bus.register_handler(
            self.node_id, MessageType.APPEND_ENTRIES, self._handle_pre_prepare
        )

    @property
    def primary(self) -> str:
        return self.all_nodes[self.view % self.n]

    @property
    def is_primary(self) -> bool:
        return self.primary == self.node_id

    def set_byzantine(self, value: bool):
        self._byzantine = value
        logger.warning(f"[{self.node_id}] Byzantine mode = {value}")

    async def submit(self, request: PBFTRequest) -> bool:
        if not self.is_primary:
            return False
        self.seq_num += 1
        digest = compute_digest(request)
        entry = PBFTLogEntry(
            seq_num=self.seq_num,
            view=self.view,
            request=request,
            digest=digest,
            pre_prepare_received=True,
        )
        self.log[self.seq_num] = entry
        await self._broadcast_pre_prepare(entry)
        return True

    async def _broadcast_pre_prepare(self, entry: PBFTLogEntry):
        for peer in self.peers:
            payload = {
                "phase": PBFTPhase.PRE_PREPARE.value,
                "view": entry.view,
                "seq_num": entry.seq_num,
                "digest": entry.digest,
                "request": {
                    "request_id": entry.request.request_id,
                    "client_id": entry.request.client_id,
                    "operation": entry.request.operation,
                    "timestamp": entry.request.timestamp,
                },
            }
            if self._byzantine:
                # Byzantine primary: send different digests to different replicas
                payload["digest"] = compute_digest(f"malicious-{peer}")
            msg = Message.create(
                msg_type=MessageType.APPEND_ENTRIES,
                sender_id=self.node_id,
                receiver_id=peer,
                payload=payload,
                term=self.view,
            )
            await self.bus.send(msg)

    async def _handle_pre_prepare(self, msg: Message):
        phase = msg.payload.get("phase")
        if phase == PBFTPhase.PRE_PREPARE.value:
            await self._on_pre_prepare(msg)
        elif phase == PBFTPhase.PREPARE.value:
            await self._on_prepare(msg)
        elif phase == PBFTPhase.COMMIT.value:
            await self._on_commit(msg)

    async def _on_pre_prepare(self, msg: Message):
        view = msg.payload["view"]
        seq_num = msg.payload["seq_num"]
        digest = msg.payload["digest"]
        request_data = msg.payload["request"]

        if view != self.view:
            return
        if msg.sender_id != self.primary:
            return

        request = PBFTRequest(**request_data)
        expected_digest = compute_digest(request)
        if digest != expected_digest:
            logger.warning(
                f"[{self.node_id}] Bad digest in PRE-PREPARE seq={seq_num}"
            )
            return

        if seq_num not in self.log:
            self.log[seq_num] = PBFTLogEntry(
                seq_num=seq_num, view=view, request=request, digest=digest
            )
        entry = self.log[seq_num]
        entry.pre_prepare_received = True

        # Broadcast PREPARE
        for peer in self.peers:
            prepare_msg = Message.create(
                msg_type=MessageType.APPEND_ENTRIES,
                sender_id=self.node_id,
                receiver_id=peer,
                payload={
                    "phase": PBFTPhase.PREPARE.value,
                    "view": view,
                    "seq_num": seq_num,
                    "digest": digest,
                },
                term=self.view,
            )
            await self.bus.send(prepare_msg)
        # Self-prepare
        entry.prepares.add(self.node_id)

    async def _on_prepare(self, msg: Message):
        seq_num = msg.payload["seq_num"]
        digest = msg.payload["digest"]

        if seq_num not in self.log:
            return
        entry = self.log[seq_num]
        if entry.digest != digest:
            return
        entry.prepares.add(msg.sender_id)

        # Need 2f matching prepares (excluding self pre-prepare)
        if (
            entry.pre_prepare_received
            and len(entry.prepares) >= 2 * self.f
            and msg.sender_id not in entry.commits
        ):
            # Broadcast COMMIT
            for peer in self.peers:
                commit_msg = Message.create(
                    msg_type=MessageType.APPEND_ENTRIES,
                    sender_id=self.node_id,
                    receiver_id=peer,
                    payload={
                        "phase": PBFTPhase.COMMIT.value,
                        "view": self.view,
                        "seq_num": seq_num,
                        "digest": digest,
                    },
                    term=self.view,
                )
                await self.bus.send(commit_msg)
            entry.commits.add(self.node_id)

    async def _on_commit(self, msg: Message):
        seq_num = msg.payload["seq_num"]
        digest = msg.payload["digest"]
        if seq_num not in self.log:
            return
        entry = self.log[seq_num]
        if entry.digest != digest:
            return
        entry.commits.add(msg.sender_id)

        # Need 2f+1 matching commits
        if (
            len(entry.commits) >= 2 * self.f + 1
            and not entry.committed
        ):
            entry.committed = True
            await self._apply(entry)

    async def _apply(self, entry: PBFTLogEntry):
        if entry.seq_num in self.applied:
            return
        self.applied.add(entry.seq_num)
        logger.info(
            f"[{self.node_id}] PBFT committed seq={entry.seq_num} "
            f"op={entry.request.operation}"
        )
        if self.apply_callback:
            try:
                if asyncio.iscoroutinefunction(self.apply_callback):
                    await self.apply_callback(entry.request.operation)
                else:
                    self.apply_callback(entry.request.operation)
            except Exception as e:
                logger.error(f"[{self.node_id}] apply error: {e}")

    def get_state(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "view": self.view,
            "primary": self.primary,
            "is_primary": self.is_primary,
            "n": self.n,
            "f": self.f,
            "log_size": len(self.log),
            "applied": len(self.applied),
            "byzantine": self._byzantine,
        }
