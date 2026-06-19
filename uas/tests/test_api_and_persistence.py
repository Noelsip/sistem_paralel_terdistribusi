"""Integration test: endpoint API, observability, dan persistensi."""
import time

from conftest import make_event, requires_stack, wait_processed


@requires_stack
def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "alive"


@requires_stack
def test_readyz(client):
    r = client.get("/readyz")
    assert r.status_code == 200
    assert r.json()["status"] == "ready"


@requires_stack
def test_stats_has_all_fields(client):
    s = client.get("/stats").json()
    for field in [
        "received", "unique_processed", "duplicate_dropped",
        "topics", "uptime_seconds", "queue_depth",
    ]:
        assert field in s


@requires_stack
def test_publish_invalid_batch_rejected(client, topic):
    bad = [make_event(topic, event_id="ok"), {"topic": topic}]  # item ke-2 invalid
    r = client.post("/publish", json=bad)
    assert r.status_code == 422, "batch all-or-nothing pada validasi"


@requires_stack
def test_idempotent_across_resend_simulates_restart(client, topic):
    """Mengirim ulang event yang SAMA setelah jeda mensimulasikan publisher
    yang retry pasca-crash; dedup store mencegah pemrosesan ulang.
    (Uji recreate container sebenarnya didemokan manual di video.)"""
    ev = make_event(topic, event_id="persist-1")
    client.post("/publish", json=ev)
    wait_processed(client, topic, expected_unique=1)
    before = len(client.get("/events", params={"topic": topic}).json())
    # kirim ulang event identik
    for _ in range(3):
        client.post("/publish", json=ev)
    time.sleep(1.0)
    after = len(client.get("/events", params={"topic": topic}).json())
    assert before == after == 1


@requires_stack
def test_small_stress_batch_timing(client, topic):
    """Stress kecil: 1000 event (300 duplikat) dan ukur waktu."""
    uniques = [make_event(topic, event_id=f"s{i}", seq=i) for i in range(700)]
    dups = [uniques[i % 700] for i in range(300)]
    dataset = uniques + dups
    t0 = time.time()
    # kirim dalam batch 100
    for i in range(0, len(dataset), 100):
        r = client.post("/publish", json=dataset[i : i + 100])
        assert r.status_code == 200
    n = wait_processed(client, topic, expected_unique=700, timeout=60)
    dt = time.time() - t0
    assert n == 700
    print(f"\n[stress] 1000 event (700 unik) diproses dalam {dt:.2f}s")
