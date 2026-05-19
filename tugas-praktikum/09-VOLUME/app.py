import os
import datetime

log_dir = "/data/logs"
log_file_path = os.path.join(log_dir, "aktivitas.log")

os.makedirs(log_dir, exist_ok=True)

waktu_sekarang = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
with open(log_file_path, "a") as f:
    f.write(f"Container berjalan pada: {waktu_sekarang}\n")

print(f"Berhasil mencatat log ke {log_file_path}!")
