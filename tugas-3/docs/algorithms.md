# Penjelasan Algoritma

Dokumen ini menjelaskan keputusan algoritma yang digunakan, beserta
trade-off-nya.

## 1. Raft Consensus

### Mengapa Raft?
Dipilih dibanding Paxos karena lebih *understandable* (Ongaro & Ousterhout,
2014). Sub-problem dipisah menjadi:

1. **Leader Election** — randomised timeout untuk menghindari split-vote.
2. **Log Replication** — leader-driven; follower hanya menerima.
3. **Safety** — restriksi pada vote dan commit menjamin konsistensi.

### Aliran Election

```
FOLLOWER ──(timeout)──► CANDIDATE ──(majority votes)──► LEADER
                              │
                              └──(higher term seen)──► FOLLOWER
```

### Aliran Replikasi

1. Client → leader: command.
2. Leader append ke log lokal.
3. Leader broadcast `AppendEntries`.
4. Saat majority ack → commit.
5. Apply ke state machine, balas client.

### Penanganan Partition
Jika leader berada di sisi minoritas, ia tidak akan mendapat majority ack
→ tidak ada entry baru yang commit. Sisi mayoritas akan timeout dan
memilih leader baru. Saat partition healed, mantan leader akan
mengundurkan diri ke FOLLOWER karena melihat term yang lebih tinggi.

## 2. Phi Accrual Failure Detector

### Mengapa Phi Accrual?
Threshold-based detector statis (mis. "5 missed heartbeats = dead") rapuh
terhadap variasi latency jaringan. Phi Accrual (Hayashibara dkk., 2004)
memanfaatkan **distribusi historis interval heartbeat** untuk memberikan
*confidence level* `phi`:

```
phi(t) = -log10( P(elapsed | distribution) )
```

`phi = 1` → ~10% probabilitas false positive; `phi = 8` → ~10⁻⁸. Cocok
untuk sistem real seperti Cassandra dan Akka.

## 3. Consistent Hashing dengan Virtual Nodes

### Masalah
Hashing langsung `hash(key) mod N` redistribusi semua key saat N berubah.

### Solusi
Tempatkan node pada *ring* `[0, 2¹²⁸]`. Key di-hash ke posisi ring;
diberikan ke node berikutnya searah jarum jam.

### Virtual Nodes
Tanpa virtual nodes, node bisa bertanggung jawab atas porsi ring yang
sangat tidak seimbang. Dengan **150 vnode/fisik**, hukum bilangan besar
membuat distribusi praktis seragam (deviasi ≤ ~10%).

### Penambahan Replica
`get_n_nodes(key, n)` berjalan keliling ring sampai mendapat `n` node
fisik *berbeda* — menjamin replica tidak menumpuk pada satu host.

## 4. MESI Cache Coherence

### Latar Belakang
Pada multi-cache yang berbagi data, write pada satu cache harus terlihat
oleh cache lain — atau invalidasi-nya harus eksplisit. MESI populer di
multi-core CPU dan diadaptasi di sini ke level node.

### Trade-off
- **Konsistensi**: kuat (linearizable untuk single key) — write
  meng-invalidate semua replica sebelum sukses.
- **Latency tulis**: lebih tinggi daripada write-back yang murni karena
  ada round-trip invalidate.
- **Bandwidth**: lebih rendah dari MOESI (tidak ada O state yang
  "owns" dirty-shared line). Cocok untuk workload dengan write moderat.

### Mengapa Bukan MOESI?
MOESI menambah state O (Owner) yang memungkinkan dirty data dishare.
Manfaatnya signifikan untuk workload write-heavy dengan banyak reader,
tapi menambah kompleksitas. Untuk benchmark di repo ini, MESI cukup.

## 5. Wait-For-Graph Deadlock Detection

### Algoritma
Maintain `wait_for: client → set(client)` setiap kali request lock
diblokir. Periodik (2 detik), DFS untuk mencari cycle. Cycle = deadlock.

### Strategi Pemilihan Korban
**Youngest-wait-die**: client dengan timestamp permintaan termuda diabort.
Ini menghindari starvation transaksi tua dan menjamin progress.

### Alternatif yang Dipertimbangkan
- **Distributed deadlock prevention** (timeout-only): sederhana tapi
  banyak abort palsu.
- **Edge chasing** (Chandy-Misra-Haas): lebih hemat bandwidth tapi lebih
  kompleks; berlebihan untuk skala 3-node demo ini.

## 6. PBFT (Bonus)

### Tiga-fase
1. **PRE-PREPARE**: primary kirim request + nomor urut + digest.
2. **PREPARE**: replica yang setuju broadcast PREPARE; tunggu 2f.
3. **COMMIT**: setelah 2f PREPARE, broadcast COMMIT; tunggu 2f+1.

### Toleransi
Aman selama jumlah node byzantine `f ≤ (n-1)/3`. Untuk n=4, f=1;
untuk n=7, f=2.

### Demonstrasi Byzantine
Mode `set_byzantine(True)` membuat node primary mengirim digest yang
berbeda ke setiap replica. Replica akan menolak karena digest tidak
match dengan `compute_digest(request)` lokal.
