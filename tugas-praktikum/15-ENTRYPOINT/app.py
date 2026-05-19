import sys

if len(sys.argv) > 1:
    nama = sys.argv[1]
else:
    nama = "User Default"

print(f"Halo {nama}, pesan ini diproses di dalam ENTRYPOINT Python!")
