#!/usr/bin/env python3
"""fixture_server.py — deterministic local HTTPS server for the AW-006 QEMU
OTA drills. Serves static files from --root over TLS (the local test CA from
firmware/test/qemu/scripts/gen-test-pki.sh), plus a synthetic /healthz.

A scenario is just a directory of files the harness generated beforehand:
  <root>/api/releases/latest   (GitHub Releases API shape: {"tag_name": ...})
  <root>/manifest.json         (signed manifest, our schema)
  <root>/releases/<version>/agent-widget-<version>.bin

Logs one line per request to stderr: path, Range header, status, byte count.
Never logs request/response bodies (keeps signatures/keys out of the log).
"""
import argparse
import http.server
import os
import ssl
import sys


class Handler(http.server.SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass  # replaced by explicit logging in do_GET/do_HEAD below

    def _log(self, status, nbytes):
        rng = self.headers.get("Range", "-")
        sys.stderr.write(
            f"{self.log_date_time_string()} {self.command} {self.path} range={rng} "
            f"status={status} bytes={nbytes}\n"
        )
        sys.stderr.flush()

    def do_GET(self):
        if self.path == "/healthz":
            body = b"ok"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            self._log(200, len(body))
            return
        try:
            super().do_GET()
            self._log(200, "-")
        except (BrokenPipeError, ConnectionResetError):
            self._log("aborted", "-")

    def do_HEAD(self):
        super().do_HEAD()
        self._log(200, "-")

    def send_error(self, code, message=None, explain=None):
        self._log(code, "-")
        return super().send_error(code, message, explain)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="directory to serve")
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--cert", required=True)
    ap.add_argument("--key", required=True)
    ap.add_argument("--bind", default="0.0.0.0")
    args = ap.parse_args()

    # Resolve cert/key before chdir: relative paths would otherwise be
    # interpreted against --root instead of the caller's cwd.
    cert_path = os.path.abspath(args.cert)
    key_path = os.path.abspath(args.key)

    os.chdir(args.root)
    server = http.server.ThreadingHTTPServer((args.bind, args.port), Handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile=cert_path, keyfile=key_path)
    server.socket = ctx.wrap_socket(server.socket, server_side=True)
    print(f"fixture_server: listening on {args.bind}:{args.port} root={args.root}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
