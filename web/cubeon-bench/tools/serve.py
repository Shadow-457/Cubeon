#!/usr/bin/env python3
"""Serve only Cubeon Bench, at its production subpath, without dependencies."""
import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]


class Handler(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        path = unquote(urlsplit(path).path)
        relative = path.removeprefix('/cubeon-bench/').lstrip('/')
        candidate = (ROOT / relative).resolve()
        return str(candidate if candidate.is_relative_to(ROOT) else ROOT / '__invalid_path__')

    def do_GET(self):
        path = urlsplit(self.path).path
        if path in ('/', '/cubeon-bench'):
            self.send_response(302)
            self.send_header('Location', '/cubeon-bench/')
            self.end_headers()
            return
        if not path.startswith('/cubeon-bench/'):
            self.send_error(404)
            return
        super().do_GET()

    def end_headers(self):
        self.send_header('Cache-Control', 'no-cache')
        super().end_headers()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--host', default='127.0.0.1')
    args = parser.parse_args()
    with ThreadingHTTPServer((args.host, args.port), Handler) as server:
        print(f'Cubeon Bench: http://{args.host}:{server.server_port}/cubeon-bench/', flush=True)
        print('Keep using this address to reopen your saved projects. Ctrl+C stops the server.', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
