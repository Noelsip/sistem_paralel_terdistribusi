"""Integration test: transaksi & kontrol konkurensi (Bab 8-9).

Membuktikan bahwa di bawah beban paralel tetap tidak ada double-process
dan statistik bebas lost-update.
"""
import concurrent.futures as cf

import httpx
from conftest import BASE_URL, make_event, requires_stack, wait_processed


def _post(ev):
    with httpx.Client(base_url=BASE_URL, timeout=30.0) as c:
        return c.post("/publish", json=ev).status_code


@requires_stack
def test_concurrent_duplicates_no_double_process(client, topic):
    # 1 event logis dikirim 50x secara paralel dari banyak koneksi.
    ev = make_event(topic, event_id="race-1")
    with cf.ThreadPoolExecutor(max_workers=20) as ex:
        results = list(ex.map(lambda _: _post(ev), range(50)))
    assert all(s == 200 for s in results)
    n = wait_processed(client, topic, expected_unique=1)
    assert n == 1, "race condition: event tunggal harus hanya 1 row"


@requires_stack
def test_concurrent_mixed_unique_and_dup(client, topic):
    # 30 event unik, masing-masing dikirim 3x, paralel -> harus 30 unik.
    events = [make_event(topic, event_id=f"u{i}", seq=i) for i in range(30)]
    payloads = []
    for ev in events:
        payloads += [ev, ev, ev]
    with cf.ThreadPoolExecutor(max_workers=20) as ex:
        list(ex.map(_post, payloads))
    n = wait_processed(client, topic, expected_unique=30, timeout=30)
    assert n == 30


@requires_stack
def test_stats_consistency_no_lost_update(client):
    import time
    deadline = time.time() + 30
    s = client.get("/stats").json()
    while time.time() < deadline and s["queue_depth"] > 0:
        time.sleep(0.3)
        s = client.get("/stats").json()
    assert s["received"] == s["unique_processed"] + s["duplicate_dropped"], (
        f"lost-update terdeteksi: {s}"
    )
