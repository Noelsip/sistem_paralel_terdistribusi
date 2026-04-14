import threading, time

results = {}
results_lock = threading.Lock()

def read_segmen(filename, start_line, end_line, thread_id):
    """Membaca segmen baris [start_line, end_line) dari file."""
    with open(filename, 'r') as f:
        lines = f.readlines()
    segment = lines[start_line:end_line]
    time.sleep(0.001) # simulasi I/O delay per segmen
    with results_lock:
        results[thread_id] = segment
    print(f" [Thread-{thread_id}] Baris {start_line+1}-{end_line} selesai.")


filename = 'data.txt'
num_threads = 4

with open(filename) as f:
    total_lines = len(f.readlines())
    
chunk = total_lines // num_threads
threads = []

start = time.time()
for i in range(num_threads):
    s = i * chunk
    e = total_lines if i == num_threads - 1 else (i + 1) * chunk
    t = threading.Thread(target=read_segmen, args=(filename, s, e, i+1))
    threads.append(t)
    t.start()

for t in threads:
    t.join()
end = time.time()

# Gabungan hasil secara berurutan
final_data = []
for i in range(1, num_threads + 1):
    final_data.extend(results[i])
    
print(f"\nTotal baris: {len(final_data)}")
print(f"Waktu eksekusi multi-thread: {end - start:.4f} detik")