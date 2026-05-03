import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from src.communication.message_passing import (
    Message,
    MessageType,
    MessageBus,
)

logger = logging.getLogger(__name__)


class RaftState(str, Enum):
    FOLLOWER = "follower"
    CANDIDATE = "candidate"
    LEADER = "leader"


@dataclass
class LogEntry:
    term: int
    index: int
    command: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)


@dataclass
class RaftPersistentState:
    """State that must be persisted across restarts."""
    current_term: int = 0
    voted_for: Optional[str] = None
    log: List[LogEntry] = field(default_factory=list)


class RaftNode:

    def __init__(
        self,
        node_id: str,
        peers: List[str],
        bus: MessageBus,
        election_timeout_min: float = 0.15,
        election_timeout_max: float = 0.30,
        heartbeat_interval: float = 0.05,
        apply_callback: Optional[Callable[[Dict[str, Any]], Any]] = None,
    ):
        self.node_id = node_id
        self.peers = peers
        self.bus = bus
        self.election_timeout_min = election_timeout_min
        self.election_timeout_max = election_timeout_max
        self.heartbeat_interval = heartbeat_interval
        self.apply_callback = apply_callback

        # Persistent state
        self.persistent = RaftPersistentState()

        # Volatile state
        self.state: RaftState = RaftState.FOLLOWER
        self.commit_index: int = -1
        self.last_applied: int = -1
        self.leader_id: Optional[str] = None

        # Volatile state on leaders
        self.next_index: Dict[str, int] = {}
        self.match_index: Dict[str, int] = {}

        # Election state
        self.votes_received: set = set()
        self.last_heartbeat: float = time.time()
        self.election_deadline: float = self._reset_election_timeout()

        # Pending commands waiting for commit
        self._pending_commands: Dict[int, asyncio.Future] = {}
        self._running = False
        self._tasks: List[asyncio.Task] = []

        # Register handlers
        self.bus.register_node(self.node_id)
        self.bus.register_handler(
            self.node_id, MessageType.REQUEST_VOTE, self._handle_request_vote
        )
        self.bus.register_handler(
            self.node_id,
            MessageType.REQUEST_VOTE_RESPONSE,
            self._handle_vote_response,
        )
        self.bus.register_handler(
            self.node_id, MessageType.APPEND_ENTRIES, self._handle_append_entries
        )
        self.bus.register_handler(
            self.node_id,
            MessageType.APPEND_ENTRIES_RESPONSE,
            self._handle_append_response,
        )

    def _reset_election_timeout(self) -> float:
        timeout = random.uniform(
            self.election_timeout_min, self.election_timeout_max
        )
        self.election_deadline = time.time() + timeout
        return self.election_deadline

    def _last_log_index(self) -> int:
        return len(self.persistent.log) - 1

    def _last_log_term(self) -> int:
        if not self.persistent.log:
            return 0
        return self.persistent.log[-1].term

    def _become_follower(self, term: int):
        if term > self.persistent.current_term:
            self.persistent.current_term = term
            self.persistent.voted_for = None
        self.state = RaftState.FOLLOWER
        self._reset_election_timeout()
        logger.debug(f"[{self.node_id}] -> FOLLOWER term={self.persistent.current_term}")

    def _become_candidate(self):
        self.state = RaftState.CANDIDATE
        self.persistent.current_term += 1
        self.persistent.voted_for = self.node_id
        self.votes_received = {self.node_id}
        self._reset_election_timeout()
        logger.info(
            f"[{self.node_id}] -> CANDIDATE term={self.persistent.current_term}"
        )

    def _become_leader(self):
        self.state = RaftState.LEADER
        self.leader_id = self.node_id
        last_idx = self._last_log_index()
        for peer in self.peers:
            self.next_index[peer] = last_idx + 1
            self.match_index[peer] = -1
        logger.info(
            f"[{self.node_id}] -> LEADER term={self.persistent.current_term}"
        )

    async def start(self):
        if self._running:
            return
        self._running = True
        self._tasks.append(asyncio.create_task(self.bus.dispatch_messages(self.node_id)))
        self._tasks.append(asyncio.create_task(self._main_loop()))

    async def stop(self):
        self._running = False
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self._tasks, return_exceptions=True),
                    timeout=1.0,
                )
            except asyncio.TimeoutError:
                pass
        self._tasks.clear()

    async def _main_loop(self):
        while self._running:
            try:
                if self.state == RaftState.FOLLOWER:
                    await self._follower_tick()
                elif self.state == RaftState.CANDIDATE:
                    await self._candidate_tick()
                elif self.state == RaftState.LEADER:
                    await self._leader_tick()
            except Exception as e:
                logger.error(f"[{self.node_id}] main loop error: {e}")
            await asyncio.sleep(0.01)

    async def _follower_tick(self):
        if time.time() >= self.election_deadline:
            self._become_candidate()
            await self._start_election()

    async def _candidate_tick(self):
        if time.time() >= self.election_deadline:
            self._become_candidate()
            await self._start_election()

    async def _leader_tick(self):
        await self._broadcast_heartbeat()
        await asyncio.sleep(self.heartbeat_interval)

    async def _start_election(self):
        logger.info(
            f"[{self.node_id}] starting election term={self.persistent.current_term}"
        )
        for peer in self.peers:
            msg = Message.create(
                msg_type=MessageType.REQUEST_VOTE,
                sender_id=self.node_id,
                receiver_id=peer,
                payload={
                    "candidate_id": self.node_id,
                    "last_log_index": self._last_log_index(),
                    "last_log_term": self._last_log_term(),
                },
                term=self.persistent.current_term,
            )
            await self.bus.send(msg)

    async def _handle_request_vote(self, msg: Message):
        term = msg.term
        candidate_id = msg.payload["candidate_id"]
        last_log_index = msg.payload["last_log_index"]
        last_log_term = msg.payload["last_log_term"]

        granted = False

        if term < self.persistent.current_term:
            granted = False
        else:
            if term > self.persistent.current_term:
                self._become_follower(term)

            log_ok = (
                last_log_term > self._last_log_term()
                or (
                    last_log_term == self._last_log_term()
                    and last_log_index >= self._last_log_index()
                )
            )
            already_voted = (
                self.persistent.voted_for is not None
                and self.persistent.voted_for != candidate_id
            )

            if log_ok and not already_voted:
                self.persistent.voted_for = candidate_id
                granted = True
                self._reset_election_timeout()

        response = Message.create(
            msg_type=MessageType.REQUEST_VOTE_RESPONSE,
            sender_id=self.node_id,
            receiver_id=candidate_id,
            payload={"vote_granted": granted, "voter_id": self.node_id},
            term=self.persistent.current_term,
        )
        await self.bus.send(response)

    async def _handle_vote_response(self, msg: Message):
        if self.state != RaftState.CANDIDATE:
            return
        if msg.term > self.persistent.current_term:
            self._become_follower(msg.term)
            return
        if msg.term < self.persistent.current_term:
            return
        if msg.payload.get("vote_granted"):
            self.votes_received.add(msg.payload["voter_id"])
            majority = (len(self.peers) + 1) // 2 + 1
            if len(self.votes_received) >= majority:
                self._become_leader()
                await self._broadcast_heartbeat()

    async def _broadcast_heartbeat(self):
        for peer in self.peers:
            await self._send_append_entries(peer)

    async def _send_append_entries(self, peer: str):
        next_idx = self.next_index.get(peer, 0)
        prev_log_index = next_idx - 1
        prev_log_term = 0
        if 0 <= prev_log_index < len(self.persistent.log):
            prev_log_term = self.persistent.log[prev_log_index].term

        entries = []
        if next_idx < len(self.persistent.log):
            entries = [
                {"term": e.term, "index": e.index, "command": e.command}
                for e in self.persistent.log[next_idx : next_idx + 50]
            ]

        msg = Message.create(
            msg_type=MessageType.APPEND_ENTRIES,
            sender_id=self.node_id,
            receiver_id=peer,
            payload={
                "leader_id": self.node_id,
                "prev_log_index": prev_log_index,
                "prev_log_term": prev_log_term,
                "entries": entries,
                "leader_commit": self.commit_index,
            },
            term=self.persistent.current_term,
        )
        await self.bus.send(msg)

    async def _handle_append_entries(self, msg: Message):
        term = msg.term
        leader_id = msg.payload["leader_id"]
        prev_log_index = msg.payload["prev_log_index"]
        prev_log_term = msg.payload["prev_log_term"]
        entries = msg.payload["entries"]
        leader_commit = msg.payload["leader_commit"]

        success = False
        match_index = -1

        if term < self.persistent.current_term:
            success = False
        else:
            if term > self.persistent.current_term:
                self._become_follower(term)
            self.state = RaftState.FOLLOWER
            self.leader_id = leader_id
            self._reset_election_timeout()

            log_ok = prev_log_index == -1 or (
                prev_log_index < len(self.persistent.log)
                and self.persistent.log[prev_log_index].term == prev_log_term
            )

            if log_ok:
                success = True
                # Truncate conflicting entries and append new
                insert_index = prev_log_index + 1
                for i, e in enumerate(entries):
                    pos = insert_index + i
                    if pos < len(self.persistent.log):
                        if self.persistent.log[pos].term != e["term"]:
                            self.persistent.log = self.persistent.log[:pos]
                            self.persistent.log.append(
                                LogEntry(
                                    term=e["term"],
                                    index=e["index"],
                                    command=e["command"],
                                )
                            )
                    else:
                        self.persistent.log.append(
                            LogEntry(
                                term=e["term"],
                                index=e["index"],
                                command=e["command"],
                            )
                        )
                match_index = prev_log_index + len(entries)

                if leader_commit > self.commit_index:
                    self.commit_index = min(leader_commit, self._last_log_index())
                    await self._apply_committed()

        response = Message.create(
            msg_type=MessageType.APPEND_ENTRIES_RESPONSE,
            sender_id=self.node_id,
            receiver_id=leader_id,
            payload={
                "success": success,
                "match_index": match_index,
                "follower_id": self.node_id,
            },
            term=self.persistent.current_term,
        )
        await self.bus.send(response)

    async def _handle_append_response(self, msg: Message):
        if self.state != RaftState.LEADER:
            return
        if msg.term > self.persistent.current_term:
            self._become_follower(msg.term)
            return

        follower = msg.payload["follower_id"]
        if msg.payload["success"]:
            self.match_index[follower] = msg.payload["match_index"]
            self.next_index[follower] = msg.payload["match_index"] + 1
            await self._update_commit_index()
        else:
            self.next_index[follower] = max(0, self.next_index.get(follower, 0) - 1)

    async def _update_commit_index(self):
        for n in range(self._last_log_index(), self.commit_index, -1):
            if n < 0 or n >= len(self.persistent.log):
                continue
            if self.persistent.log[n].term != self.persistent.current_term:
                continue
            count = 1  # self
            for peer in self.peers:
                if self.match_index.get(peer, -1) >= n:
                    count += 1
            majority = (len(self.peers) + 1) // 2 + 1
            if count >= majority:
                self.commit_index = n
                await self._apply_committed()
                break

    async def _apply_committed(self):
        while self.last_applied < self.commit_index:
            self.last_applied += 1
            entry = self.persistent.log[self.last_applied]
            result = None
            if self.apply_callback:
                try:
                    if asyncio.iscoroutinefunction(self.apply_callback):
                        result = await self.apply_callback(entry.command)
                    else:
                        result = self.apply_callback(entry.command)
                except Exception as e:
                    logger.error(f"[{self.node_id}] apply error: {e}")
            if entry.index in self._pending_commands:
                fut = self._pending_commands.pop(entry.index)
                if not fut.done():
                    fut.set_result(result)

    async def submit(
        self, command: Dict[str, Any], timeout: float = 5.0
    ) -> Optional[Any]:
        """Submit a command to the cluster. Only succeeds on leader."""
        if self.state != RaftState.LEADER:
            return None
        index = len(self.persistent.log)
        entry = LogEntry(
            term=self.persistent.current_term, index=index, command=command
        )
        self.persistent.log.append(entry)
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending_commands[index] = fut
        await self._broadcast_heartbeat()
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending_commands.pop(index, None)
            return None

    @property
    def is_leader(self) -> bool:
        return self.state == RaftState.LEADER

    def get_state_info(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "state": self.state.value,
            "term": self.persistent.current_term,
            "leader_id": self.leader_id,
            "log_size": len(self.persistent.log),
            "commit_index": self.commit_index,
            "last_applied": self.last_applied,
        }
