#!/usr/bin/env python3

# SPDX-License-Identifier: GPL-3.0-or-later

"""Record ntfy publish requests as JSON lines."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import sys


PORT = int(sys.argv[1])
LOG = sys.argv[2]


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        record = {
            "path": self.path,
            "title": self.headers.get("Title"),
            "priority": self.headers.get("Priority"),
            "authorization": self.headers.get("Authorization"),
            "body": body.decode("utf-8", "replace"),
        }
        with open(LOG, "a", encoding="utf-8") as log:
            log.write(json.dumps(record) + "\n")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *_args):
        pass


ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
