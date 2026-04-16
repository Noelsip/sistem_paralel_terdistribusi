#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
 SIMULASI INTERAKTIF MODEL KOMUNIKASI DALAM SISTEM TERDISTRIBUSI
=============================================================================
 Nama   : Noel Ericson Rapael Sipayung
 NIM    : 11231072
 Mata Kuliah : Sistem Paralel dan Terdistribusi

 Model Komunikasi yang Disimulasikan:
   1. Request-Response  – Sinkron; klien memblokir hingga respons diterima.
   2. Publish-Subscribe – Asinkron berbasis topik melalui broker terpusat.
   3. Message Passing   – Asinkron point-to-point dengan antrian pesan.

 Cara menjalankan:
   python simulasi_komunikasi.py

 Cara berinteraksi:
   - Pilih tab model komunikasi yang ingin dilihat.
   - Gunakan tombol dan kontrol di panel kanan untuk memicu aksi.
   - Amati animasi paket pesan pada kanvas dan log di panel kanan.
   - Buka tab "Perbandingan" untuk melihat metrik gabungan semua model.
=============================================================================
"""

import tkinter as tk
from tkinter import ttk, scrolledtext
import time
import random
import math
from datetime import datetime
from collections import defaultdict

# ─── Palet Warna (GitHub Dark-inspired) ───────────────────────────────────────
BG      = '#0d1117'
SURF    = '#161b22'
BORDER  = '#30363d'
TEXT    = '#e6edf3'
MUTED   = '#8b949e'
BLUE    = '#58a6ff'
GREEN   = '#3fb950'
ORANGE  = '#d29922'
RED     = '#f85149'
PURPLE  = '#bc8cff'
CYAN    = '#56d364'
YELLOW  = '#e3b341'

NODE_CLR = {
    'client':     '#1f6feb',
    'server':     '#238636',
    'broker':     '#9a3412',
    'publisher':  '#7e4f08',
    'subscriber': '#512d98',
    'node':       '#1a4971',
}
MSG_CLR = {
    'request':   BLUE,
    'response':  GREEN,
    'publish':   ORANGE,
    'notify':    PURPLE,
    'message':   CYAN,
    'ack':       YELLOW,
}

FONT_TITLE = ('Segoe UI', 13, 'bold')
FONT_NORM  = ('Segoe UI', 10)
FONT_MONO  = ('Consolas', 9)
FONT_SMALL = ('Consolas', 8)


def ts():
    """Timestamp pendek."""
    return datetime.now().strftime('%H:%M:%S.%f')[:-3]


# ─── Kelas Animasi Paket ───────────────────────────────────────────────────────
class AnimatedPacket:
    """Paket pesan yang bergerak dari satu node ke node lain di atas kanvas."""

    def __init__(self, canvas, x1, y1, x2, y2,
                 color=BLUE, label='', size=9, speed=0.045, on_arrive=None):
        self.canvas    = canvas
        self.src       = (x1, y1)
        self.dst       = (x2, y2)
        self.color     = color
        self.on_arrive = on_arrive
        self.progress  = 0.0
        self.speed     = speed
        self.done      = False
        self._size     = size

        # Gambar oval (paket)
        self.oval = canvas.create_oval(
            x1 - size, y1 - size, x1 + size, y1 + size,
            fill=color, outline='white', width=1, tags='packet')
        # Label kecil di atas paket
        self.tag = canvas.create_text(
            x1, y1 - size - 5, text=label,
            fill='white', font=FONT_SMALL, tags='packet') if label else None

    def step(self):
        if self.done:
            return
        self.progress = min(1.0, self.progress + self.speed)
        t = self.progress
        t2 = t * t * (3.0 - 2.0 * t)          # ease-in-out
        x = self.src[0] + (self.dst[0] - self.src[0]) * t2
        y = self.src[1] + (self.dst[1] - self.src[1]) * t2
        s = self._size
        try:
            self.canvas.coords(self.oval, x - s, y - s, x + s, y + s)
            if self.tag:
                self.canvas.coords(self.tag, x, y - s - 5)
        except Exception:
            pass

        if self.progress >= 1.0:
            self.done = True
            self._destroy()
            if self.on_arrive:
                self.on_arrive()

    def _destroy(self):
        try:
            self.canvas.delete(self.oval)
            if self.tag:
                self.canvas.delete(self.tag)
        except Exception:
            pass


# ─── Kelas Node Visual ─────────────────────────────────────────────────────────
class VNode:
    """Node visual berbentuk lingkaran dengan label dan status."""

    def __init__(self, canvas, x, y, name, color=BLUE, radius=30):
        self.canvas = canvas
        self.x, self.y = x, y
        self._color = color
        self.radius = radius

        # Bayangan
        canvas.create_oval(x - radius + 3, y - radius + 3,
                           x + radius + 3, y + radius + 3,
                           fill='#000000', outline='', tags='node')
        # Lingkaran utama
        self.circ = canvas.create_oval(x - radius, y - radius,
                                       x + radius, y + radius,
                                       fill=color, outline='white', width=2, tags='node')
        # Nama
        self.lbl = canvas.create_text(x, y, text=name,
                                      fill='white', font=FONT_SMALL + ('bold',), tags='node')
        # Status
        self.stlbl = canvas.create_text(x, y + radius + 14, text='idle',
                                        fill=MUTED, font=FONT_SMALL, tags='node')

    def status(self, txt, color=MUTED):
        self.canvas.itemconfig(self.stlbl, text=txt, fill=color)

    def flash(self, color='white', ms=250):
        self.canvas.itemconfig(self.circ, fill=color)
        self.canvas.after(ms, lambda: self.canvas.itemconfig(self.circ, fill=self._color))

    def draw_arrow(self, x2, y2, color=BORDER, dash=()):
        """Gambar panah statis menuju koordinat tujuan."""
        self.canvas.create_line(self.x, self.y, x2, y2,
                                fill=color, width=1, arrow=tk.LAST,
                                arrowshape=(10, 12, 4), dash=dash, tags='arrow')


# ─── Panel Log Kejadian ────────────────────────────────────────────────────────
class EventLog:
    """Widget log kejadian berwarna."""

    TAGS = {
        'send':    {'foreground': BLUE},
        'recv':    {'foreground': GREEN},
        'info':    {'foreground': MUTED},
        'warn':    {'foreground': ORANGE},
        'error':   {'foreground': RED},
        'pub':     {'foreground': ORANGE},
        'sub':     {'foreground': PURPLE},
        'msg':     {'foreground': CYAN},
    }

    def __init__(self, parent, height=12):
        self.txt = scrolledtext.ScrolledText(
            parent, height=height, bg=BG, fg=TEXT,
            font=FONT_MONO, state='disabled',
            insertbackground=TEXT, relief='flat',
            borderwidth=0)
        self.txt.pack(fill='both', expand=True, padx=4, pady=4)
        for tag, cfg in self.TAGS.items():
            self.txt.tag_config(tag, **cfg)

    def log(self, msg, kind='info'):
        self.txt.config(state='normal')
        self.txt.insert('end', f'[{ts()}] ', 'info')
        self.txt.insert('end', msg + '\n', kind)
        self.txt.see('end')
        self.txt.config(state='disabled')

    def clear(self):
        self.txt.config(state='normal')
        self.txt.delete('1.0', 'end')
        self.txt.config(state='disabled')


# ─── Tab 1: Request-Response ───────────────────────────────────────────────────
class RequestResponseTab(tk.Frame):
    """
    Simulasi model Request-Response (Client-Server).

    Cara kerja:
      • Klien mengirim REQUEST ke server.
      • Server memproses selama waktu acak (delay simulasi).
      • Server mengembalikan RESPONSE ke klien.
      • Klien memblokir (tidak bisa mengirim baru) sampai respons diterima.
      Ini mencerminkan sifat sinkron Request-Response.
    """

    def __init__(self, parent, metrics: dict):
        super().__init__(parent, bg=BG)
        self._metrics = metrics
        self._metrics['rr'] = defaultdict(float)
        self._packets = []
        self._waiting = False
        self._req_count = 0
        self._latency_sum = 0.0
        self._req_time = 0.0
        self._build_ui()
        self._animate()

    # ── Layout ──
    def _build_ui(self):
        # Kiri: kanvas simulasi
        left = tk.Frame(self, bg=BG)
        left.pack(side='left', fill='both', expand=True)

        tk.Label(left, text='Model: Request-Response (Sinkron)',
                 bg=BG, fg=BLUE, font=FONT_TITLE).pack(anchor='w', padx=10, pady=(8, 2))
        tk.Label(left,
                 text='Klien mengirim request → server memproses → server mengirim response.\n'
                      'Klien MEMBLOKIR selama menunggu respons (bersifat sinkron).',
                 bg=BG, fg=MUTED, font=FONT_SMALL, justify='left').pack(anchor='w', padx=12)

        self.cv = tk.Canvas(left, bg=SURF, highlightthickness=0, height=340)
        self.cv.pack(fill='both', expand=True, padx=8, pady=6)

        # Kanan: kontrol + log
        right = tk.Frame(self, bg=SURF, width=280)
        right.pack(side='right', fill='y', padx=(0, 8), pady=8)
        right.pack_propagate(False)

        tk.Label(right, text='Kontrol', bg=SURF, fg=TEXT,
                 font=FONT_NORM + ('bold',)).pack(anchor='w', padx=8, pady=(8, 2))

        # Input pesan
        inp_frm = tk.Frame(right, bg=SURF)
        inp_frm.pack(fill='x', padx=8)
        tk.Label(inp_frm, text='Isi Pesan:', bg=SURF, fg=TEXT, font=FONT_SMALL).pack(anchor='w')
        self.msg_var = tk.StringVar(value='GET /data')
        tk.Entry(inp_frm, textvariable=self.msg_var, bg=BG, fg=TEXT,
                 insertbackground=TEXT, font=FONT_MONO, relief='flat',
                 highlightbackground=BORDER, highlightthickness=1).pack(fill='x', pady=2)

        # Delay server
        tk.Label(right, text='Delay Server (ms):', bg=SURF, fg=TEXT,
                 font=FONT_SMALL).pack(anchor='w', padx=8)
        self.delay_var = tk.IntVar(value=800)
        tk.Scale(right, from_=100, to=3000, orient='horizontal',
                 variable=self.delay_var, bg=SURF, fg=TEXT,
                 troughcolor=BORDER, highlightthickness=0).pack(fill='x', padx=8)

        self.send_btn = tk.Button(right, text='▶  Kirim Request',
                                  bg=BLUE, fg='white', font=FONT_NORM + ('bold',),
                                  relief='flat', cursor='hand2',
                                  command=self._send_request)
        self.send_btn.pack(fill='x', padx=8, pady=6)

        tk.Button(right, text='↺  Reset', bg=BORDER, fg=TEXT,
                  font=FONT_NORM, relief='flat', cursor='hand2',
                  command=self._reset).pack(fill='x', padx=8, pady=2)

        # Metrik
        tk.Label(right, text='Metrik', bg=SURF, fg=TEXT,
                 font=FONT_NORM + ('bold',)).pack(anchor='w', padx=8, pady=(10, 2))
        self.stat_lbl = tk.Label(right, text=self._stat_text(),
                                 bg=SURF, fg=CYAN, font=FONT_MONO,
                                 justify='left', anchor='w')
        self.stat_lbl.pack(fill='x', padx=8)

        # Log
        tk.Label(right, text='Log Kejadian', bg=SURF, fg=TEXT,
                 font=FONT_NORM + ('bold',)).pack(anchor='w', padx=8, pady=(8, 0))
        self.log = EventLog(right, height=10)

        self.cv.bind('<Configure>', lambda e: self._draw_static())

    def _stat_text(self):
        m = self._metrics['rr']
        avg = (m['lat_sum'] / m['count']) if m['count'] > 0 else 0
        return (f"  Request dikirim : {int(m['count'])}\n"
                f"  Latency rata-rata: {avg:.0f} ms\n"
                f"  Throughput       : {m['throughput']:.2f} req/s")

    # ── Gambar komponen statis ──
    def _draw_static(self):
        self.cv.delete('all')
        w = self.cv.winfo_width() or 600
        h = self.cv.winfo_height() or 340
        cx, cy = w // 2, h // 2

        # Garis koneksi
        self.cv.create_line(80 + 30, cy, w - 80 - 30, cy,
                            fill=BORDER, width=2, dash=(6, 4))

        # Node
        self._client = VNode(self.cv, 80,     cy, 'CLIENT', NODE_CLR['client'])
        self._server = VNode(self.cv, w - 80, cy, 'SERVER', NODE_CLR['server'])

        # Label jalur
        self.cv.create_text(cx, cy - 24, text='─── REQUEST ───▶',
                            fill=BLUE, font=FONT_SMALL)
        self.cv.create_text(cx, cy + 24, text='◀─── RESPONSE ───',
                            fill=GREEN, font=FONT_SMALL)

        # Status koneksi
        self.cv.create_text(cx, 20,
                            text='TCP / HTTP  |  Sinkron (blocking)',
                            fill=MUTED, font=FONT_SMALL)

        # Antrian klien (ilustrasi)
        self._draw_queue_boxes(w, h)

    def _draw_queue_boxes(self, w, h):
        """Gambar kotak ilustrasi antrian sinkron."""
        labels = ['Req #1', 'Req #2', 'Req #3']
        for i, lbl in enumerate(labels):
            x = 20
            y = 60 + i * 36
            alpha = 1.0 - i * 0.3
            clr = BLUE if i == 0 else BORDER
            self.cv.create_rectangle(x, y, x + 60, y + 26,
                                     fill=clr, outline=BORDER)
            self.cv.create_text(x + 30, y + 13, text=lbl,
                                fill='white', font=FONT_SMALL)
        self.cv.create_text(50, 48, text='Antrian\nKlien',
                            fill=MUTED, font=FONT_SMALL)

    # ── Aksi kirim ──
    def _send_request(self):
        if self._waiting:
            self.log.log('Klien masih menunggu respons (blocking)...', 'warn')
            return
        self._waiting = True
        self._req_count += 1
        self._req_time = time.time()
        msg = self.msg_var.get() or 'GET /data'
        self.send_btn.config(state='disabled', bg=BORDER)

        self._client.status('sending...', BLUE)
        self._client.flash(BLUE)
        self.log.log(f'Klien → REQUEST #{self._req_count}: "{msg}"', 'send')

        w = self.cv.winfo_width() or 600
        cy = (self.cv.winfo_height() or 340) // 2

        pkt = AnimatedPacket(
            self.cv, 110, cy - 10, (w - 110), cy - 10,
            color=MSG_CLR['request'], label=f'REQ#{self._req_count}',
            on_arrive=lambda: self._server_receive(msg))
        self._packets.append(pkt)

    def _server_receive(self, msg):
        self._server.flash(GREEN)
        self._server.status('processing...', ORANGE)
        self.log.log(f'Server ← menerima request: "{msg}"', 'recv')
        delay = self.delay_var.get()
        self.log.log(f'Server memproses selama {delay} ms...', 'info')
        self.after(delay, lambda: self._server_respond(msg))

    def _server_respond(self, msg):
        self._server.status('responding', GREEN)
        resp = f'200 OK: data={random.randint(100, 999)}'
        self.log.log(f'Server → RESPONSE: "{resp}"', 'send')

        w = self.cv.winfo_width() or 600
        cy = (self.cv.winfo_height() or 340) // 2
        pkt = AnimatedPacket(
            self.cv, (w - 110), cy + 10, 110, cy + 10,
            color=MSG_CLR['response'], label='RESP',
            on_arrive=lambda: self._client_receive(resp))
        self._packets.append(pkt)

    def _client_receive(self, resp):
        self._waiting = False
        lat = (time.time() - self._req_time) * 1000
        self._client.flash(GREEN)
        self._client.status('done', GREEN)
        self._server.status('idle', MUTED)
        self.log.log(f'Klien ← RESPONSE: "{resp}"  [{lat:.0f} ms]', 'recv')

        m = self._metrics['rr']
        m['count'] += 1
        m['lat_sum'] += lat
        m['throughput'] = m['count'] / max(1, (time.time() - m.get('t0', time.time())))
        if 't0' not in m:
            m['t0'] = time.time()
        self.stat_lbl.config(text=self._stat_text())
        self.send_btn.config(state='normal', bg=BLUE)
        self.after(1500, lambda: self._client.status('idle', MUTED))

    def _reset(self):
        self._waiting = False
        self._packets.clear()
        self._metrics['rr'] = defaultdict(float)
        self.send_btn.config(state='normal', bg=BLUE)
        self.log.clear()
        self.log.log('Simulasi di-reset.', 'info')
        self.stat_lbl.config(text=self._stat_text())
        self._draw_static()

    def _animate(self):
        for p in self._packets[:]:
            p.step()
            if p.done:
                self._packets.remove(p)
        self.after(33, self._animate)


# ─── Tab 2: Publish-Subscribe ──────────────────────────────────────────────────
TOPICS = ['cuaca', 'berita', 'saham', 'olahraga']
TOPIC_CLR = {'cuaca': BLUE, 'berita': GREEN, 'saham': ORANGE, 'olahraga': PURPLE}

class PubSubTab(tk.Frame):
    """
    Simulasi model Publish-Subscribe melalui Broker.

    Cara kerja:
      • Publisher menerbitkan pesan ke topik tertentu.
      • Broker menerima pesan dan meneruskan HANYA ke subscriber
        yang berlangganan topik tersebut (topic filtering).
      • Subscriber tidak perlu tahu siapa publishernya (decoupled).
      Ini mencerminkan sifat asinkron dan loosely-coupled Pub-Sub.
    """

    SUBS = [
        ('Sub-A', ['cuaca', 'berita']),
        ('Sub-B', ['saham', 'olahraga']),
        ('Sub-C', ['cuaca', 'saham']),
        ('Sub-D', ['berita']),
    ]

    def __init__(self, parent, metrics: dict):
        super().__init__(parent, bg=BG)
        self._metrics = metrics
        self._metrics['ps'] = defaultdict(float)
        self._packets = []
        self._pub_count = 0
        self._notif_count = 0
        self._t0 = None
        self._build_ui()
        self._animate()

    def _build_ui(self):
        left = tk.Frame(self, bg=BG)
        left.pack(side='left', fill='both', expand=True)

        tk.Label(left, text='Model: Publish-Subscribe (Asinkron via Broker)',
                 bg=BG, fg=ORANGE, font=FONT_TITLE).pack(anchor='w', padx=10, pady=(8, 2))
        tk.Label(left,
                 text='Publisher → Broker (topik) → hanya Subscriber yang berlangganan topik tsb.\n'
                      'Publisher & Subscriber tidak saling mengenal (loosely coupled).',
                 bg=BG, fg=MUTED, font=FONT_SMALL, justify='left').pack(anchor='w', padx=12)

        self.cv = tk.Canvas(left, bg=SURF, highlightthickness=0, height=360)
        self.cv.pack(fill='both', expand=True, padx=8, pady=6)

        right = tk.Frame(self, bg=SURF, width=280)
        right.pack(side='right', fill='y', padx=(0, 8), pady=8)
        right.pack_propagate(False)

        tk.Label(right, text='Kontrol', bg=SURF, fg=TEXT,
                 font=FONT_NORM + ('bold',)).pack(anchor='w', padx=8, pady=(8, 2))

        tk.Label(right, text='Topik:', bg=SURF, fg=TEXT, font=FONT_SMALL).pack(anchor='w', padx=8)
        self.topic_var = tk.StringVar(value='cuaca')
        for t in TOPICS:
            tk.Radiobutton(right, text=t.capitalize(), variable=self.topic_var, value=t,
                           bg=SURF, fg=TOPIC_CLR[t], selectcolor=BG,
                           activebackground=SURF, font=FONT_SMALL).pack(anchor='w', padx=16)

        tk.Label(right, text='Isi Pesan:', bg=SURF, fg=TEXT, font=FONT_SMALL).pack(anchor='w', padx=8, pady=(4,0))
        self.msg_var = tk.StringVar(value='Hujan deras hari ini')
        tk.Entry(right, textvariable=self.msg_var, bg=BG, fg=TEXT,
                 insertbackground=TEXT, font=FONT_MONO, relief='flat',
                 highlightbackground=BORDER, highlightthickness=1).pack(fill='x', padx=8, pady=2)

        tk.Button(right, text='📢  Publish', bg=ORANGE, fg='white',
                  font=FONT_NORM + ('bold',), relief='flat', cursor='hand2',
                  command=self._publish).pack(fill='x', padx=8, pady=6)

        tk.Button(right, text='↺  Reset', bg=BORDER, fg=TEXT,
                  font=FONT_NORM, relief='flat', cursor='hand2',
                  command=self._reset).pack(fill='x', padx=8, pady=2)

        tk.Label(right, text='Langganan Subscriber', bg=SURF, fg=TEXT,
                 font=FONT_NORM + ('bold',)).pack(anchor='w', padx=8, pady=(8, 2))
        for name, topics in self.SUBS:
            clrs = [TOPIC_CLR[t] for t in topics]
            t_str = ', '.join(f'[{t}]' for t in topics)
            tk.Label(right, text=f'  {name}: {t_str}',
                     bg=SURF, fg=PURPLE, font=FONT_SMALL).pack(anchor='w', padx=8)

        tk.Label(right, text='Metrik', bg=SURF, fg=TEXT,
                 font=FONT_NORM + ('bold',)).pack(anchor='w', padx=8, pady=(10, 2))
        self.stat_lbl = tk.Label(right, text=self._stat_text(),
                                 bg=SURF, fg=CYAN, font=FONT_MONO, justify='left')
        self.stat_lbl.pack(fill='x', padx=8)

        tk.Label(right, text='Log Kejadian', bg=SURF, fg=TEXT,
                 font=FONT_NORM + ('bold',)).pack(anchor='w', padx=8, pady=(6, 0))
        self.log = EventLog(right, height=8)

        self.cv.bind('<Configure>', lambda e: self._draw_static())

    def _stat_text(self):
        m = self._metrics['ps']
        thr = m['pub_count'] / max(1, (time.time() - m['t0'])) if m.get('t0') else 0
        return (f"  Pesan dipublish  : {int(m['pub_count'])}\n"
                f"  Notif dikirim   : {int(m['notif_count'])}\n"
                f"  Throughput       : {thr:.2f} pub/s")

    def _draw_static(self):
        self.cv.delete('all')
        w = self.cv.winfo_width() or 620
        h = self.cv.winfo_height() or 360
        mid_x = w // 2
        cy = h // 2

        # Publisher (kiri)
        self._pub_node = VNode(self.cv, 70, cy, 'PUB', NODE_CLR['publisher'], radius=28)
        self.cv.create_line(70 + 28, cy, mid_x - 32, cy,
                            fill=BORDER, width=2, dash=(6, 3))

        # Broker (tengah)
        self._broker = VNode(self.cv, mid_x, cy, 'BROKER', NODE_CLR['broker'], radius=32)
        self.cv.create_text(mid_x, cy + 50,
                            text='Topic\nFilter', fill=MUTED, font=FONT_SMALL)

        # Subscriber (kanan) – 4 buah
        sub_xs = [w - 70] * 4
        sub_ys = [cy - 120, cy - 40, cy + 40, cy + 120]
        self._sub_nodes = []
        for i, (name, topics) in enumerate(self.SUBS):
            sn = VNode(self.cv, sub_xs[i], sub_ys[i], name,
                       NODE_CLR['subscriber'], radius=24)
            self._sub_nodes.append(sn)
            # Garis dari broker ke subscriber
            self.cv.create_line(mid_x + 32, cy, sub_xs[i] - 24, sub_ys[i],
                                fill=BORDER, width=1, dash=(4, 4))
            # Label topik
            tstr = ' '.join(f'[{t[0]}]' for t in topics)
            self.cv.create_text(sub_xs[i] - 30, sub_ys[i] - 30,
                                text=tstr, fill=MUTED, font=FONT_SMALL)

        self.cv.create_text(w // 2, 18,
                            text='Asinkron  |  Loosely Coupled  |  Topic-based Routing',
                            fill=MUTED, font=FONT_SMALL)

    def _publish(self):
        if self._t0 is None:
            self._t0 = time.time()
            self._metrics['ps']['t0'] = self._t0

        topic = self.topic_var.get()
        msg   = self.msg_var.get() or 'test'
        self._pub_count += 1
        color = TOPIC_CLR.get(topic, ORANGE)

        self._pub_node.flash(color)
        self._pub_node.status('publishing', color)
        self.log.log(f'PUB → topik="{topic}": "{msg}"', 'pub')

        w = self.cv.winfo_width() or 620
        cy = (self.cv.winfo_height() or 360) // 2
        mid_x = w // 2

        pkt = AnimatedPacket(
            self.cv, 98, cy, mid_x - 32, cy,
            color=color, label=topic[:5],
            on_arrive=lambda: self._broker_receive(topic, msg, color))
        self._packets.append(pkt)
        m = self._metrics['ps']
        m['pub_count'] += 1
        self.stat_lbl.config(text=self._stat_text())

    def _broker_receive(self, topic, msg, color):
        self._broker.flash(color)
        self.log.log(f'Broker ← topik="{topic}" | filtering subscriber...', 'info')

        w = self.cv.winfo_width() or 620
        cy = (self.cv.winfo_height() or 360) // 2
        mid_x = w // 2
        sub_xs = [w - 70] * 4
        sub_ys = [cy - 120, cy - 40, cy + 40, cy + 120]

        delay = 0
        for i, (name, topics) in enumerate(self.SUBS):
            if topic in topics:
                d = delay
                idx = i
                def _send(i=idx, d=d):
                    self.after(d, lambda: self._notify_sub(
                        i, topic, msg, color, mid_x, cy, sub_xs[i], sub_ys[i]))
                _send()
                delay += 180

    def _notify_sub(self, idx, topic, msg, color, bx, by, sx, sy):
        self._sub_nodes[idx].flash(color)
        name = self.SUBS[idx][0]

        pkt = AnimatedPacket(
            self.cv, bx + 32, by, sx - 24, sy,
            color=color, label='✉',
            on_arrive=lambda: self._sub_receive(name, topic, msg))
        self._packets.append(pkt)

    def _sub_receive(self, name, topic, msg, ):
        self.log.log(f'{name} ← notif topik="{topic}": "{msg}"', 'sub')
        m = self._metrics['ps']
        m['notif_count'] += 1
        self.stat_lbl.config(text=self._stat_text())

    def _reset(self):
        self._packets.clear()
        self._t0 = None
        self._metrics['ps'] = defaultdict(float)
        self.log.clear()
        self.log.log('Simulasi di-reset.', 'info')
        self.stat_lbl.config(text=self._stat_text())
        self._draw_static()

    def _animate(self):
        for p in self._packets[:]:
            p.step()
            if p.done:
                self._packets.remove(p)
        self.after(33, self._animate)


# ─── Tab 3: Message Passing ────────────────────────────────────────────────────
class MessagePassingTab(tk.Frame):
    """
    Simulasi model Message Passing (Point-to-Point).

    Cara kerja:
      • Setiap node memiliki antrian masuk (inbox queue).
      • Pengirim menaruh pesan ke antrian penerima tanpa menunggu.
      • Penerima memproses pesan dari antriannya secara asinkron.
      Ini mencerminkan sifat asinkron dan decoupled Message Passing.
    """

    NODES = ['Node-A', 'Node-B', 'Node-C', 'Node-D', 'Node-E']

    def __init__(self, parent, metrics: dict):
        super().__init__(parent, bg=BG)
        self._metrics = metrics
        self._metrics['mp'] = defaultdict(float)
        self._packets = []
        self._queues = {n: [] for n in self.NODES}
        self._msg_count = 0
        self._t0 = None
        self._build_ui()
        self._animate()
        self._process_queues()

    def _build_ui(self):
        left = tk.Frame(self, bg=BG)
        left.pack(side='left', fill='both', expand=True)

        tk.Label(left, text='Model: Message Passing (Asinkron P2P)',
                 bg=BG, fg=CYAN, font=FONT_TITLE).pack(anchor='w', padx=10, pady=(8, 2))
        tk.Label(left,
                 text='Pengirim menaruh pesan ke antrian penerima lalu langsung lanjut (non-blocking).\n'
                      'Penerima memproses pesan dari antriannya sendiri secara independen.',
                 bg=BG, fg=MUTED, font=FONT_SMALL, justify='left').pack(anchor='w', padx=12)

        self.cv = tk.Canvas(left, bg=SURF, highlightthickness=0, height=360)
        self.cv.pack(fill='both', expand=True, padx=8, pady=6)

        right = tk.Frame(self, bg=SURF, width=280)
        right.pack(side='right', fill='y', padx=(0, 8), pady=8)
        right.pack_propagate(False)

        tk.Label(right, text='Kontrol', bg=SURF, fg=TEXT,
                 font=FONT_NORM + ('bold',)).pack(anchor='w', padx=8, pady=(8, 2))

        frm = tk.Frame(right, bg=SURF)
        frm.pack(fill='x', padx=8)

        tk.Label(frm, text='Dari:', bg=SURF, fg=TEXT, font=FONT_SMALL).grid(row=0, column=0, sticky='w')
        self.from_var = tk.StringVar(value='Node-A')
        ttk.Combobox(frm, textvariable=self.from_var, values=self.NODES,
                     state='readonly', width=10).grid(row=0, column=1, padx=4, pady=2)

        tk.Label(frm, text='Ke:', bg=SURF, fg=TEXT, font=FONT_SMALL).grid(row=1, column=0, sticky='w')
        self.to_var = tk.StringVar(value='Node-C')
        ttk.Combobox(frm, textvariable=self.to_var, values=self.NODES,
                     state='readonly', width=10).grid(row=1, column=1, padx=4, pady=2)

        tk.Label(right, text='Isi Pesan:', bg=SURF, fg=TEXT, font=FONT_SMALL).pack(anchor='w', padx=8)
        self.msg_var = tk.StringVar(value='Hello!')
        tk.Entry(right, textvariable=self.msg_var, bg=BG, fg=TEXT,
                 insertbackground=TEXT, font=FONT_MONO, relief='flat',
                 highlightbackground=BORDER, highlightthickness=1).pack(fill='x', padx=8, pady=2)

        tk.Button(right, text='📨  Kirim Pesan', bg=CYAN, fg=BG,
                  font=FONT_NORM + ('bold',), relief='flat', cursor='hand2',
                  command=self._send_msg).pack(fill='x', padx=8, pady=4)

        tk.Button(right, text='🔀  Kirim Acak (×5)', bg=PURPLE, fg='white',
                  font=FONT_NORM, relief='flat', cursor='hand2',
                  command=self._send_random).pack(fill='x', padx=8, pady=2)

        tk.Button(right, text='↺  Reset', bg=BORDER, fg=TEXT,
                  font=FONT_NORM, relief='flat', cursor='hand2',
                  command=self._reset).pack(fill='x', padx=8, pady=2)

        tk.Label(right, text='Metrik', bg=SURF, fg=TEXT,
                 font=FONT_NORM + ('bold',)).pack(anchor='w', padx=8, pady=(8, 2))
        self.stat_lbl = tk.Label(right, text=self._stat_text(),
                                 bg=SURF, fg=CYAN, font=FONT_MONO, justify='left')
        self.stat_lbl.pack(fill='x', padx=8)

        # Antrian visual
        tk.Label(right, text='Antrian Masuk (inbox)', bg=SURF, fg=TEXT,
                 font=FONT_NORM + ('bold',)).pack(anchor='w', padx=8, pady=(8, 2))
        self.queue_lbl = tk.Label(right, text=self._queue_text(),
                                  bg=SURF, fg=YELLOW, font=FONT_MONO, justify='left')
        self.queue_lbl.pack(fill='x', padx=8)

        tk.Label(right, text='Log Kejadian', bg=SURF, fg=TEXT,
                 font=FONT_NORM + ('bold',)).pack(anchor='w', padx=8, pady=(6, 0))
        self.log = EventLog(right, height=7)

        self.cv.bind('<Configure>', lambda e: self._draw_static())

    def _stat_text(self):
        m = self._metrics['mp']
        thr = m['sent'] / max(1, (time.time() - m['t0'])) if m.get('t0') else 0
        return (f"  Pesan dikirim : {int(m['sent'])}\n"
                f"  Pesan diproses: {int(m['processed'])}\n"
                f"  Throughput    : {thr:.2f} msg/s")

    def _queue_text(self):
        lines = []
        for n in self.NODES:
            q = self._queues[n]
            qs = f'[{len(q)}]' if q else '[ ]'
            lines.append(f'  {n}: {qs}')
        return '\n'.join(lines)

    def _draw_static(self):
        self.cv.delete('all')
        w = self.cv.winfo_width() or 600
        h = self.cv.winfo_height() or 360
        # Susun 5 node dalam lingkaran
        cx, cy, r = w // 2, h // 2, min(w, h) // 2 - 55
        self._node_pos = {}
        self._vnodes = {}
        for i, name in enumerate(self.NODES):
            angle = math.radians(270 + i * 360 / len(self.NODES))
            nx = int(cx + r * math.cos(angle))
            ny = int(cy + r * math.sin(angle))
            self._node_pos[name] = (nx, ny)

        # Gambar garis antar semua node
        for i, n1 in enumerate(self.NODES):
            for n2 in self.NODES[i + 1:]:
                x1, y1 = self._node_pos[n1]
                x2, y2 = self._node_pos[n2]
                self.cv.create_line(x1, y1, x2, y2,
                                    fill=BORDER, width=1, dash=(4, 6))

        for name in self.NODES:
            nx, ny = self._node_pos[name]
            vn = VNode(self.cv, nx, ny, name[:6], NODE_CLR['node'], radius=26)
            self._vnodes[name] = vn

        self.cv.create_text(cx, 18,
                            text='Asinkron  |  Non-blocking  |  Point-to-Point  |  Queue-based',
                            fill=MUTED, font=FONT_SMALL)

    def _send_msg(self):
        src = self.from_var.get()
        dst = self.to_var.get()
        if src == dst:
            self.log.log('Pengirim dan penerima harus berbeda!', 'warn')
            return
        msg = self.msg_var.get() or 'ping'
        self._do_send(src, dst, msg)

    def _send_random(self):
        for _ in range(5):
            src, dst = random.sample(self.NODES, 2)
            msgs = ['ping', 'sync', 'data_req', 'heartbeat', 'update', 'task']
            self.after(random.randint(0, 400), lambda s=src, d=dst, m=random.choice(msgs):
                       self._do_send(s, d, m))

    def _do_send(self, src, dst, msg):
        if self._t0 is None:
            self._t0 = time.time()
            self._metrics['mp']['t0'] = self._t0

        self._msg_count += 1
        mid = self._msg_count
        x1, y1 = self._node_pos[src]
        x2, y2 = self._node_pos[dst]

        self._vnodes[src].flash(CYAN)
        self._vnodes[src].status('sending', CYAN)
        self.log.log(f'{src} → {dst}: "{msg}" [#{mid}]', 'msg')

        pkt = AnimatedPacket(
            self.cv, x1, y1, x2, y2,
            color=MSG_CLR['message'], label=f'#{mid}',
            on_arrive=lambda: self._enqueue(src, dst, msg, mid))
        self._packets.append(pkt)
        m = self._metrics['mp']
        m['sent'] += 1
        self.stat_lbl.config(text=self._stat_text())

    def _enqueue(self, src, dst, msg, mid):
        self._queues[dst].append((src, msg, mid))
        self._vnodes[dst].flash(YELLOW)
        self._vnodes[dst].status(f'inbox:{len(self._queues[dst])}', YELLOW)
        self.log.log(f'{dst} ← masuk antrian: "{msg}" dari {src}', 'recv')
        self.queue_lbl.config(text=self._queue_text())

    def _process_queues(self):
        """Proses satu item dari setiap antrian node secara periodik."""
        for name in self.NODES:
            if self._queues[name]:
                src, msg, mid = self._queues[name].pop(0)
                self._vnodes[name].flash(GREEN)
                self._vnodes[name].status('processing', GREEN)
                self.log.log(f'{name} ✓ diproses: "{msg}" dari {src} [#{mid}]', 'recv')
                m = self._metrics['mp']
                m['processed'] += 1
                self.stat_lbl.config(text=self._stat_text())
                self.queue_lbl.config(text=self._queue_text())
        self.after(600, self._process_queues)

    def _reset(self):
        self._packets.clear()
        self._queues = {n: [] for n in self.NODES}
        self._t0 = None
        self._metrics['mp'] = defaultdict(float)
        self.log.clear()
        self.log.log('Simulasi di-reset.', 'info')
        self.stat_lbl.config(text=self._stat_text())
        self.queue_lbl.config(text=self._queue_text())
        self._draw_static()

    def _animate(self):
        for p in self._packets[:]:
            p.step()
            if p.done:
                self._packets.remove(p)
        self.after(33, self._animate)


# ─── Tab 4: Perbandingan ───────────────────────────────────────────────────────
class ComparisonTab(tk.Frame):
    """Tab perbandingan metrik antar ketiga model komunikasi."""

    def __init__(self, parent, metrics: dict):
        super().__init__(parent, bg=BG)
        self._metrics = metrics
        self._build_ui()
        self._update_loop()

    def _build_ui(self):
        tk.Label(self, text='Perbandingan Model Komunikasi',
                 bg=BG, fg=TEXT, font=FONT_TITLE).pack(anchor='w', padx=14, pady=(10, 2))
        tk.Label(self,
                 text='Perbandingan throughput, latency, dan karakteristik kualitatif '
                      'ketiga model komunikasi berdasarkan simulasi yang telah dijalankan.',
                 bg=BG, fg=MUTED, font=FONT_SMALL).pack(anchor='w', padx=14)

        # Kanvas bar chart
        self.cv = tk.Canvas(self, bg=SURF, highlightthickness=0, height=280)
        self.cv.pack(fill='x', padx=10, pady=6)

        # Tabel karakteristik
        self._build_table()

    def _build_table(self):
        frm = tk.Frame(self, bg=SURF)
        frm.pack(fill='both', expand=True, padx=10, pady=(0, 10))

        headers = ['Kriteria', 'Request-Response', 'Publish-Subscribe', 'Message Passing']
        col_clrs = [TEXT, BLUE, ORANGE, CYAN]
        rows = [
            ('Pola komunikasi',   'Sinkron',      'Asinkron',     'Asinkron'),
            ('Coupling',          'Tightly',      'Loosely',      'Loosely'),
            ('Skalabilitas',      'Rendah',       'Tinggi',       'Sedang'),
            ('Latensi',           'Tinggi*',      'Rendah',       'Rendah'),
            ('Kompleksitas',      'Rendah',       'Sedang',       'Sedang'),
            ('Kasus pakai',       'API/Web',      'Event system', 'Microservice'),
            ('Fault tolerance',   'Rendah',       'Tinggi',       'Tinggi'),
        ]

        for ci, (h, c) in enumerate(zip(headers, col_clrs)):
            tk.Label(frm, text=h, bg=SURF, fg=c,
                     font=FONT_NORM + ('bold',),
                     relief='flat', padx=6, pady=4,
                     borderwidth=0).grid(row=0, column=ci, sticky='nsew', padx=1, pady=1)

        for ri, row in enumerate(rows):
            for ci, val in enumerate(row):
                bg = BG if ri % 2 == 0 else SURF
                clr = MUTED if ci == 0 else TEXT
                tk.Label(frm, text=val, bg=bg, fg=clr,
                         font=FONT_SMALL, padx=6, pady=3).grid(
                    row=ri + 1, column=ci, sticky='nsew', padx=1, pady=0)

        tk.Label(frm, text='  * Latensi R-R mencakup waktu pemrosesan server',
                 bg=SURF, fg=MUTED, font=FONT_SMALL).grid(
            row=len(rows) + 1, column=0, columnspan=4, sticky='w', pady=(4, 0))

    def _draw_chart(self):
        self.cv.delete('all')
        w = self.cv.winfo_width() or 700
        h = self.cv.winfo_height() or 280

        title = 'Throughput (operasi/detik) – berdasarkan simulasi'
        self.cv.create_text(w // 2, 16, text=title, fill=TEXT, font=FONT_NORM + ('bold',))

        rr = self._metrics.get('rr', {})
        ps = self._metrics.get('ps', {})
        mp = self._metrics.get('mp', {})

        def thr(m, key):
            cnt = m.get(key, 0)
            t0  = m.get('t0', 0)
            if t0 == 0:
                return 0.0
            return cnt / max(1, time.time() - t0)

        values = [
            ('R-R',  thr(rr, 'count'), BLUE),
            ('P-S',  thr(ps, 'pub_count'), ORANGE),
            ('M-P',  thr(mp, 'sent'), CYAN),
        ]

        max_v = max((v for _, v, _ in values), default=1)
        max_v = max(max_v, 0.001)

        bar_w  = 80
        gap    = (w - len(values) * bar_w) // (len(values) + 1)
        bottom = h - 50
        top    = 40

        for i, (lbl, val, clr) in enumerate(values):
            x0 = gap + i * (bar_w + gap)
            bar_h = (val / max_v) * (bottom - top)
            y0 = bottom - bar_h
            # Bar
            self.cv.create_rectangle(x0, y0, x0 + bar_w, bottom,
                                     fill=clr, outline='', width=0)
            # Nilai
            self.cv.create_text(x0 + bar_w // 2, max(y0 - 10, top),
                                text=f'{val:.2f}', fill=TEXT, font=FONT_SMALL)
            # Label
            self.cv.create_text(x0 + bar_w // 2, bottom + 12,
                                text=lbl, fill=TEXT, font=FONT_NORM + ('bold',))

        # Garis dasar
        self.cv.create_line(gap - 10, bottom, w - gap + 10, bottom,
                            fill=BORDER, width=1)

        # Latency R-R
        cnt = rr.get('count', 0)
        ls  = rr.get('lat_sum', 0)
        avg_lat = (ls / cnt) if cnt > 0 else 0
        self.cv.create_text(w - 10, h - 10,
                            text=f'Avg Latency R-R: {avg_lat:.0f} ms',
                            fill=MUTED, font=FONT_SMALL, anchor='se')

    def _update_loop(self):
        self._draw_chart()
        self.after(500, self._update_loop)


# ─── Aplikasi Utama ────────────────────────────────────────────────────────────
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Simulasi Komunikasi Sistem Terdistribusi — Noel E.R. Sipayung')
        self.geometry('1080x660')
        self.minsize(900, 580)
        self.configure(bg=BG)
        self._metrics: dict = {}
        self._build()

    def _build(self):
        # Header
        hdr = tk.Frame(self, bg='#010409', pady=6)
        hdr.pack(fill='x')
        tk.Label(hdr,
                 text='  🌐  Simulasi Interaktif Model Komunikasi Sistem Terdistribusi',
                 bg='#010409', fg=TEXT, font=('Segoe UI', 12, 'bold')).pack(side='left')
        tk.Label(hdr, text='Noel E.R. Sipayung  ·  11231072  ·  Sistem Paralel & Terdistribusi  ',
                 bg='#010409', fg=MUTED, font=FONT_SMALL).pack(side='right')

        # Notebook
        style = ttk.Style(self)
        style.theme_use('default')
        style.configure('TNotebook',       background=BG, borderwidth=0)
        style.configure('TNotebook.Tab',   background=SURF, foreground=MUTED,
                        padding=[14, 6], font=FONT_NORM)
        style.map('TNotebook.Tab',
                  background=[('selected', BG)],
                  foreground=[('selected', TEXT)])

        nb = ttk.Notebook(self)
        nb.pack(fill='both', expand=True, padx=6, pady=(4, 6))

        t1 = RequestResponseTab(nb, self._metrics)
        t2 = PubSubTab(nb, self._metrics)
        t3 = MessagePassingTab(nb, self._metrics)
        t4 = ComparisonTab(nb, self._metrics)

        nb.add(t1, text='  Request-Response  ')
        nb.add(t2, text='  Publish-Subscribe  ')
        nb.add(t3, text='  Message Passing  ')
        nb.add(t4, text='  📊 Perbandingan  ')

        # Status bar
        self._sbar = tk.Label(self, text=' Siap.  Pilih tab untuk memulai simulasi.',
                              bg='#010409', fg=MUTED, font=FONT_SMALL, anchor='w')
        self._sbar.pack(fill='x', side='bottom')


# ─── Entry Point ──────────────────────────────────────────────────────────────
if __name__ == '__main__':
    app = App()
    app.mainloop()
