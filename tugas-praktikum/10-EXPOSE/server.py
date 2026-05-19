import http.server
import socketserver

PORT = 8000

Handler = http.server.SimpleHTTPRequestHandler

with socketserver.TCPServer(("", PORT), Handler) as httpd:
    print(f"Server lagi berjalan dan mendengarkan di port {PORT}...")
    httpd.serve_forever()
