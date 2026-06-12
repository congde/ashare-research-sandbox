from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import sys


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from a_share.report import build_report  # noqa: E402


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/report":
            self.send_report(parsed.query)
            return
        if parsed.path in ("/", "/index.html"):
            self.send_file(ROOT / "static/index.html", "text/html; charset=utf-8")
            return
        if parsed.path == "/styles.css":
            self.send_file(ROOT / "static/styles.css", "text/css; charset=utf-8")
            return
        if parsed.path == "/app.js":
            self.send_file(ROOT / "static/app.js", "text/javascript; charset=utf-8")
            return
        self.send_error(404)

    def send_report(self, query: str) -> None:
        params = parse_qs(query)
        try:
            short = int(params.get("short", ["3"])[0])
            long = int(params.get("long", ["7"])[0])
            payload = build_report(short=short, long=long)
            status = 200
        except (ValueError, TypeError) as error:
            payload = {"error": str(error)}
            status = 400
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path: Path, content_type: str) -> None:
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 8765), Handler)
    print("A-share research sandbox: http://127.0.0.1:8765", flush=True)
    server.serve_forever()

