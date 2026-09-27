#!/usr/bin/env python3
"""Sirve el HTML de desarrollo en 0.0.0.0 y apunta la API al mismo host (LAN).

Copia de Control de Proyecto (Instalacion/desarrollo/servir-frontend.py) con
la página y los puertos del Sistema de Cotización.
"""
from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

INJECT = b'\n<script src="config.js"></script>\n'
APPS = ("sistema_cotizacion.html",)


class Handler(SimpleHTTPRequestHandler):
    config_js = b""
    config_path = ""
    api_port = 8100
    index_html = "sistema_cotizacion.html"

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            self._redirect("/" + self.index_html.lstrip("/"))
            return
        name = path.rsplit("/", 1)[-1]
        if name in APPS and name != self.index_html:
            self._redirect("/" + self.index_html)
            return
        if path == "/config.js":
            body = self.config_js
            if self.config_path:
                try:
                    body = Path(self.config_path).read_bytes()
                except OSError:
                    pass
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if name == self.index_html:
            self._serve_app(name)
            return
        super().do_GET()

    def _redirect(self, loc: str) -> None:
        self.send_response(302)
        self.send_header("Location", loc)
        self.end_headers()

    def _serve_app(self, name: str) -> None:
        fp = Path(self.translate_path("/" + name))
        data = fp.read_bytes()
        if b'src="config.js"' not in data[:2048]:
            lower = data.lower()
            idx = lower.find(b"<head>")
            if idx >= 0:
                end = idx + len(b"<head>")
                data = data[:end] + INJECT + data[end:]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt: str, *args) -> None:
        pass


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--root", required=True)
    p.add_argument("--bind", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8090)
    p.add_argument("--config", required=True)
    p.add_argument("--api-port", type=int, default=8100)
    p.add_argument("--index", default="sistema_cotizacion.html")
    args = p.parse_args()
    Handler.config_path = args.config
    Handler.config_js = Path(args.config).read_bytes()
    Handler.api_port = args.api_port
    Handler.index_html = args.index
    httpd = ThreadingHTTPServer(
        (args.bind, args.port),
        partial(Handler, directory=args.root),
    )
    httpd.serve_forever()


if __name__ == "__main__":
    main()
