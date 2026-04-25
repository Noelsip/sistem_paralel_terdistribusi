import json
import sqlite3
from pathlib import Path
from threading import Lock

from src.models import Event


class DedupStore:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS processed_events (
                topic TEXT NOT NULL,
                event_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                source TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                processed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (topic, event_id)
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_processed_events_topic ON processed_events(topic)"
        )
        self._conn.commit()

    def add_if_new(self, event: Event) -> bool:
        payload_json = json.dumps(event.payload, separators=(",", ":"), ensure_ascii=False)
        with self._lock:
            cursor = self._conn.execute(
                """
                INSERT OR IGNORE INTO processed_events
                (topic, event_id, timestamp, source, payload_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    event.topic,
                    event.event_id,
                    event.timestamp.isoformat(),
                    event.source,
                    payload_json,
                ),
            )
            self._conn.commit()
            return cursor.rowcount == 1

    def list_events(self, topic: str | None = None) -> list[dict]:
        if topic:
            cursor = self._conn.execute(
                """
                SELECT topic, event_id, timestamp, source, payload_json, processed_at
                FROM processed_events
                WHERE topic = ?
                ORDER BY timestamp ASC, processed_at ASC
                """,
                (topic,),
            )
        else:
            cursor = self._conn.execute(
                """
                SELECT topic, event_id, timestamp, source, payload_json, processed_at
                FROM processed_events
                ORDER BY timestamp ASC, processed_at ASC
                """
            )

        rows = cursor.fetchall()
        events: list[dict] = []
        for row in rows:
            events.append(
                {
                    "topic": row[0],
                    "event_id": row[1],
                    "timestamp": row[2],
                    "source": row[3],
                    "payload": json.loads(row[4]),
                    "processed_at": row[5],
                }
            )
        return events

    def list_topics(self) -> list[str]:
        cursor = self._conn.execute(
            "SELECT DISTINCT topic FROM processed_events ORDER BY topic ASC"
        )
        return [row[0] for row in cursor.fetchall()]

    def close(self) -> None:
        with self._lock:
            self._conn.close()
