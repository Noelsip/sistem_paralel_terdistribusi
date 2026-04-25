# UTS Sistem Terdistribusi dan Paralel

## Pub-Sub Log Aggregator dengan Idempotent Consumer dan Deduplication

Repository ini berisi implementasi layanan log aggregator berbasis publish-subscribe dengan fokus pada reliability:

1. duplicate delivery tetap aman melalui idempotent consumer,
2. event duplikat didrop menggunakan deduplication,
3. dedup store persisten tetap efektif setelah container restart,
4. observability tersedia melalui endpoint stats dan health.

## Tujuan Demo yang Harus Terbukti

Video demo harus membuktikan hal berikut:

1. Aplikasi dapat di-build sebagai Docker image dan dijalankan sebagai container.
2. Sistem menerima event dan memprosesnya melalui pola publish-subscribe.
3. Event duplikat tidak diproses ulang.
4. Endpoint observability menunjukkan kondisi sistem sebelum dan sesudah duplikasi.
5. Setelah restart container, deduplication tetap efektif (persisten).

## Struktur Folder

```text
uts/
├── src/
├── tests/
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── README.md
└── report.md
```

## Spesifikasi Event

Format event JSON:

```json
{
  "topic": "string",
  "event_id": "string-unik",
  "timestamp": "ISO8601",
  "source": "string",
  "payload": {}
}
```

`POST /publish` menerima single event maupun batch array.

## Endpoint API

1. `POST /publish`
2. `GET /events?topic=...`
3. `GET /stats`
4. `GET /health`

Contoh publish event:

```bash
curl -X POST http://localhost:8080/publish \
  -H "Content-Type: application/json" \
  -d '{
    "topic": "app.logs",
    "event_id": "evt-001",
    "timestamp": "2026-04-25T12:00:00Z",
    "source": "service-a",
    "payload": {"message": "first send"}
  }'
```

Contoh cek stats:

```bash
curl http://localhost:8080/stats
```

## Menjalankan Proyek

### Opsi 1: Lokal Tanpa Docker

```bash
pip install -r requirements.txt
uvicorn src.main:app --host 0.0.0.0 --port 8080
```

### Opsi 2: Docker

Build image:

```bash
docker build -t uts-aggregator .
```

Jalankan container:

```bash
docker run --name uts-agg -p 8080:8080 -v uts_agg_data:/app/data -d uts-aggregator
```

Verifikasi:

```bash
docker ps
curl http://localhost:8080/health
curl http://localhost:8080/stats
```

## Skenario Demo Video (Ringkas, Sesuai Rubrik)

Durasi yang disarankan: 5 sampai 8 menit.

### 1) Build dan Start Container

```bash
docker build -t uts-aggregator .
docker run --name uts-agg -p 8080:8080 -v uts_agg_data:/app/data -d uts-aggregator
docker ps
curl http://localhost:8080/health
curl http://localhost:8080/stats
```

### 2) Kirim Event Unik lalu Duplikat

```bash
curl -X POST http://localhost:8080/publish -H "Content-Type: application/json" -d '{"topic":"app.logs","event_id":"evt-001","timestamp":"2026-04-25T12:00:00Z","source":"service-a","payload":{"message":"first send"}}'
curl -X POST http://localhost:8080/publish -H "Content-Type: application/json" -d '{"topic":"app.logs","event_id":"evt-001","timestamp":"2026-04-25T12:00:05Z","source":"service-a","payload":{"message":"retry duplicate"}}'
curl "http://localhost:8080/events?topic=app.logs"
curl http://localhost:8080/stats
```

Yang harus terlihat:

1. Event unik masuk.
2. Event dengan `event_id` sama dianggap duplikat.
3. Nilai `duplicate_dropped` bertambah.

### 3) Restart Container dan Uji Persistensi Dedup

```bash
docker restart uts-agg
curl http://localhost:8080/health
curl -X POST http://localhost:8080/publish -H "Content-Type: application/json" -d '{"topic":"app.logs","event_id":"evt-001","timestamp":"2026-04-25T12:01:00Z","source":"service-a","payload":{"message":"after restart"}}'
curl "http://localhost:8080/events?topic=app.logs"
curl http://localhost:8080/stats
```

Yang harus terlihat:

1. Container sempat restart dan kembali sehat.
2. Event yang sama tetap dideteksi sebagai duplikat setelah restart.

### 4) Simulasi Beban Minimal 5000 Event

Opsi A, jalankan simulator manual:

```bash
python -m src.publisher_simulator --url http://localhost:8080/publish --total 5000 --duplicate-ratio 0.2
curl http://localhost:8080/stats
```

Opsi B, bonus Docker Compose:

```bash
docker compose up --build
docker compose down
```

## Menjalankan Test

```bash
pytest -q
```

## Arti Metrik Stats

1. `received`: total event yang diterima endpoint publish.
2. `unique_processed`: jumlah event unik yang benar-benar diproses.
3. `duplicate_dropped`: jumlah event duplikat yang ditolak.

## Persistensi Dedup Store

Dedup store menggunakan SQLite pada path default `data/dedup.db`.
Path dapat diubah lewat environment variable `DEDUP_DB_PATH`.

Dengan volume Docker `-v uts_agg_data:/app/data`, dedup state tetap tersimpan setelah restart container.

## Checklist Sebelum Upload YouTube

1. Durasi video 5 sampai 8 menit.
2. Build image dan run container terlihat.
3. Event unik dan event duplikat sama-sama ditampilkan.
4. Output `GET /events` dan `GET /stats` terlihat jelas.
5. Restart container ditampilkan.
6. Bukti dedup tetap efektif setelah restart ditampilkan.
7. Simulasi minimal 5000 event dengan duplikasi minimal 20% ditampilkan.
8. Penutup berisi ringkasan keputusan desain.

## Troubleshooting Singkat

Port 8080 sudah dipakai:

```bash
docker run --name uts-agg -p 8081:8080 -v uts_agg_data:/app/data -d uts-aggregator
```

Jika pakai port 8081, semua curl diarahkan ke `http://localhost:8081`.

Container gagal start:

```bash
docker logs uts-agg
```

Stats belum berubah:

Consumer berjalan asynchronous, tunggu sebentar lalu cek ulang endpoint stats.

Simulator tidak ditemukan:

```bash
pip install -r requirements.txt
```

Pastikan perintah dijalankan dari folder proyek.

## Link Video Demo

https://youtu.be/jSaMKpdi-OI
