"""Broker internal berbasis Redis Streams."""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Dict, List, Optional, Tuple

import redis.asyncio as redis
from redis.exceptions import ResponseError

BROKER_URL = os.getenv("BROKER_URL", "redis://broker:6379/0")
STREAM_KEY = os.getenv("STREAM_KEY", "events:stream")
GROUP = os.getenv("CONSUMER_GROUP", "aggregators")
CLAIM_MIN_IDLE_MS = int(os.getenv("CLAIM_MIN_IDLE_MS", "15000"))

class Broker:
    def __init__(self) -> None:
        self.r: Optional[redis.Redis] = None

    async def connect(self, retries: int = 30, delay: float = 1.0) -> None:
        last_err: Optional[Exception] = None
        for _ in range(retries):
            try:
                self.r = redis.from_url(BROKER_URL, decode_responses=True)
                await self.r.ping()
                try:
                    await self.r.xgroup_create(
                        STREAM_KEY, GROUP, id="0", mkstream=True
                    )
                except ResponseError as e:
                    if "BUSYGROUP" not in str(e):
                        raise
                return
            except Exception as e:  # noqa: BLE001
                last_err = e
                await asyncio.sleep(delay)
        raise RuntimeError(f"Gagal konek Redis: {last_err}")

    async def close(self) -> None:
        if self.r:
            await self.r.aclose()

    async def ping(self) -> bool:
        return bool(self.r and await self.r.ping())

    async def publish(self, ev: Dict[str, Any]) -> str:
        """Mengirim satu event ke stream via XADD. Mengembalikan stream id."""
        return await self.r.xadd(STREAM_KEY, {"data": json.dumps(ev)})

    async def read_group(
        self, consumer: str, count: int = 20, block_ms: int = 2000
    ) -> List[Tuple[str, Dict[str, Any]]]:
        """Membaca entry baru (">") untuk consumer ini dalam group."""
        res = await self.r.xreadgroup(
            GROUP, consumer, {STREAM_KEY: ">"}, count=count, block=block_ms
        )
        return self._flatten(res)

    async def claim_stale(
        self, consumer: str, count: int = 50
    ) -> List[Tuple[str, Dict[str, Any]]]:
        """Mengambil-alih entry di PEL milik consumer mati via XAUTOCLAIM."""
        try:
            res = await self.r.xautoclaim(
                STREAM_KEY,
                GROUP,
                consumer,
                min_idle_time=CLAIM_MIN_IDLE_MS,
                start_id="0-0",
                count=count,
            )
        except ResponseError:
            return []
        # Mengambil bagian "claimed" dari tuple (next_cursor, claimed, deleted).
        claimed = res[1] if len(res) > 1 else []
        return self._normalize(claimed)

    async def ack(self, ids: List[str]) -> None:
        if ids:
            await self.r.xack(STREAM_KEY, GROUP, *ids)

    async def pending_count(self) -> int:
        """Menghitung entry yang sudah terkirim tetapi belum di-ACK (backlog)."""
        try:
            info = await self.r.xpending(STREAM_KEY, GROUP)
        except ResponseError:
            return 0
        # xpending summary -> {'pending': n, ...}
        if isinstance(info, dict):
            return int(info.get("pending", 0) or 0)
        return int(info[0] or 0) if info else 0

    async def stream_len(self) -> int:
        try:
            return int(await self.r.xlen(STREAM_KEY))
        except ResponseError:
            return 0

    @staticmethod
    def _flatten(res: Any) -> List[Tuple[str, Dict[str, Any]]]:
        out: List[Tuple[str, Dict[str, Any]]] = []
        if not res:
            return out
        for _stream, entries in res:
            out.extend(Broker._normalize(entries))
        return out

    @staticmethod
    def _normalize(entries: Any) -> List[Tuple[str, Dict[str, Any]]]:
        out: List[Tuple[str, Dict[str, Any]]] = []
        for msg_id, fields in entries or []:
            if fields is None:  # entry sudah terhapus dari stream
                continue
            try:
                ev = json.loads(fields["data"])
            except (KeyError, json.JSONDecodeError):
                continue
            out.append((msg_id, ev))
        return out


broker = Broker()
