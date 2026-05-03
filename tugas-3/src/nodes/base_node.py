import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from src.communication.message_passing import MessageBus, global_bus
from src.communication.failure_detector import FailureDetector

logger = logging.getLogger(__name__)


class BaseNode(ABC):
    """
    Abstract base class for all distributed nodes.

    Provides common infrastructure:
    - Message bus registration
    - Failure detection
    - Lifecycle management (start/stop)
    - Health/status reporting
    """

    def __init__(
        self,
        node_id: str,
        peers: List[str],
        bus: Optional[MessageBus] = None,
    ):
        self.node_id = node_id
        self.peers = peers
        self.bus = bus or global_bus
        self.failure_detector = FailureDetector(node_id, peers)
        self._running = False
        self._tasks: List[asyncio.Task] = []

    async def start(self):
        if self._running:
            return
        self._running = True
        self.bus.register_node(self.node_id)
        self.failure_detector.start()
        await self._on_start()
        logger.info(f"[{self.node_id}] node started")

    async def stop(self):
        if not self._running:
            return
        self._running = False
        self.failure_detector.stop()
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
        await self._on_stop()
        logger.info(f"[{self.node_id}] node stopped")

    @abstractmethod
    async def _on_start(self):
        pass

    @abstractmethod
    async def _on_stop(self):
        pass

    def health(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "running": self._running,
            "peers": self.peers,
            "alive_peers": self.failure_detector.get_alive_nodes(),
            "dead_peers": self.failure_detector.get_dead_nodes(),
        }
