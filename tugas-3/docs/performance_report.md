# Performance Analysis Report

Laporan ini diisi setelah menjalankan benchmark via
`benchmarks/run_benchmarks.py`. Template di bawah menunjukkan format
yang diharapkan; angka akan terisi otomatis dari hasil run.

## Skenario Pengujian

| Skenario | Tools | Beban | Tujuan |
|----------|-------|-------|--------|
| Cache: read-heavy | in-process | 10K reads, 1K writes | Hit ratio MESI |
| Cache: write-heavy | in-process | 10K writes, hot key | Invalidation cost |
| Queue: throughput | in-process | 5K enqueue/dequeue | Throughput msg/s |
| Lock: contention | in-process | 100 client x 10 lock | Latency p50/p99 |
| HTTP: end-to-end | locust | 50 user, 2 menit | RPS, p99 |

## Hasil Sample (akan ditimpa oleh `run_benchmarks.py`)

### Cache (MESI, LRU, max=1000)
| Metric                | Single-node | 3-node | Δ          |
|-----------------------|-------------|--------|------------|
| Read throughput (ops/s)| 12.000     | 9.500  | -20.8%     |
| Write throughput      | 8.500       | 4.200  | -50.6%     |
| Hit ratio             | 0.92        | 0.88   | -4.3%      |
| p99 latency (ms)      | 1.2         | 4.8    | +300%      |

### Queue (consistent hashing, RF=2)
| Metric              | Single | 3-node | Δ      |
|---------------------|--------|--------|--------|
| Enqueue (msg/s)     | 6.800  | 4.500  | -33.8% |
| Dequeue (msg/s)     | 5.200  | 3.800  | -26.9% |
| Replikasi overhead  | -      | ~30%   |        |

### Lock Manager (Raft)
| Metric              | 3-node | 5-node |
|---------------------|--------|--------|
| Acquire (ops/s)     | 280    | 180    |
| p99 latency (ms)    | 25     | 38     |
| Election time (ms)  | 220    | 280    |

## Analisis

### Throughput
Distribusi menurunkan throughput karena overhead replikasi dan koordinasi.
Trade-off ini diterima sebagai harga ketahanan terhadap node failure.

### Latency
p99 jauh lebih tinggi pada 3-node karena:
1. Round-trip ke leader untuk lock acquire.
2. Quorum wait untuk Raft commit.
3. Invalidate broadcast untuk cache write.

### Skalabilitas
- Cache: read scales near-linearly (data direplikasi sebagai SHARED).
- Queue: scales horizontal lewat consistent hashing — tambah node →
  bagian ring per node mengecil.
- Lock: bottleneck di leader; tidak scale horizontal untuk write.

## Visualisasi

Grafik akan dihasilkan di `benchmarks/results/`:
- `throughput_comparison.png`
- `latency_distribution.png`
- `cache_hit_ratio.png`
- `raft_election_time.png`

## Single vs Distributed Comparison

Sistem distributed kalah dalam raw throughput tapi memberikan:
- Toleransi terhadap kegagalan satu node.
- Tidak ada single point of failure.
- Skalabilitas horizontal untuk read.

Untuk workload write-heavy yang konsisten kuat, single-node tetap unggul;
distributed cocok untuk workload read-heavy dengan kebutuhan availability.
