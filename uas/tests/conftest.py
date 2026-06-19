from __future__ import annotations

import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "aggregator"))

BASE_URL = os.getenv("BASE_URL", "http://localhost:8090")


def _aggregator_up() -> bool:
    try:
        r = httpx.get(f"{BASE_URL}/readyz", timeout=2.0)
        return r.status_code == 200
    except Exception:
        return False


requires_stack = pytest.mark.skipif(
    not _aggregator_up(),
    reason=f"aggregator tidak berjalan di {BASE_URL} (jalankan: docker compose up)",
)

@pytest.fixture()
def client():
    with httpx.Client(base_url=BASE_URL, timeout=30.0) as c:
        yield c

@pytest.fixture()
def topic():
    """Topic unik per test agar test saling terisolasi pada DB persisten."""
    return f"test.{uuid.uuid4().hex[:12]}"


def make_event(topic: str, event_id: str | None = None, seq: int = 0) -> dict:
    return {
        "topic": topic,
        "event_id": event_id or str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "pytest",
        "payload": {"seq": seq, "msg": f"line {seq}"},
    }


def wait_processed(client: httpx.Client, topic: str, expected_unique: int, timeout: float = 20.0) -> int:
    """Polling /events sampai jumlah event unik untuk topic mencapai target."""
    deadline = time.time() + timeout
    n = 0
    while time.time() < deadline:
        r = client.get("/events", params={"topic": topic, "limit": 100000})
        n = len(r.json())
        if n >= expected_unique:
            return n
        time.sleep(0.2)
    return n
