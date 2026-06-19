"""Lapisan akses Postgres (asyncpg) + logika transaksi inti."""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import asyncpg

def _coerce_ts(ts: Any) -> datetime:
    """Mengubah timestamp ISO8601 dari broker menjadi datetime agar asyncpg
    bisa meng-encode-nya ke kolom TIMESTAMPTZ."""
    if isinstance(ts, datetime):
        return ts
    return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))


DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://user:pass@storage:5432/db"
)


class Database:
    def __init__(self) -> None:
        self.pool: Optional[asyncpg.Pool] = None

    async def connect(self, retries: int = 30, delay: float = 1.0) -> None:
        import asyncio

        last_err: Optional[Exception] = None
        for _ in range(retries):
            try:
                self.pool = await asyncpg.create_pool(
                    dsn=DATABASE_URL, min_size=2, max_size=10
                )
                # Memastikan koneksi benar-benar hidup sebelum dianggap siap.
                async with self.pool.acquire() as con:
                    await con.execute("SELECT 1")
                return
            except Exception as e:  # noqa: BLE001
                last_err = e
                await asyncio.sleep(delay)
        raise RuntimeError(f"Gagal konek Postgres: {last_err}")

    async def close(self) -> None:
        if self.pool:
            await self.pool.close()

    async def incr_received(self, n: int = 1) -> None:
        async with self.pool.acquire() as con:
            await con.execute(
                "UPDATE aggregator_stats SET value = value + $1 WHERE metric='received'",
                n,
            )

    async def process_event(self, ev: Dict[str, Any], worker: str) -> bool:
        """Memproses satu event dalam satu transaksi atomik.

        Mengembalikan True bila event baru (unik), False bila duplikat.
        """
        async with self.pool.acquire() as con:
            async with con.transaction():
                row = await con.fetchrow(
                    """
                    INSERT INTO processed_events
                        (topic, event_id, event_ts, source, payload)
                    VALUES ($1, $2, $3, $4, $5::jsonb)
                    ON CONFLICT (topic, event_id) DO NOTHING
                    RETURNING seq
                    """,
                    ev["topic"],
                    ev["event_id"],
                    _coerce_ts(ev["timestamp"]),
                    ev["source"],
                    json.dumps(ev["payload"]),
                )
                is_new = row is not None
                metric = "unique_processed" if is_new else "duplicate_dropped"
                await con.execute(
                    "UPDATE aggregator_stats SET value = value + 1 WHERE metric=$1",
                    metric,
                )
                await con.execute(
                    """INSERT INTO audit_log (topic, event_id, action, worker)
                       VALUES ($1, $2, $3, $4)""",
                    ev["topic"],
                    ev["event_id"],
                    "processed" if is_new else "duplicate",
                    worker,
                )
        return is_new

    async def get_events(
        self, topic: Optional[str] = None, limit: int = 1000
    ) -> List[Dict[str, Any]]:
        async with self.pool.acquire() as con:
            if topic:
                rows = await con.fetch(
                    """SELECT topic, event_id, event_ts, source, payload, seq
                       FROM processed_events WHERE topic=$1
                       ORDER BY seq ASC LIMIT $2""",
                    topic,
                    limit,
                )
            else:
                rows = await con.fetch(
                    """SELECT topic, event_id, event_ts, source, payload, seq
                       FROM processed_events
                       ORDER BY seq ASC LIMIT $1""",
                    limit,
                )
        return [
            {
                "topic": r["topic"],
                "event_id": r["event_id"],
                "timestamp": r["event_ts"].isoformat(),
                "source": r["source"],
                "payload": json.loads(r["payload"]),
                "seq": r["seq"],
            }
            for r in rows
        ]

    async def get_stats(self) -> Dict[str, int]:
        async with self.pool.acquire() as con:
            rows = await con.fetch("SELECT metric, value FROM aggregator_stats")
            topics = await con.fetchval(
                "SELECT COUNT(DISTINCT topic) FROM processed_events"
            )
        stats = {r["metric"]: r["value"] for r in rows}
        stats["topics"] = int(topics or 0)
        return stats


db = Database()
