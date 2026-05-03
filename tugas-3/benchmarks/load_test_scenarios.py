"""
Locust load test scenarios.

Run:
    locust -f benchmarks/load_test_scenarios.py \
           --host=http://localhost:8001 \
           --users 50 --spawn-rate 5 \
           --run-time 2m --headless --csv=benchmarks/results/run1
"""

import json
import random
import uuid

from locust import HttpUser, between, task


class DistSyncUser(HttpUser):
    wait_time = between(0.1, 0.5)

    def on_start(self):
        self.client_id = f"client-{uuid.uuid4().hex[:8]}"

    @task(5)
    def cache_get(self):
        key = f"hot-{random.randint(0, 99)}"
        self.client.get(f"/cache/{key}", name="/cache/[key]")

    @task(2)
    def cache_put(self):
        key = f"hot-{random.randint(0, 99)}"
        self.client.put(
            f"/cache/{key}",
            json={"value": {"ts": random.random(), "data": "x" * 64}},
            name="/cache/[key]",
        )

    @task(2)
    def queue_enqueue(self):
        self.client.post(
            "/queues/orders/messages",
            json={
                "payload": {"id": str(uuid.uuid4()), "amount": random.randint(1, 1000)}
            },
            name="/queues/[name]/messages",
        )

    @task(1)
    def queue_dequeue(self):
        with self.client.get(
            "/queues/orders/messages",
            name="/queues/[name]/messages [GET]",
            catch_response=True,
        ) as response:
            try:
                data = response.json()
                if data.get("message"):
                    msg_id = data["message"]["msg_id"]
                    self.client.post(
                        f"/queues/messages/{msg_id}/ack",
                        name="/queues/messages/[id]/ack",
                    )
            except (ValueError, KeyError):
                pass

    @task(1)
    def lock_cycle(self):
        resource = f"resource-{random.randint(0, 19)}"
        self.client.post(
            "/locks/acquire",
            json={
                "client_id": self.client_id,
                "resource": resource,
                "mode": "exclusive",
                "timeout": 1.0,
            },
            name="/locks/acquire",
        )
        self.client.post(
            "/locks/release",
            json={"client_id": self.client_id, "resource": resource},
            name="/locks/release",
        )
