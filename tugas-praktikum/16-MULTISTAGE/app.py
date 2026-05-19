import requests

response = requests.get("https://jsonplaceholder.typicode.com/todos/1")
data = response.json()

print("Berhasil terhubung ke internet di dalam Multi-Stage Container!")
print(f"Hasil Data: {data['title']}")
