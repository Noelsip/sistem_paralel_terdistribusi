import argparse
import random
import time
from datetime import UTC, datetime

import httpx


def build_events(total: int, duplicate_ratio: float, topic: str, source: str) -> list[dict]:
    unique_count = max(1, int(total * (1 - duplicate_ratio)))
    base_ids = [f"evt-{i:06d}" for i in range(unique_count)]
    events: list[dict] = []

    for i in range(total):
        if i < unique_count:
            event_id = base_ids[i]
        else:
            event_id = random.choice(base_ids)
        events.append(
            {
                "topic": topic,
                "event_id": event_id,
                "timestamp": datetime.now(UTC).isoformat(),
                "source": source,
                "payload": {"index": i, "message": "simulated-log"},
            }
        )
    random.shuffle(events)
    return events


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8080/publish")
    parser.add_argument("--total", type=int, default=5000)
    parser.add_argument("--duplicate-ratio", type=float, default=0.2)
    parser.add_argument("--topic", default="app.logs")
    parser.add_argument("--source", default="publisher-simulator")
    parser.add_argument("--batch-size", type=int, default=500)
    args = parser.parse_args()

    events = build_events(
        total=args.total,
        duplicate_ratio=args.duplicate_ratio,
        topic=args.topic,
        source=args.source,
    )

    start = time.perf_counter()
    with httpx.Client(timeout=30.0) as client:
        for i in range(0, len(events), args.batch_size):
            chunk = events[i : i + args.batch_size]
            resp = client.post(args.url, json=chunk)
            resp.raise_for_status()

    elapsed = time.perf_counter() - start
    print(f"Sent {len(events)} events in {elapsed:.3f}s")


if __name__ == "__main__":
    main()
