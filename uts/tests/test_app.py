import os
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from src.main import create_app


def make_event(event_id: str, topic: str = "app.logs") -> dict:
    return {
        "topic": topic,
        "event_id": event_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "source": "pytest",
        "payload": {"message": "log"},
    }


def wait_processed(client: TestClient, expected_total: int, timeout: float = 5.0) -> dict:
    start = time.perf_counter()
    while time.perf_counter() - start < timeout:
        stats = client.get("/stats").json()
        done = stats["unique_processed"] + stats["duplicate_dropped"]
        if done >= expected_total and stats["queue_size"] == 0:
            return stats
        time.sleep(0.02)
    raise AssertionError("Worker belum menyelesaikan event sesuai timeout")


def new_client_with_db(db_path: Path) -> TestClient:
    os.environ["DEDUP_DB_PATH"] = str(db_path)
    return TestClient(create_app())


def test_publish_single_event(tmp_path: Path) -> None:
    with new_client_with_db(tmp_path / "dedup.db") as client:
        event = make_event("evt-1")
        resp = client.post("/publish", json=event)
        assert resp.status_code == 200
        wait_processed(client, expected_total=1)
        events_resp = client.get("/events")
        assert events_resp.json()["count"] == 1


def test_dedup_duplicate_event(tmp_path: Path) -> None:
    with new_client_with_db(tmp_path / "dedup.db") as client:
        event = make_event("evt-same")
        client.post("/publish", json=event)
        client.post("/publish", json=event)
        stats = wait_processed(client, expected_total=2)
        assert stats["unique_processed"] == 1
        assert stats["duplicate_dropped"] == 1


def test_publish_batch_with_duplicates(tmp_path: Path) -> None:
    with new_client_with_db(tmp_path / "dedup.db") as client:
        payload = [
            make_event("evt-a"),
            make_event("evt-b"),
            make_event("evt-a"),
            make_event("evt-c"),
            make_event("evt-c"),
        ]
        resp = client.post("/publish", json=payload)
        assert resp.status_code == 200
        stats = wait_processed(client, expected_total=len(payload))
        assert stats["unique_processed"] == 3
        assert stats["duplicate_dropped"] == 2


def test_invalid_schema_missing_topic(tmp_path: Path) -> None:
    with new_client_with_db(tmp_path / "dedup.db") as client:
        bad_event = make_event("evt-x")
        del bad_event["topic"]
        resp = client.post("/publish", json=bad_event)
        assert resp.status_code == 422


def test_invalid_schema_timestamp(tmp_path: Path) -> None:
    with new_client_with_db(tmp_path / "dedup.db") as client:
        bad_event = make_event("evt-y")
        bad_event["timestamp"] = "bukan-iso8601"
        resp = client.post("/publish", json=bad_event)
        assert resp.status_code == 422


def test_get_events_filter_topic(tmp_path: Path) -> None:
    with new_client_with_db(tmp_path / "dedup.db") as client:
        events = [
            make_event("evt-1", topic="topic.A"),
            make_event("evt-2", topic="topic.B"),
            make_event("evt-3", topic="topic.A"),
        ]
        client.post("/publish", json=events)
        wait_processed(client, expected_total=3)
        topic_a = client.get("/events", params={"topic": "topic.A"}).json()
        assert topic_a["count"] == 2
        assert all(e["topic"] == "topic.A" for e in topic_a["events"])


def test_dedup_persistent_after_restart(tmp_path: Path) -> None:
    db_path = tmp_path / "dedup.db"
    event = make_event("evt-restart")

    with new_client_with_db(db_path) as client1:
        client1.post("/publish", json=event)
        stats1 = wait_processed(client1, expected_total=1)
        assert stats1["unique_processed"] == 1

    with new_client_with_db(db_path) as client2:
        client2.post("/publish", json=event)
        stats2 = wait_processed(client2, expected_total=1)
        assert stats2["unique_processed"] == 0
        assert stats2["duplicate_dropped"] == 1
        events = client2.get("/events").json()
        assert events["count"] == 1


def test_small_stress_batch_runtime(tmp_path: Path) -> None:
    with new_client_with_db(tmp_path / f"dedup-{uuid.uuid4().hex}.db") as client:
        total = 1200
        unique_ids = [f"evt-{i:04d}" for i in range(900)]
        events: list[dict] = []
        for i in range(total):
            event_id = unique_ids[i] if i < len(unique_ids) else unique_ids[i % len(unique_ids)]
            events.append(make_event(event_id, topic="stress.topic"))

        start = time.perf_counter()
        resp = client.post("/publish", json=events)
        assert resp.status_code == 200
        stats = wait_processed(client, expected_total=total, timeout=12)
        elapsed = time.perf_counter() - start

        assert elapsed < 12
        assert stats["unique_processed"] == 900
        assert stats["duplicate_dropped"] == 300
