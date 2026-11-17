"""Local HTTP interface for Release Desk."""

import argparse
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from releases import Store, WorkflowError

ROOT = Path(__file__).resolve().parent
ASSETS = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"),
          "/style.css": ("style.css", "text/css")}


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, data, content_type="application/json", filename=None):
        if content_type == "application/json":
            data = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; frame-ancestors 'none'")
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(data)

    def serve(self):
        if self.headers.get("Host") != self.server.authority:
            raise WorkflowError("Open the local Release Desk URL.", 403)
        if self.command == "GET":
            if self.path in ASSETS:
                name, media = ASSETS[self.path]
                return self.reply(200, (ROOT / "static" / name).read_bytes(), media)
            if self.path == "/api/releases":
                return self.reply(200, self.server.store.list())
            if match := re.fullmatch(r"/api/releases/([1-9][0-9]{0,17})(/export)?", self.path):
                release_id = int(match[1])
                if match[2]:
                    body = self.server.store.export(release_id)
                    return self.reply(200, body.encode(), "text/markdown", f"release-{release_id}.md")
                return self.reply(200, self.server.store.get(release_id))

        if self.command == "POST":
            if self.headers.get("Origin") != f"http://{self.server.authority}":
                raise WorkflowError("Use the local Release Desk page.", 403)
            if self.headers.get_content_type() != "application/json":
                raise WorkflowError("Expected JSON.", 415)
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 40000:
                    raise ValueError
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError
            except ValueError:
                raise WorkflowError("Expected a JSON object within the size limit.", 400) from None
            if self.path == "/api/releases":
                return self.reply(201, self.server.store.create(data))
            if match := re.fullmatch(r"/api/releases/([1-9][0-9]{0,17})", self.path):
                return self.reply(200, self.server.store.change(int(match[1]), data))
        raise WorkflowError("Route not found.", 404)

    def do_GET(self):
        try:
            self.serve()
        except WorkflowError as error:
            self.reply(error.status, {"error": str(error)})

    do_POST = do_GET


def build_server(path, port=8780):
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    try:
        server.store = Store(path)
    except Exception:
        server.server_close()
        raise
    server.authority = f"127.0.0.1:{server.server_port}"
    return server


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=ROOT / "data/release-desk.sqlite3")
    parser.add_argument("--port", type=int, default=8780)
    args = parser.parse_args()
    args.db.parent.mkdir(parents=True, exist_ok=True)
    with build_server(args.db, args.port) as server:
        print(f"Release Desk is running at http://{server.authority}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
