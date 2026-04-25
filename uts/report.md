# Laporan UTS

## Tema

Pub-Sub Log Aggregator dengan Idempotent Consumer dan Deduplication.

## Ringkasan Arsitektur

Sistem terdiri dari satu layanan aggregator berbasis FastAPI, internal queue berbasis `asyncio.Queue`, worker consumer idempotent, dan dedup store persisten berbasis SQLite. Publisher dapat mengirim event tunggal atau batch ke endpoint `POST /publish`. Event diproses asynchronous oleh worker sehingga request handler tetap responsif saat beban meningkat. Penghapusan duplikasi dilakukan pada level storage dengan kunci unik `(topic, event_id)`. Dengan desain ini, delivery model praktis yang dicapai adalah at-least-once processing dengan efek akhir idempotent.

## Diagram Sederhana

```text
Publisher -> POST /publish -> asyncio.Queue -> Consumer Worker -> SQLite Dedup Store
                                                           |
                                                           +-> GET /events, GET /stats
```

## T1 (Bab 1)

Karakteristik utama sistem terdistribusi pada kasus ini meliputi concurrency antar komponen, tidak adanya global clock sempurna, serta kemungkinan kegagalan parsial. Pada aggregator Pub-Sub, banyak publisher dapat mengirim event secara paralel, sementara consumer harus menjaga agar hasil akhir tetap konsisten meskipun urutan kedatangan tidak deterministik. Trade-off penting muncul antara throughput, latency, dan tingkat konsistensi. Jika sistem memaksakan ordering ketat untuk semua event, kompleksitas sinkronisasi meningkat dan throughput turun. Sebaliknya, jika sistem hanya menargetkan eventual consistency dengan dedup kuat, performa naik tetapi konsumen hilir harus menerima bahwa data dapat muncul sedikit tertunda. Trade-off lain adalah antara simplicity dan durability: in-memory dedup cepat tetapi hilang saat restart, sedangkan SQLite lebih lambat sedikit namun memberikan ketahanan state. Dalam konteks tugas ini, pemilihan local persistent store adalah keputusan rasional karena kebutuhan utama adalah idempotency lintas restart container, bukan latensi absolut terendah. Prinsip ini sejalan dengan gagasan bahwa desain sistem terdistribusi selalu melibatkan kompromi antar properti fungsional dan nonfungsional (Coulouris et al., 2012; Tanenbaum & Van Steen, 2007).

## T2 (Bab 2)

Arsitektur client-server cocok ketika alur interaksi bersifat request-response langsung, coupling ketat antar pihak dapat diterima, dan beban tidak terlalu bursty. Pada model ini, publisher mengirim data dan menunggu pemrosesan penuh selesai. Sebaliknya, publish-subscribe lebih tepat ketika producer dan consumer harus decoupled dalam waktu, ruang, dan sinkronisasi. Pada aggregator log, publisher idealnya tidak menunggu proses dedup atau penyimpanan selesai satu per satu karena itu menambah latency sisi producer. Dengan Pub-Sub berbasis queue internal, endpoint publish dapat segera meng-ack penerimaan, lalu consumer memproses asynchronous. Ini meningkatkan elastisitas terhadap spike traffic dan menurunkan risiko backpressure langsung ke publisher. Pub-Sub dipilih ketika workload bersifat event-driven, volume tinggi, dan toleransi keterlambatan kecil diperbolehkan selama eventual consistency tercapai. Selain itu, pattern ini mempermudah perluasan ke banyak subscriber di masa depan tanpa mengubah kontrak publisher. Secara teknis, decoupling tersebut merefleksikan prinsip pemisahan concern pada arsitektur terdistribusi: communication path dipisahkan dari business processing path agar sistem lebih fleksibel dan scalable (Coulouris et al., 2012; Tanenbaum & Van Steen, 2007).

## T3 (Bab 3)

At-least-once delivery menjamin setiap event akan sampai minimal satu kali, tetapi event yang sama bisa terkirim ulang karena retry, timeout, atau kegagalan acknowledgement. Exactly-once delivery secara teori menjanjikan event diproses tepat satu kali, namun implementasinya end-to-end sangat kompleks karena butuh koordinasi state lintas komponen, transactional messaging, serta penanganan failure yang ketat. Dalam praktik banyak sistem, at-least-once dipilih karena lebih sederhana dan andal, lalu correctness dijaga di sisi consumer melalui idempotency. Idempotent consumer berarti memproses event yang sama berkali-kali tetap menghasilkan state akhir identik dengan sekali proses. Pada tugas ini, event didefinisikan unik oleh `(topic, event_id)`. Ketika retry terjadi, consumer melakukan dedup check sebelum commit proses sehingga duplikasi tidak mengubah hasil. Tanpa idempotency, retry dapat menggandakan insert, memperbesar metrik secara salah, dan menurunkan kualitas observability. Karena retry adalah mekanisme inti reliability pada jaringan yang tidak sempurna, idempotent consumer bukan fitur tambahan, melainkan syarat utama agar at-least-once tetap menghasilkan konsistensi aplikatif yang dapat dipercaya (Coulouris et al., 2012; Tanenbaum & Van Steen, 2007).

## T4 (Bab 4)

Skema penamaan topic sebaiknya mengikuti namespace hierarkis agar mudah di-routing, difilter, dan dikelola. Contoh: `domain.service.loglevel` seperti `payments.api.error` atau `auth.worker.info`. Untuk `event_id`, diperlukan identitas unik yang collision-resistant, misalnya UUIDv4, ULID, atau kombinasi `source + timestamp + monotonic counter + random bits`. Dalam implementasi ini, dedup key adalah pasangan `(topic, event_id)` sehingga event_id cukup unik dalam scope topic. Dampaknya terhadap dedup sangat signifikan: jika skema ID lemah, collision palsu bisa membuat event berbeda dianggap duplikat; jika terlalu longgar tanpa aturan, duplicate detection bisa gagal karena event yang sama memakai ID berbeda saat retry. Karena itu producer harus mempertahankan event_id yang stabil saat retransmission. Naming yang konsisten juga memudahkan observability melalui agregasi per topic serta analisis anomali duplikasi. Dari perspektif distributed naming, identitas bukan sekadar label, tetapi bagian dari kontrak konsistensi sistem. Kualitas naming mempengaruhi correctness dedup, efisiensi lookup, dan kemudahan operasional jangka panjang (Coulouris et al., 2012; Tanenbaum & Van Steen, 2007).

## T5 (Bab 5)

Total ordering tidak selalu diperlukan pada log aggregator. Jika tujuan utama adalah mengumpulkan event unik untuk monitoring, auditing ringan, atau statistik agregat, partial ordering per topic atau per source biasanya cukup. Kebutuhan total order global menjadi kritis hanya bila semantics bisnis bergantung pada urutan absolut antar seluruh event lintas sumber, yang mahal dicapai tanpa centralized sequencer. Pendekatan praktis adalah memakai `timestamp` ISO8601 dari publisher ditambah monotonic counter lokal di source untuk meminimalkan ambiguitas urutan saat timestamp sama. Pada sisi penyimpanan, event dapat ditampilkan berdasarkan `(timestamp, processed_at)` sebagai urutan baca yang stabil. Namun pendekatan ini memiliki batas: clock antar node bisa skew, timestamp dapat mundur, dan counter hanya valid dalam scope source. Artinya urutan yang terlihat adalah best-effort, bukan bukti kausal total. Untuk konteks tugas ini, keputusan desain menyatakan total ordering global tidak wajib karena objektif utamanya idempotency dan dedup yang kuat. Selama event unik tersimpan dan duplikasi dibuang secara deterministik, konsistensi fungsional agregator tetap tercapai meskipun ordering bersifat praktis, bukan absolut (Coulouris et al., 2012; Tanenbaum & Van Steen, 2007).

## T6 (Bab 6)

Failure modes utama pada sistem ini meliputi duplikasi event akibat retry, out-of-order arrival karena variasi latency jaringan, serta crash proses/container saat event sedang diproses. Mitigasi pertama adalah retry dengan backoff di sisi publisher agar transient failure tidak langsung dianggap kehilangan permanen. Mitigasi kedua adalah idempotent consumer dengan dedup key `(topic, event_id)` sehingga duplicate delivery tidak merusak state akhir. Mitigasi ketiga adalah durable dedup store (SQLite) agar informasi event yang sudah diproses bertahan setelah restart. Dengan begitu, crash-recovery tidak menyebabkan reprocessing event lama bila publisher mengirim ulang. Untuk out-of-order, sistem tidak memaksakan total order global; event tetap disimpan dengan metadata waktu agar analisis urutan bisa dilakukan best-effort. Kombinasi strategi ini merepresentasikan prinsip fault tolerance pragmatis: menerima kenyataan bahwa failure tidak bisa dihindari, lalu membatasi dampaknya melalui recovery-friendly protocol dan state persistence. Dengan desain tersebut, sistem tetap memberikan perilaku stabil pada beban normal maupun saat terjadi gangguan parsial (Coulouris et al., 2012; Tanenbaum & Van Steen, 2007).

## T7 (Bab 7)

Eventual consistency pada aggregator berarti seluruh replika logikal state (dalam konteks ini, view event unik yang dipublikasikan melalui API) akan konvergen ke kondisi benar setelah semua pesan dan retry selesai diproses. Sistem tidak menjamin bahwa `GET /events` langsung menampilkan event tepat pada saat publish karena ada queue asynchronous; namun dalam kondisi stabil, event unik akan muncul dan duplikasi tersaring. Idempotency berkontribusi dengan memastikan operasi pemrosesan bersifat repeat-safe, sedangkan dedup memastikan hanya representasi tunggal setiap `(topic, event_id)` yang bertahan. Keduanya bekerja bersama untuk mencegah divergensi state akibat retransmission. Tanpa idempotency, at-least-once dapat menciptakan inflasi data; tanpa dedup persisten, restart dapat mengulang pemrosesan dan merusak konvergensi. Dengan persistent key store, state pasca-recovery tetap kompatibel dengan state pra-crash, sehingga proses rekonsiliasi alami melalui retry tetap menuju hasil akhir yang sama. Pendekatan ini adalah implementasi konkret konsistensi praktis pada sistem event-driven yang menukar strong synchronicity dengan convergence berbasis determinisme kunci idempotensi (Coulouris et al., 2012; Tanenbaum & Van Steen, 2007).

## T8 (Bab 1–7)

Evaluasi sistem sebaiknya memakai metrik yang langsung menguji keputusan desain. Pertama, throughput (event/detik) mengukur kapasitas pipeline publish-queue-consume pada workload tinggi. Kedua, latency end-to-end mengukur selang waktu dari publish hingga event muncul sebagai processed unik. Ketiga, duplicate rate terdeteksi (`duplicate_dropped / received`) memvalidasi perilaku at-least-once dan kualitas dedup. Keempat, uniqueness effectiveness (`unique_processed / distinct_input_keys`) menunjukkan ketepatan idempotency. Kelima, recovery correctness setelah restart: event lama yang dikirim ulang harus masuk hitungan duplicate, bukan unique. Dalam implementasi ini, endpoint `/stats` menyediakan metrik inti `received`, `unique_processed`, `duplicate_dropped`, `topics`, dan `uptime`, sehingga observability dasar terpenuhi. Keputusan memakai queue asynchronous meningkatkan throughput dan menjaga API responsif, sementara SQLite persistent menambah sedikit overhead I/O tetapi memperkuat correctness saat crash. Dengan demikian, metrik bukan sekadar pelaporan, melainkan bukti empiris bahwa trade-off arsitektur yang diambil (decoupling, at-least-once, idempotent dedup) sesuai dengan sasaran konsistensi dan keandalan sistem terdistribusi (Coulouris et al., 2012; Hariri & Parashar, 2004; Tanenbaum & Van Steen, 2007).

## Keputusan Implementasi

1. API framework: FastAPI.
2. Queue internal: `asyncio.Queue`.
3. Dedup store persisten: SQLite dengan primary key `(topic, event_id)`.
4. Delivery model: at-least-once dengan idempotent consumer.
5. Ordering: best-effort berdasarkan timestamp, tanpa total ordering global.

## Hasil Uji Fungsional

Pengujian unit mencakup 8 skenario:

1. Publish single event.
2. Dedup event duplikat.
3. Batch event campuran unik dan duplikat.
4. Validasi skema: field wajib.
5. Validasi skema: timestamp ISO8601.
6. Konsistensi filter `GET /events?topic=...`.
7. Persistensi dedup setelah restart service.
8. Stress kecil berbasis batch dengan batas waktu.

## Daftar Pustaka (APA 7)

Coulouris, G., Dollimore, J., Kindberg, T., & Blair, G. (2012). *Distributed systems: Concepts and design* (5th ed.). Pearson.

Hariri, S., & Parashar, M. (Eds.). (2004). *Tools and environments for parallel and distributed computing*. John Wiley & Sons.

Tanenbaum, A. S., & Van Steen, M. (2007). *Distributed systems: Principles and paradigms* (2nd ed.). Pearson Prentice Hall.
