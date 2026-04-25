import asyncio
import logging
import time

from src.models import Event
from src.store import DedupStore

logger = logging.getLogger(__name__)


class AggregatorService:
    def __init__(self, store: DedupStore) -> None:
        self.store = store
        self.queue: asyncio.Queue[Event] = asyncio.Queue()
        self.received = 0
        self.unique_processed = 0
        self.duplicate_dropped = 0
        self.started_at = time.time()
        self._worker_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._worker())

    async def stop(self) -> None:
        if self._worker_task is not None:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass

    async def publish(self, events: list[Event]) -> dict:
        for event in events:
            self.received += 1
            await self.queue.put(event)
        return {"accepted": len(events), "queue_size": self.queue.qsize()}

    async def _worker(self) -> None:
        while True:
            event = await self.queue.get()
            try:
                inserted = await asyncio.to_thread(self.store.add_if_new, event)
                if inserted:
                    self.unique_processed += 1
                else:
                    self.duplicate_dropped += 1
                    logger.info(
                        "Duplicate dropped topic=%s event_id=%s",
                        event.topic,
                        event.event_id,
                    )
            finally:
                self.queue.task_done()

    async def get_events(self, topic: str | None = None) -> list[dict]:
        return await asyncio.to_thread(self.store.list_events, topic)

    async def get_stats(self) -> dict:
        topics = await asyncio.to_thread(self.store.list_topics)
        return {
            "received": self.received,
            "unique_processed": self.unique_processed,
            "duplicate_dropped": self.duplicate_dropped,
            "topics": topics,
            "uptime_seconds": round(time.time() - self.started_at, 3),
            "queue_size": self.queue.qsize(),
        }
