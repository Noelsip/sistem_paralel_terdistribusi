# Simulasi Interaktif Model Komunikasi Sistem Terdistribusi

Nama: Noel Ericson Rapael Sipayung  
NIM: 11231072  
Mata Kuliah: Sistem Paralel dan Terdistribusi

## Ringkasan Proyek

Proyek ini berisi simulasi visual tiga pola komunikasi yang paling sering dipakai pada sistem terdistribusi. Tujuan utamanya bukan sekadar menampilkan animasi, tapi membantu memahami perbedaan perilaku komunikasi saat sistem berjalan: mana yang blocking, mana yang event-driven, dan mana yang berbasis antrian.

Simulasi dibuat dengan Tkinter (tanpa library eksternal), sehingga bisa langsung dijalankan di Python standar.

Catatan: dokumentasi ini difokuskan pada program `simulasi_komunikasi.py`.

## Tujuan Simulasi

1. Memvisualisasikan alur pesan antar komponen pada sistem terdistribusi.
2. Membandingkan karakter tiga model komunikasi dalam kondisi interaktif.
3. Menunjukkan dampak desain komunikasi terhadap metrik sederhana, terutama latency, throughput, dan penumpukan antrian.

## Model Komunikasi yang Dipilih

### 1) Request-Response

Model ini bersifat sinkron. Klien mengirim request lalu menunggu respons dari server sebelum mengirim request berikutnya.

Komponen:
- Client
- Server

Ciri yang terlihat di simulasi:
- Tombol kirim dinonaktifkan saat request masih berjalan (blocking).
- Latency sangat dipengaruhi delay pemrosesan server.

Contoh penggunaan nyata: REST API, web service berbasis HTTP.

### 2) Publish-Subscribe

Model ini bersifat asinkron dengan broker sebagai perantara. Publisher mengirim pesan ke topik, lalu broker meneruskan ke subscriber yang memang berlangganan topik tersebut.

Komponen:
- Publisher
- Broker
- Subscriber

Ciri yang terlihat di simulasi:
- Publisher tidak berkomunikasi langsung dengan subscriber.
- Satu publish dapat menghasilkan banyak notifikasi tergantung jumlah subscriber yang match topik.

Contoh penggunaan nyata: event notification, sistem notifikasi, pipeline event-driven.

### 3) Message Passing

Model ini juga asinkron, tetapi berbasis komunikasi antar node dan inbox queue. Pengirim tidak menunggu penerima selesai memproses.

Komponen:
- Node pengirim/penerima
- Inbox queue per node
- Worker pemroses periodik

Ciri yang terlihat di simulasi:
- Pesan masuk ke antrian penerima terlebih dulu.
- Pemrosesan dilakukan periodik per node, sehingga bisa terjadi backlog.

Contoh penggunaan nyata: task queue, komunikasi antarmicroservice, actor-based processing.

## Logika Simulasi

### Representasi Pesan

Setiap pesan ditampilkan sebagai paket kecil berwarna yang bergerak dari sumber ke tujuan di kanvas. Animasi memakai easing agar perpindahan terlihat halus.

Warna utama pesan:
- Request: biru
- Response: hijau
- Publish: oranye
- Notify pub-sub: ungu
- Message passing: cyan

### Alur Request-Response

1. Client kirim request ke server.
2. Server menerima dan masuk status processing selama delay yang diatur user.
3. Server kirim response balik ke client.
4. Metrik diperbarui: jumlah request, rata-rata latency, throughput.

### Alur Publish-Subscribe

1. Publisher kirim pesan ke broker dengan topik tertentu.
2. Broker melakukan filtering subscriber berdasarkan topik.
3. Broker mengirim notifikasi hanya ke subscriber yang sesuai.
4. Metrik diperbarui: jumlah publish dan jumlah notifikasi terkirim.

### Alur Message Passing

1. Node sumber mengirim pesan ke node tujuan.
2. Saat paket tiba, pesan dimasukkan ke inbox queue node tujuan.
3. Worker periodik memproses satu item dari tiap queue.
4. Metrik diperbarui: jumlah pesan terkirim dan jumlah pesan diproses.

## Instruksi Interaksi Pengguna

### Menjalankan Aplikasi

Syarat:
- Python 3.8 atau lebih baru

Perintah:

```bash
python simulasi_komunikasi.py
```

### Cara Pakai Tiap Tab

### Tab Request-Response

1. Isi kolom Isi Pesan.
2. Atur Delay Server (ms).
3. Klik Kirim Request.
4. Perhatikan status node dan log kejadian.
5. Gunakan Reset untuk mengulang metrik.

### Tab Publish-Subscribe

1. Pilih topik pesan.
2. Isi konten pesan.
3. Klik Publish.
4. Amati subscriber mana yang menerima notifikasi.
5. Coba beberapa topik untuk melihat efek filtering.

### Tab Message Passing

1. Pilih node sumber dan node tujuan.
2. Isi pesan.
3. Klik Kirim Pesan atau Kirim Acak (x5).
4. Pantau perubahan inbox queue di panel kanan.
5. Amati proses dequeue dan pemrosesan periodik.

### Tab Perbandingan

1. Jalankan ketiga tab simulasi terlebih dulu.
2. Buka tab Perbandingan.
3. Lihat bar chart throughput.
4. Gunakan tabel karakteristik sebagai perbandingan kualitatif.

## Cara Menginterpretasi Hasil Simulasi

### Metrik Utama

Request-Response:
- Request dikirim: total transaksi selesai.
- Latency rata-rata: waktu tempuh request-response.
- Throughput: request selesai per detik.

Publish-Subscribe:
- Pesan dipublish: total publish yang dilakukan.
- Notif dikirim: total notifikasi ke subscriber.
- Throughput: publish per detik.

Message Passing:
- Pesan dikirim: total pesan masuk jaringan.
- Pesan diproses: total pesan yang keluar dari queue.
- Throughput: pesan terkirim per detik.

### Panduan Baca Cepat

- Jika delay server dinaikkan, model Request-Response biasanya turun throughput dan naik latency.
- Jika subscriber topik banyak, model Publish-Subscribe akan menunjukkan notifikasi jauh lebih besar dari jumlah publish.
- Jika laju kirim pesan lebih cepat dari laju proses queue, model Message Passing akan menunjukkan penumpukan inbox.

## Kesimpulan Singkat

Request-Response paling sederhana tetapi blocking. Publish-Subscribe unggul untuk penyebaran event ke banyak penerima secara longgar. Message Passing fleksibel untuk alur asinkron berbasis antrian, tetapi perlu kontrol backlog agar tidak terjadi bottleneck pada proses penerima.

## Berkas Utama

```text
.
├── simulasi_komunikasi.py
└── README.md
```

## Referensi

- A. S. Tanenbaum, M. van Steen, Distributed Systems: Principles and Paradigms.
- G. Hohpe, B. Woolf, Enterprise Integration Patterns.
- Dokumentasi Tkinter Python: https://docs.python.org/3/library/tkinter.html
