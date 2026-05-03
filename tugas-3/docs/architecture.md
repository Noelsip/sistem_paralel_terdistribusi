# Arsitektur Sistem Sinkronisasi Terdistribusi

## 1. Gambaran Umum

Sistem ini mensimulasikan tiga fitur fundamental dari distributed systems:

1. **Distributed Lock Manager** — koordinasi akses resource lewat Raft.
2. **Distributed Queue** — antrian pesan tahan-fault dengan consistent hashing.
3. **Distributed Cache** — cache coherence MESI antar node.

Semua tiga komponen berjalan pada setiap node, sehingga setiap node setara
secara fungsi (tidak ada single-point-of-failure design).

## 2. Topologi

```
                ┌─────────────────────────────────────────────┐
                │              Client / Load Test             │
                └──────────────┬───────────────┬──────────────┘
                               │               │
                       HTTP REST API (aiohttp)
                               │               │
        ┌──────────────────────┼───────────────┼──────────────────────┐
        │                      │               │                      │
   ┌────▼────┐            ┌────▼────┐     ┌────▼────┐
   │ Node 1  │◄──Raft────►│ Node 2  │◄────│ Node 3  │
   │         │            │         │     │         │
   │ ┌─────┐ │            │ ┌─────┐ │     │ ┌─────┐ │
   │ │Lock │ │  Message   │ │Lock │ │     │ │Lock │ │
   │ ├─────┤ │  Bus       │ ├─────┤ │     │ ├─────┤ │
   │ │Queue│ │            │ │Queue│ │     │ │Queue│ │
   │ ├─────┤ │            │ ├─────┤ │     │ ├─────┤ │
   │ │Cache│ │            │ │Cache│ │     │ │Cache│ │
   │ └─────┘ │            │ └─────┘ │     │ └─────┘ │
   └─────────┘            └─────────┘     └─────────┘
        │                      │               │
        └──── Failure Detector (Phi Accrual) ──┘
```

## 3. Lapisan Komunikasi

### Message Bus
- `src/communication/message_passing.py` — implementasi bus pesan in-process
  (untuk demo single-process) dengan API yang setara dengan transport
  jaringan. Mendukung:
  - `send(message)` — unicast dengan routing per `receiver_id`
  - `broadcast(message)` — multicast ke semua peer
  - `partition_nodes(...)` — simulasi network partition
  - `dispatch_messages(node_id)` — loop dispatch ke handler terdaftar

### Failure Detector
- `src/communication/failure_detector.py` — implementasi **Phi Accrual**
  Failure Detector (Cassandra). Menghitung distribusi interval heartbeat
  per peer dan menerbitkan suspicion level `phi`. Threshold default 8.0
  → DEAD; antara 8.0–16.0 → SUSPECTED.

## 4. Distributed Lock Manager

### Algoritma: Raft Consensus
- Implementasi `src/consensus/raft.py`.
- State machine: `FOLLOWER → CANDIDATE → LEADER`.
- Election dengan **randomised timeout** (150–300 ms) untuk hindari
  split-vote.
- **Log replication** via `AppendEntries` — leader commit hanya jika
  mayoritas (quorum) follower mengakui entry.
- **Safety properties** Raft yang dijaga:
  - Election Safety
  - Leader Append-Only
  - Log Matching
  - Leader Completeness
  - State Machine Safety

### Mode Lock
- **Shared (read)**: kompatibel dengan shared lain. Diblokir oleh exclusive.
- **Exclusive (write)**: tidak kompatibel dengan apa pun.

### Deadlock Detection
- **Wait-For-Graph (WFG)** dengan DFS cycle-detection.
- Dijalankan periodik (2 detik) di leader.
- Korban: transaksi termuda (`youngest-wait-die` policy) — di-abort agar
  cycle pecah.

### Network Partition
- Sisi minoritas tidak dapat mencapai quorum → tidak dapat memberikan lock.
- Sisi mayoritas memilih leader baru dan terus melayani lock.
- Saat partition healed, node yang tertinggal akan menerima `AppendEntries`
  dari leader yang baru dan men-catch-up.

## 5. Distributed Queue

### Consistent Hashing
- Ring dengan **150 virtual nodes per fisik** (default) untuk distribusi
  yang seimbang.
- Hash MD5 atas `partition_key`.
- `get_n_nodes(key, n)` mengembalikan primary + (n-1) replica fisik
  yang berbeda.

### Replikasi & Durability
- **Replication factor = 2** (primary + 1 replica).
- Append-only **persistent log** per node (`fsync` setiap append).
- Saat restart, log diputar ulang untuk merekonstruksi state.
- Jika `REDIS_ENABLED=true`, setiap append log queue juga di-mirror ke Redis
  dengan key `distsync:queue-log:<node_id>` sebagai distributed state eksternal.

### At-least-once Delivery
- Setelah dequeue, pesan masuk ke `inflight` dengan **visibility timeout**
  (30 detik default).
- Jika consumer tidak `ACK` sebelum timeout → pesan dikembalikan ke queue
  dan delivery_count bertambah.
- Saat ACK, replica di node lain juga dihapus.

### Penanganan Node Failure
- Failure detector memicu `_on_peer_failure(peer_id)`.
- Replica yang menyimpan `primary_node == peer_id` dipromosikan menjadi
  primary lokal — pesan tidak hilang.

## 6. Cache Coherence (MESI)

### State Machine
| Dari\Aksi | Local Read | Local Write | Bus Read | Bus Write/Inv |
|-----------|-----------|-------------|----------|---------------|
| **M**     | M         | M           | S        | I             |
| **E**     | E         | M           | S        | I             |
| **S**     | S         | M (BusRdX)  | S        | I             |
| **I**     | E/S       | M           | -        | -             |

### Protokol
- **BusRd**: cache miss → broadcast `CACHE_FETCH`. Peer yang punya line
  merespons (M/E → S setelah respons; S tetap S).
- **BusRdX**: write → broadcast `CACHE_INVALIDATE`. Semua peer mark line
  sebagai I (lalu evict jika bukan M).
- **Writeback**: line M yang dievakuasi diloggingkan sebagai writeback.

### Eviction
- **LRU** (default) atau **LFU**, dipilih lewat env `CACHE_EVICTION`.
- Saat capacity penuh, `_ensure_capacity` mengevakuasi sampai size < max.

## 7. Containerization

- `docker/Dockerfile.node` — image dasar Python 3.11-slim, runs
  `python -m src` (HTTP server pada port `NODE_PORT`).
- `docker/docker-compose.yml` — orchestration 3 node + Redis.
- Konfigurasi via environment variables (`.env.example`).

## 8. Observability

- `/health` endpoint per node — status Raft + peer health.
- `/metrics` — counter/gauge/histogram (cache hit ratio, queue throughput,
  Raft term/leader).
- Histogram laten p95/p99 dihitung in-process tanpa dependensi eksternal.
