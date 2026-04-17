"""Minimal HTTP server that exposes process_bid.py over a single POST endpoint.

Stdlib-only (http.server) so Tasklet sandboxes without uvicorn/flask work.
The instant-app.html frontend POSTs JSON here; the server runs the pipeline
and returns a JSON result (with base64-encoded deliverables) synchronously.

Run:
    python -m backend.server --port 8787 --output-dir /tmp/uma-out

Endpoints:
    GET  /              → serves instant-app.html (if present alongside backend/)
    GET  /health        → {"ok": true}
    POST /api/process   → runs the pipeline; body = same JSON payload as process_bid.py
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .process_bid import run_pipeline


# Project root (one level above backend/) — used to serve instant-app.html.
ROOT = pathlib.Path(__file__).resolve().parent.parent


class _Handler(BaseHTTPRequestHandler):
    # Injected by main() before the server starts.
    output_dir: pathlib.Path = pathlib.Path("./out")

    def _send_json(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def _send_file(self, path: pathlib.Path, content_type: str) -> None:
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self) -> None:  # CORS preflight
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html", "/instant-app.html"):
            html = ROOT / "instant-app.html"
            if html.exists():
                self._send_file(html, "text/html; charset=utf-8")
                return
            self._send_json(404, {"ok": False, "error": "instant-app.html not found"})
            return
        if self.path == "/health":
            self._send_json(200, {"ok": True})
            return
        self._send_json(404, {"ok": False, "error": f"no route for {self.path}"})

    def do_POST(self) -> None:
        if self.path != "/api/process":
            self._send_json(404, {"ok": False, "error": f"no route for {self.path}"})
            return
        length = int(self.headers.get("Content-Length") or "0")
        try:
            raw = self.rfile.read(length) if length else b""
            payload = json.loads(raw.decode("utf-8")) if raw else {}
            result = run_pipeline(payload, output_dir=self.output_dir)
            self._send_json(200, result)
        except Exception as e:
            self._send_json(500, {
                "ok": False,
                "error": str(e),
                "traceback": traceback.format_exc(),
            })


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--output-dir", default="./out")
    args = parser.parse_args()

    _Handler.output_dir = pathlib.Path(args.output_dir)
    _Handler.output_dir.mkdir(parents=True, exist_ok=True)

    server = ThreadingHTTPServer((args.host, args.port), _Handler)
    print(f"UMA estimating backend listening on http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("shutting down", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
