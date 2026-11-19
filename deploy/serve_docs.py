"""Static server for docs/, with an explicit UTF-8 charset on text types.

`python -m http.server` labels `.md` as `text/markdown` with no charset, so a
browser on a Chinese Windows falls back to GBK and every page turns to mojibake.
"""

import argparse
import functools
import http.server

TYPES = {
    ".md": "text/plain; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".jsonl": "text/plain; charset=utf-8",
    ".csv": "text/plain; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
}


class Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map, **TYPES}

    def end_headers(self):
        # A cached response with the old Content-Type would keep the mojibake
        # alive long after the server was fixed.
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bind", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--directory", required=True)
    args = ap.parse_args()
    handler = functools.partial(Handler, directory=args.directory)
    with http.server.ThreadingHTTPServer((args.bind, args.port), handler) as httpd:
        print(f"serving {args.directory} on http://{args.bind}:{args.port}/", flush=True)
        httpd.serve_forever()


if __name__ == "__main__":
    main()
