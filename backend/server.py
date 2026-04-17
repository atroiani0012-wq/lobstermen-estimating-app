"""HTTP server exposing the UMA bid-analysis backend.

Stdlib-only (http.server) so no extra infra is required on the Tasklet
sandbox. Endpoints:

    GET  /               → serves instant-app.html
    GET  /health         → {"ok": true}
    POST /api/drive/scan → runs scan_drive; returns JSON
    POST /api/process    → runs run_pipeline; streams NDJSON progress events
                           and ends with a `{"type":"complete",...}` event
    POST /api/legacy/process → runs run_pipeline synchronously, returns the
                           full JSON result (for clients that can't consume
                           a streaming response)
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .process_bid import run_pipeline, scan_drive


ROOT = pathlib.Path(__file__).resolve().parent.parent


class _Handler(BaseHTTPRequestHandler):
    output_dir: pathlib.Path = pathlib.Path("./out")

    # --- basic response helpers ------------------------------------------------

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send_json(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self._cors()
        self.end_headers()
        self.wfile.write(data)

    def _send_file(self, path: pathlib.Path, content_type: str) -> None:
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self._cors()
        self.end_headers()
        self.wfile.write(data)

    def _start_ndjson(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("X-Accel-Buffering", "no")
        self._cors()
        self.end_headers()

    def _write_ndjson_event(self, event: dict) -> None:
        line = (json.dumps(event) + "\n").encode("utf-8")
        try:
            self.wfile.write(line)
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            # Client went away; downstream code should notice when the pipeline finishes.
            pass

    # --- HTTP verbs ------------------------------------------------------------

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors()
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

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length) if length else b""
        return json.loads(raw.decode("utf-8")) if raw else {}

    def do_POST(self) -> None:
        try:
            if self.path == "/api/drive/scan":
                payload = self._read_json_body()
                result = scan_drive(payload)
                self._send_json(200, result)
                return

            if self.path == "/api/process":
                payload = self._read_json_body()
                self._start_ndjson()

                def emit(evt: dict) -> None:
                    # Strip the giant base64 blobs from the "complete" event so
                    # the NDJSON stream stays reasonable; the browser fetches
                    # them via the final JSON response below instead? We keep
                    # them: the client finishes by reading "complete".
                    self._write_ndjson_event(evt)

                try:
                    run_pipeline(payload, output_dir=self.output_dir, emit=emit)
                except Exception as e:
                    self._write_ndjson_event({
                        "type": "error",
                        "error": str(e),
                        "traceback": traceback.format_exc(),
                    })
                return

            if self.path == "/api/legacy/process":
                payload = self._read_json_body()
                result = run_pipeline(payload, output_dir=self.output_dir)
                self._send_json(200, result)
                return

            self._send_json(404, {"ok": False, "error": f"no route for {self.path}"})
        except Exception as e:
            try:
                self._send_json(500, {
                    "ok": False,
                    "error": str(e),
                    "traceback": traceback.format_exc(),
                })
            except Exception:
                pass

    def log_message(self, format: str, *args) -> None:
        # Quieter default logs — one line per request, to stderr.
        sys.stderr.write(f"[{self.log_date_time_string()}] {format % args}\n")


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
