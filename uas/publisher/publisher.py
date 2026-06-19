"""Publisher: generator/simulator event dengan duplikasi.
"""
from __future__ import annotations

import asyncio
import os
import random
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

import httpx

TARGET_URL = os.getenv("TARGET_URL", "http://aggregator:8080/publish")
READY_URL = os.getenv("READY_URL", TARGET_URL.replace("/publish", "/readyz"))
NUM_EVENTS = int(os.getenv("NUM_EVENTS", "20000"))
DUP_RATIO = float(os.getenv("DUP_RATIO", "0.45"))
TOPICS = [t.strip() for t in os.getenv("TOPICS", "app.logs,sys.metrics,audit").split(",")]
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "200"))
CONCURRENCY = int(os.getenv("CONCURRENCY", "16"))
SOURCE = os.getenv("SOURCE", f"publisher-{uuid.uuid4().hex[:6]}")


def make_event(seq: int) -> Dict[str, Any]:
    topic = random.choice(TOPICS)
    return {
        "topic": topic,
        "event_id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": SOURCE,
        "payload": {"seq": seq, "level": random.choice(["INFO", "WARN", "ERROR"]), "msg": f"log line {seq}"},
    }


def build_dataset() -> List[Dict[str, Any]]:
    """Membangun daftar event: NUM_EVENTS unik + DUP_RATIO duplikat (event sama
    dikirim ulang), lalu mengacaknya agar duplikat tersebar (out-of-order)."""
    uniques = [make_event(i) for i in range(NUM_EVENTS)]
    num_dup = int(NUM_EVENTS * DUP_RATIO)
    dups = [dict(random.choice(uniques)) for _ in range(num_dup)]
    dataset = uniques + dups
    random.shuffle(dataset)
    return dataset


def chunk(items: List[Dict[str, Any]], size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


async def wait_ready(client: httpx.AsyncClient, timeout: float = 120.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = await client.get(READY_URL, timeout=3.0)
            if r.status_code == 200:
                print(f"[publisher] aggregator siap: {READY_URL}", flush=True)
                return
        except Exception:
            pass
        await asyncio.sleep(1.0)
    raise RuntimeError("aggregator tidak kunjung siap")


async def send_batches(batches: List[List[Dict[str, Any]]]) -> Dict[str, int]:
    sem = asyncio.Semaphore(CONCURRENCY)
    sent = {"accepted": 0, "requests": 0, "errors": 0}
    async with httpx.AsyncClient(timeout=30.0) as client:
        await wait_ready(client)

        async def one(batch: List[Dict[str, Any]]):
            async with sem:
                for attempt in range(5):  # retry + backoff (Bab 6)
                    try:
                        r = await client.post(TARGET_URL, json=batch)
                        if r.status_code == 200:
                            sent["accepted"] += r.json().get("accepted", 0)
                            sent["requests"] += 1
                            return
                        else:
                            print(f"[publisher] status {r.status_code}: {r.text[:120]}", flush=True)
                    except Exception as e:  # noqa: BLE001
                        if attempt == 4:
                            sent["errors"] += 1
                            print(f"[publisher] gagal kirim batch: {e}", flush=True)
                            return
                    await asyncio.sleep(0.2 * (2 ** attempt))

        await asyncio.gather(*(one(b) for b in batches))
    return sent


async def main() -> None:
    print(
        f"[publisher] target={TARGET_URL} unik={NUM_EVENTS} dup_ratio={DUP_RATIO} "
        f"batch={BATCH_SIZE} concurrency={CONCURRENCY}",
        flush=True,
    )
    dataset = build_dataset()
    total = len(dataset)
    batches = list(chunk(dataset, BATCH_SIZE))
    t0 = time.time()
    result = await send_batches(batches)
    dt = time.time() - t0
    thr = total / dt if dt > 0 else 0
    print(
        f"[publisher] SELESAI total_dikirim={total} accepted={result['accepted']} "
        f"requests={result['requests']} errors={result['errors']} "
        f"durasi={dt:.2f}s throughput={thr:.0f} ev/s "
        f"(unik={NUM_EVENTS} duplikat={total - NUM_EVENTS})",
        flush=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
