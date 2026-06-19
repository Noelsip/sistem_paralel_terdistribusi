"""Integration test: idempotency & deduplication."""
from conftest import make_event, requires_stack, wait_processed


@requires_stack
def test_duplicate_processed_once(client, topic):
    ev = make_event(topic, event_id="dup-1")
    # Kirim event yang sama 5 kali.
    for _ in range(5):
        r = client.post("/publish", json=ev)
        assert r.status_code == 200
    n = wait_processed(client, topic, expected_unique=1)
    assert n == 1, "event duplikat harus diproses tepat sekali"


@requires_stack
def test_batch_with_internal_duplicates(client, topic):
    e1 = make_event(topic, event_id="a")
    e2 = make_event(topic, event_id="b")
    batch = [e1, e2, dict(e1), dict(e2), dict(e1)]
    r = client.post("/publish", json=batch)
    assert r.status_code == 200
    assert r.json()["accepted"] == 5
    n = wait_processed(client, topic, expected_unique=2)
    assert n == 2


@requires_stack
def test_events_endpoint_returns_unique_only(client, topic):
    for i in range(3):
        client.post("/publish", json=make_event(topic, event_id=f"e{i}", seq=i))
    # kirim ulang semuanya
    for i in range(3):
        client.post("/publish", json=make_event(topic, event_id=f"e{i}", seq=i))
    n = wait_processed(client, topic, expected_unique=3)
    assert n == 3
    rows = client.get("/events", params={"topic": topic}).json()
    ids = sorted(r["event_id"] for r in rows)
    assert ids == ["e0", "e1", "e2"]


@requires_stack
def test_events_filter_by_topic(client, topic):
    other = topic + ".other"
    client.post("/publish", json=make_event(topic, event_id="x"))
    client.post("/publish", json=make_event(other, event_id="y"))
    wait_processed(client, topic, expected_unique=1)
    rows = client.get("/events", params={"topic": topic}).json()
    assert all(r["topic"] == topic for r in rows)
    assert any(r["event_id"] == "x" for r in rows)

@requires_stack
def test_events_ordered_by_seq(client, topic):
    for i in range(5):
        client.post("/publish", json=make_event(topic, event_id=f"o{i}", seq=i))
    wait_processed(client, topic, expected_unique=5)
    rows = client.get("/events", params={"topic": topic}).json()
    seqs = [r["seq"] for r in rows]
    assert seqs == sorted(seqs), "seq harus monotonik naik (Bab 5: ordering)"
