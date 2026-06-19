# Pub-Sub Log Aggregator Terdistribusi

Sistem **publish–subscribe log aggregator** multi-service berbasis Docker
Compose yang menjamin **idempotency**, **deduplication kuat**, dan
**transaksi/kontrol konkurensi** untuk mencegah race condition.

Mata kuliah: Sistem Paralel dan Terdistribusi — UAS.
Cakupan teori: Bab 1–13 (DISTRIBUTED SYSTEMS: Concepts and Design, 5th ed.),
penekanan **Bab 8–9 (Transactions & Concurrency Control)**.

---

## 1. Arsitektur

```
                 POST /publish (single/batch)
   publisher  ─────────────────────────────▶  aggregator (FastAPI)
  (simulator,                                    │  incr received
   30% duplikat)                                 │  XADD ke stream
                                                 ▼
                                       broker: Redis Streams
                                       (consumer group "aggregators")
                                                 │  XREADGROUP ">"
                          ┌──────────────────────┼──────────────────────┐
                          ▼                      ▼                      ▼
                      worker-0               worker-1   ...          worker-N
                          └──────────────────────┼──────────────────────┘
                              process_event() dalam 1 transaksi:
                              INSERT ... ON CONFLICT DO NOTHING
                                                 ▼
                                       storage: PostgreSQL 16
                                       (UNIQUE(topic,event_id) = dedup)
```

| Service | Image | Peran |
|---|---|---|
| `aggregator` | build `./aggregator` (python:3.11-slim) | API `/publish`, `/events`, `/stats`, `/healthz`, `/readyz` + consumer workers internal |
| `publisher` | build `./publisher` | Simulator ≥ 20.000 event dengan ≥ 30% duplikat |
| `broker` | `redis:7-alpine` | Message broker (Redis Streams + consumer group) |
| `storage` | `postgres:16-alpine` | Dedup store persisten (UNIQUE constraint) |

**Mengapa Redis Streams + Postgres?** Broker memberi *at-least-once delivery*
(pesan menggantung di Pending Entries List bila worker crash, lalu di-claim
ulang). Postgres dengan `UNIQUE(topic, event_id)` + `ON CONFLICT DO NOTHING`
memberi idempotency. Kombinasi keduanya menghasilkan **efek exactly-once
processing**.

---

## 2. Cara Menjalankan

```bash
# Build & jalankan semua service (termasuk publisher yang langsung membanjiri
# aggregator dengan 20.000 event + 30% duplikat lalu berhenti).
docker compose up --build

# Atau jalankan inti dulu, publisher menyusul:
docker compose up -d --build storage broker aggregator
docker compose up publisher        # jalankan simulator beban
```

Akses aggregator di host: **http://localhost:8090**

```bash
curl http://localhost:8090/healthz
curl http://localhost:8090/stats
curl "http://localhost:8090/events?topic=app.logs&limit=10"
```

Konfigurasi publisher (override di `docker-compose.yml` atau `-e`):
`NUM_EVENTS`, `DUP_RATIO`, `BATCH_SIZE`, `CONCURRENCY`.

---

## 3. Model Event & API

Event JSON:
```json
{
  "topic": "app.logs",
  "event_id": "b1c2...-uuid4",
  "timestamp": "2026-06-17T10:00:00+00:00",
  "source": "publisher-ab12cd",
  "payload": { "level": "INFO", "msg": "..." }
}
```

| Endpoint | Keterangan |
|---|---|
| `POST /publish` | Terima **single** event atau **batch** (list). Validasi skema; batch all-or-nothing pada validasi. Mengembalikan `{accepted, rejected, detail}`. |
| `GET /events?topic=&limit=` | Daftar **event unik** yang sudah diproses, urut `seq` (monotonik). |
| `GET /stats` | `received`, `unique_processed`, `duplicate_dropped`, `topics`, `uptime_seconds`, `queue_depth`. |
| `GET /healthz` | Liveness probe. |
| `GET /readyz` | Readiness (DB + broker siap), 503 bila belum. |

---

## 4. Idempotency, Dedup & Transaksi (Bab 8–9)

- **Dedup store persisten:** tabel `processed_events` dengan
  `CONSTRAINT uq_topic_event UNIQUE (topic, event_id)`.
- **Idempotent write:** setiap event diproses dalam **satu transaksi**:
  ```sql
  INSERT INTO processed_events (...) VALUES (...)
  ON CONFLICT (topic, event_id) DO NOTHING
  RETURNING seq;
  ```
  Bila baris baru ter-insert → `unique_processed += 1`; bila konflik →
  `duplicate_dropped += 1`. Atomik di level row, sehingga **dua worker paralel
  tidak pernah double-process** event yang sama.
- **Statistik bebas lost-update:** `UPDATE aggregator_stats SET value = value + 1`
  di dalam transaksi yang sama (bukan read-modify-write di aplikasi).
- **Isolation level:** **READ COMMITTED** (default Postgres). Korektnya
  idempotency dijamin oleh UNIQUE constraint + `ON CONFLICT`, bukan oleh
  isolation level, sehingga tidak perlu SERIALIZABLE (menghindari overhead &
  serialization failure). Lihat `report.md` untuk analisis trade-off
  (phantom read, write skew) dan mitigasinya.

---

## 5. Reliability & Ordering

- **At-least-once:** publisher mengirim duplikat + retry exponential backoff;
  broker menyimpan PEL untuk pesan belum di-ACK.
- **Crash tolerance:** worker melakukan `XAUTOCLAIM` atas pesan idle milik
  consumer mati → diproses ulang; dedup store mencegah efek ganda. Setelah
  `docker compose restart`/recreate aggregator, data di Postgres tetap utuh.
- **Ordering:** total ordering global **tidak** diperlukan untuk korektnya
  dedup. Tersedia *monotonic counter* `seq` (BIGSERIAL) untuk ordering praktis
  per-topic dan toleransi event out-of-order (lihat `report.md`, Bab 5).

---

## 6. Persistensi (data aman meski container dihapus)

Named volumes: `pg_data` (data Postgres) dan `broker_data` (AOF Redis).

```bash
# Bukti persistensi:
docker compose up -d
# ... kirim event ...
docker compose rm -sf aggregator storage    # hapus container (BUKAN volume)
docker compose up -d                          # recreate
curl http://localhost:8090/stats              # data tetap ada
```
Hapus total termasuk data: `docker compose down -v`.

---

## 7. Pengujian (20 tests)

```bash
# Pastikan stack berjalan lebih dulu (integration test menyasar localhost:8090).
docker compose up -d --build storage broker aggregator

python -m venv .venv && . .venv/Scripts/activate    # Windows: .venv\Scripts\activate
pip install -r tests/requirements.txt
pytest -v                # atau: BASE_URL=http://localhost:8090 pytest -v
```

Cakupan: validasi skema (unit), dedup, batch dengan duplikat, filter `/events`,
ordering `seq`, konkurensi multi-thread (no double-process), konsistensi stats
(no lost-update), health/ready, validasi batch, idempotency lintas resend,
stress kecil. Unit test skema berjalan tanpa Docker; integration test otomatis
**skip** bila aggregator tidak terjangkau.

### Load test (k6)
```bash
k6 run -e BASE_URL=http://localhost:8090 k6/load_test.js
```

---

## 8. Keamanan Jaringan

Semua service berada di network bridge internal `appnet`. Hanya `aggregator`
yang meng-expose port ke host (host `8090` → container `8080`, untuk demo). `storage` dan `broker` **tidak**
punya `ports:` → tidak dapat diakses dari luar Compose. Tidak ada dependensi ke
layanan eksternal publik. Image aplikasi berjalan sebagai **non-root user**.

---

## 9. Struktur Repo

```
uas/
├── aggregator/         # API + consumer workers + Dockerfile
│   └── app/{main,db,broker,consumer,schemas}.py
├── publisher/          # simulator event + Dockerfile
├── storage/init.sql    # skema DB (dedup, stats, audit)
├── tests/              # 20 unit/integration tests
├── k6/load_test.js     # load test
├── docker-compose.yml
├── README.md
└── report.md           # laporan teori Bab 1-13 + metrik
```
