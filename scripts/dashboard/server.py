"""Local dashboard server (V1.6) — Python standard library only.

    python career_hunter.py dashboard [--port 8765] [--host 127.0.0.1]

Serves the single-page UI from scripts/dashboard/static/ and the JSON API from
scripts/dashboard/api.py. Binds to localhost by default; write requests must
carry the `X-Career-Hunter: 1` header (sent by the UI), so other web pages
open in your browser cannot post to it.
"""
import json
import mimetypes
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.dashboard import api  # noqa: E402

STATIC_DIR = Path(__file__).resolve().parent / "static"
MAX_BODY = 64 * 1024


class Handler(BaseHTTPRequestHandler):
    server_version = "CareerHunterDashboard/1.6"

    def log_message(self, fmt, *args):  # quiet by default
        if getattr(self.server, "verbose", False):
            super().log_message(fmt, *args)

    def _send(self, status, payload, content_type="application/json; charset=utf-8"):
        data = payload if isinstance(payload, bytes) else json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def _static(self, rel):
        rel = rel or "index.html"
        target = (STATIC_DIR / rel).resolve()
        if STATIC_DIR not in target.parents or not target.is_file():
            return self._send(404, {"error": "Not found"})
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith("javascript"):
            ctype += "; charset=utf-8"
        self._send(200, target.read_bytes(), ctype)

    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        if url.path.startswith("/api/"):
            status, payload = api.handle("GET", url.path, urllib.parse.parse_qs(url.query))
            return self._send(status, payload)
        return self._static(url.path.lstrip("/"))

    def do_POST(self):
        url = urllib.parse.urlsplit(self.path)
        if self.headers.get("X-Career-Hunter") != "1":
            return self._send(403, {"error": "Missing X-Career-Hunter header"})
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            return self._send(413, {"error": "Request too large"})
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._send(400, {"error": "Body must be JSON"})
        status, payload = api.handle("POST", url.path, body=body)
        self._send(status, payload)


def make_server(host="127.0.0.1", port=8765, verbose=False):
    server = ThreadingHTTPServer((host, port), Handler)
    server.verbose = verbose
    return server


def serve(host="127.0.0.1", port=8765, verbose=False):
    server = make_server(host, port, verbose)
    print(f"Career Hunter dashboard: http://{host}:{server.server_address[1]}/  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Dashboard stopped.")
    finally:
        server.server_close()
