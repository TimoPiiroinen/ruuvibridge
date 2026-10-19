"""Serve fixed local assets and a loopback-only API with mutation token checks."""

import csv
import io
import json
import logging
import os
import secrets
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .i18n import translate
from .storage import TAG_ID

LOG = logging.getLogger(__name__)
STATIC = Path(__file__).parent / "static"


class LocalServer(ThreadingHTTPServer):
    """Allow quick POSIX restarts without permitting a second Windows listener."""

    daemon_threads = True
    allow_reuse_address = os.name != "nt"

    def server_bind(self):
        if os.name == "nt":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def create_server(bridge, port, shutdown):
    """Bind only loopback; local processes are trusted, foreign web origins are not."""
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            LOG.debug(fmt, *args)

        def respond(self, code, body, content_type="application/json; charset=utf-8"):
            if isinstance(body, dict) and "error" in body:
                body = {
                    **body,
                    "error": translate(body["error"], bridge.store.settings()["language"]),
                }
            if isinstance(body, (dict, list)):
                body = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
            elif isinstance(body, str):
                body = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
            )
            self.end_headers()
            self.wfile.write(body)

        def safe_host(self):
            # Checking Host as well as Origin prevents DNS-rebinding access.
            return self.headers.get("Host") in (
                f"127.0.0.1:{self.server.server_port}",
                f"localhost:{self.server.server_port}",
            )

        def do_GET(self):
            if not self.safe_host():
                return self.respond(403, {"error": "Virheellinen osoite"})
            url = urlsplit(self.path)
            if url.path == "/api/state":
                return self.respond(200, {**bridge.snapshot(), "token": token})
            if url.path in ("/api/history", "/api/export"):
                params = parse_qs(url.query)
                tag = params.get("tag", [""])[0]
                try:
                    hours = int(params.get("hours", ["24"])[0])
                    if not TAG_ID.fullmatch(tag) or hours not in (1, 24, 168, 720):
                        raise ValueError()
                except ValueError:
                    return self.respond(400, {"error": "Virheellinen anturi tai aikaväli"})
                rows = bridge.store.history(tag, hours)
                if url.path == "/api/history":
                    return self.respond(200, {"samples": rows})
                output = io.StringIO()
                writer = csv.DictWriter(
                    output,
                    fieldnames=("time", "temperature", "humidity", "pressure", "battery", "rssi"),
                )
                writer.writeheader()
                writer.writerows(rows)
                return self.respond(200, output.getvalue(), "text/csv; charset=utf-8")
            assets = {
                "/": ("index.html", "text/html; charset=utf-8"),
                "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                "/i18n.json": ("i18n.json", "application/json; charset=utf-8"),
                "/style.css": ("style.css", "text/css; charset=utf-8"),
                "/logo.png": ("assets/ruuvi-bridge-logo-256.png", "image/png"),
                "/favicon.ico": ("assets/ruuvi-bridge.ico", "image/x-icon"),
            }
            if url.path in assets:
                filename, content_type = assets[url.path]
                return self.respond(200, (STATIC / filename).read_bytes(), content_type)
            self.respond(404, {"error": "Sivua ei löydy"})

        def do_POST(self):
            if not self.safe_host() or not secrets.compare_digest(
                self.headers.get("X-Ruuvi-Token", ""), token
            ):
                return self.respond(403, {"error": "Avaa käyttöliittymä uudelleen"})
            origin = self.headers.get("Origin")
            if origin and origin not in (
                f"http://127.0.0.1:{self.server.server_port}",
                f"http://localhost:{self.server.server_port}",
            ):
                return self.respond(403, {"error": "Virheellinen lähde"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 8192 or self.headers.get_content_type() != "application/json":
                    return self.respond(400, {"error": "Virheellinen pyyntö"})
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError("Virheellinen pyyntö")
                if self.path == "/api/settings":
                    bridge.update_settings(body)
                elif self.path == "/api/tag":
                    bridge.update_tag(body["id"], body["name"], body["enabled"])
                elif self.path == "/api/shutdown":
                    self.respond(200, {"ok": True})
                    shutdown()
                    return
                else:
                    return self.respond(404, {"error": "Tuntematon toiminto"})
                return self.respond(200, {"ok": True})
            except (ValueError, TypeError, KeyError) as error:
                return self.respond(400, {"error": str(error) or "Virheellinen arvo"})
            except Exception:
                LOG.exception("API request failed")
                return self.respond(
                    500, {"error": "Toiminto epäonnistui; tarkista sovelluksen loki"}
                )

    return LocalServer(("127.0.0.1", port), Handler)
