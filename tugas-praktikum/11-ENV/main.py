import os

nama = os.environ.get("NAMA", "User Default")
port = os.environ.get("PORT_APLIKASI", "8000")

print(f"Halo {nama}!")
print(f"Aplikasi kamu dikonfigurasi berjalan di port: {port}")
