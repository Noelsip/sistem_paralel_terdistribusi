import threading

data_buffer = []
buffer_lock = threading.Lock()
read_done = threading.Event() # selesai membaca

def read_file (filename):
    """Thread 1 – Membaca file ke buffer bersama."""
    print("[Thread Pembaca] Mulai membaca file...")
    with open(filename, 'r') as f:
        lines = f.readlines()
    with buffer_lock:
        data_buffer.extend(lines)
    read_done.set()
    print(f"[Thread Pembaca] Selesai: {len(lines)} baris dibaca.")
    
def show_data():
    """Thread 2 – Menampilkan data setelah thread pembaca selesai."""
    read_done.wait()
    print("[Thread Penampil] Mulai menampilkan data...")
    with buffer_lock:
        for line in data_buffer:
            print(f" >> {line.strip()}")
    print("[Thread Penampil] Selesai.")
    
t1 = threading.Thread(target=read_file, args=('data.txt',))
t2 = threading.Thread(target=show_data)
t1.start(); t2.start()
t1.join(); t2.join()