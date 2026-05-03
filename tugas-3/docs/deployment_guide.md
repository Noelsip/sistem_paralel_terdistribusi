# Deployment Guide

## Prasyarat

- Python 3.10+ (3.11 direkomendasikan)
- Docker 20.10+ dan Docker Compose v2
- Redis untuk mirror distributed queue state saat menjalankan Docker Compose

## Quick Start (In-process Demo)

Cara tercepat memverifikasi sistem berjalan:

```bash
cd distributed-sync-system
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python demo.py
```

Demo akan:
1. Spawn 3 node Raft in-process.
2. Jalankan election leader.
3. Demo lock shared/exclusive.
4. Demo enqueue/dequeue/ack queue.
5. Demo cache coherence MESI.
6. Demo network partition.

## Menjalankan via Docker Compose

```bash
cd distributed-sync-system
cp .env.example .env
docker compose -f docker/docker-compose.yml up --build
```

Akses:
- Node 1: http://localhost:8001/health
- Node 2: http://localhost:8002/health
- Node 3: http://localhost:8003/health

Verifikasi kluster sehat:

```bash
curl http://localhost:8001/health | jq
curl http://localhost:8001/state  | jq
```

## Scaling Dinamis

Untuk menambah node baru tanpa restart:

```bash
docker compose -f docker/docker-compose.yml \
  up --scale node-extra=2 -d
```

> Catatan: dynamic Raft membership memerlukan joint-consensus reconfig
> entry. Implementasi saat ini mendukung scaling di queue dan cache
> tier. Untuk lock manager, restart dengan PEERS yang diperbarui.

## Konfigurasi via Environment

Semua parameter dapat di-override via env:

| Variable               | Default              | Deskripsi                          |
|------------------------|----------------------|------------------------------------|
| `NODE_ID`              | `node-1`             | Identitas unik node                |
| `NODE_PORT`            | `8000`               | Port HTTP                          |
| `PEERS`                | (kosong)             | Daftar peer dipisah koma           |
| `ELECTION_TIMEOUT_MIN` | `0.15`               | Min election timeout (detik)       |
| `HEARTBEAT_INTERVAL`   | `0.05`               | Heartbeat interval leader          |
| `REPLICATION_FACTOR`   | `2`                  | Queue replication factor           |
| `CACHE_MAX_SIZE`       | `1000`               | Max cache entries per node         |
| `CACHE_EVICTION`       | `LRU`                | LRU atau LFU                       |
| `REDIS_ENABLED`        | `false`              | Mirror append-only queue log ke Redis |
| `REDIS_HOST`           | `localhost`          | Host Redis                         |

## Menjalankan Tests

```bash
# Unit tests (cepat, no asyncio cluster)
pytest tests/unit -v

# Integration tests (spawn cluster)
pytest tests/integration -v

# Performance tests
pytest tests/performance -s

# Semua
pytest -v
```

## Load Testing

Locust load testing terhadap node yang sedang berjalan:

```bash
locust -f benchmarks/load_test_scenarios.py \
       --host=http://localhost:8001 \
       --users 50 --spawn-rate 5 \
       --run-time 2m --headless --csv=benchmarks/results/run1
```

## Troubleshooting

### Node tidak memilih leader
- Cek bahwa `PEERS` setiap node berisi node lain (bukan dirinya sendiri).
- Cek bahwa Docker network membolehkan komunikasi antar container.
- Lihat log untuk pesan `[node-X] -> CANDIDATE`. Jika split-vote berulang,
  naikkan `ELECTION_TIMEOUT_MAX`.

### Queue kehilangan pesan
- Pastikan `PERSISTENCE_PATH` writable dan punya cukup disk.
- Cek `replication_factor`; untuk node failure tunggal harus ≥ 2.

### Cache hit ratio rendah
- Periksa size cache (`CACHE_MAX_SIZE`); jika data set > capacity → banyak
  eviction.
- Banyak `invalidations` di metrics → write-heavy workload memang menurunkan
  hit ratio. Pertimbangkan partisi key atau write-back batching.

### Network partition tidak terdeteksi
- Phi Accrual butuh ≥ 5 sample heartbeat. Tunggu beberapa detik setelah
  startup.
- Naikkan `phi_threshold` (default 8.0) untuk lebih konservatif.
