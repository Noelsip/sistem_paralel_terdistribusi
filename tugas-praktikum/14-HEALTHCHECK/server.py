from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = 8000

counter = 0


class SimpleServer(BaseHTTPRequestHandler):
    def do_GET(self):
        global counter

        if self.path == '/health':
            counter = counter + 1

            if counter > 5:
                self.send_response(500)
                self.send_header('Content-type', 'text/plain')
                self.end_headers()
                self.wfile.write(b"KO")
                print(f"[HEALTHCHECK] Pengecekan ke-{counter}: STATUS DOWN (KO)!")
            else:
                self.send_response(200)
                self.send_header('Content-type', 'text/plain')
                self.end_headers()
                self.wfile.write(b"OK")
                print(f"[HEALTHCHECK] Pengecekan ke-{counter}: STATUS UP (OK)")

        else:
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b"Halo dari Server Python Noel!")


server = HTTPServer(('', PORT), SimpleServer)
print(f"Server berjalan di port {PORT}...")
server.serve_forever()
