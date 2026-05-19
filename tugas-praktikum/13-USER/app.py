import os
import getpass

user_aktif = getpass.getuser()
uid_aktif = os.getuid()

print("Verifikasi Keamanan Container:")
print(f"Aplikasi Python ini sukses berjalan di bawah User: {user_aktif} (UID: {uid_aktif})")
