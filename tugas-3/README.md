# Distributed Sync System

Sistem sinkronisasi terdistribusi yang mensimulasikan skenario real-world
dari distributed systems. Menangani multiple nodes yang berkomunikasi
dan mensinkronisasi data secara konsisten.

> Tugas Sistem Paralel dan Terdistribusi


## Komponen Inti

| Komponen | Algoritma | File Utama |
|----------|-----------|------------|
| Distributed Lock Manager | Raft + Wait-For-Graph deadlock detection | `src/nodes/lock_manager.py` |
| Distributed Queue        | Consistent hashing + replikasi + persistent log | `src/nodes/queue_node.py` |
| Distributed Cache        | MESI coherence + LRU/LFU eviction | `src/nodes/cache_node.py` |
| Consensus                | Raft (utama) + PBFT (bonus) | `src/consensus/` |
| Komunikasi               | Async message bus + Phi Accrual failure detector | `src/communication/` |

## Quick Start

```bash
cd distributed-sync-system
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 1) Demo end-to-end (3 node in-process)
python demo.py

# 2) Single node HTTP server
cp .env.example .env
python -m src

# 3) Cluster via Docker Compose
docker compose -f docker/docker-compose.yml up --build
```

## Struktur Proyek

```
distributed-sync-system/
├── src/
│   ├── nodes/
│   │   ├── base_node.py
│   │   ├── lock_manager.py
│   │   ├── queue_node.py
│   │   └── cache_node.py
│   ├── consensus/
│   │   ├── raft.py
│   │   └── pbft.py             (bonus)
│   ├── communication/
│   │   ├── message_passing.py
│   │   └── failure_detector.py
│   ├── utils/
│   │   ├── config.py
│   │   └── metrics.py
│   ├── server.py               (HTTP API)
│   ├── cluster.py              (in-process multi-node)
│   └── __main__.py
├── tests/
│   ├── unit/
│   ├── integration/
│   └── performance/
├── docker/
│   ├── Dockerfile.node
│   └── docker-compose.yml
├── docs/
│   ├── architecture.md
│   ├── algorithms.md
│   ├── api_spec.yaml
│   ├── deployment_guide.md
│   └── performance_report.md
├── benchmarks/
│   ├── load_test_scenarios.py  (locust)
│   ├── run_benchmarks.py
│   └── plot_results.py
├── requirements.txt
├── pytest.ini
├── .env.example
├── demo.py
└── README.md
```

## API Endpoints (per node)

| Method | Path | Deskripsi |
|--------|------|-----------|
| GET    | `/health`                              | Status node + Raft |
| GET    | `/metrics`                             | Snapshot metrik |
| GET    | `/state`                               | State penuh (Raft, queue, cache, locks) |
| POST   | `/locks/acquire`                       | Acquire lock (shared/exclusive) |
| POST   | `/locks/release`                       | Release lock |
| GET    | `/locks`                               | Lock table |
| POST   | `/queues/{queue}/messages`             | Enqueue |
| GET    | `/queues/{queue}/messages`             | Dequeue |
| POST   | `/queues/messages/{msg_id}/ack`        | Acknowledge |
| GET    | `/queues/stats`                        | Statistik queue |
| GET    | `/cache/{key}`                         | Get value |
| PUT    | `/cache/{key}`                         | Put value |
| DELETE | `/cache/{key}`                         | Delete |
| GET    | `/cache/stats/all`                     | Statistik cache |

Spesifikasi penuh: [`docs/api_spec.yaml`](docs/api_spec.yaml).

## Tests

```bash
pytest tests/unit -v             # ~1s
pytest tests/integration -v      # ~30s, spawn cluster
pytest tests/performance -s      # cetak throughput
pytest -v                        # semua
```

## Benchmark

```bash
# In-process throughput/latency
python benchmarks/run_benchmarks.py

# HTTP load testing (Locust)
locust -f benchmarks/load_test_scenarios.py \
       --host=http://localhost:8001 \
       --users 50 --spawn-rate 5 --run-time 2m \
       --headless --csv=benchmarks/results/run1
```

Hasil dilaporkan di [`docs/performance_report.md`](docs/performance_report.md).
Laporan akhir PDF tersedia di [`report.pdf`](report.pdf).

## Fitur Bonus

- **PBFT (Byzantine Fault Tolerance)** di [`src/consensus/pbft.py`](src/consensus/pbft.py) —
  toleransi terhadap `f = (n-1)/3` node malicious; ada mode `set_byzantine(True)` untuk demo.

## Demonstrasi Video

Link YouTube: https://youtu.be/MAaFyo-ya0I
