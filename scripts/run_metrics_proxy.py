import argparse
import os
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import get_settings


DEFAULT_UPSTREAM_URL = "http://api:8000/api/v1/operations/metrics/prometheus"


class MetricsProxyHandler(BaseHTTPRequestHandler):
    upstream_url = DEFAULT_UPSTREAM_URL
    api_key = ""
    upstream_timeout_seconds = 5.0

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._send_text(200, "ok\n")
            return
        if self.path != "/metrics":
            self._send_text(404, "not found\n")
            return
        try:
            payload = fetch_metrics(
                upstream_url=self.upstream_url,
                api_key=self.api_key,
                timeout_seconds=self.upstream_timeout_seconds,
            )
        except Exception as exc:
            self._send_text(502, f"upstream metrics request failed: {type(exc).__name__}\n")
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send_text(self, status_code: int, body: str) -> None:
        payload = body.encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def fetch_metrics(*, upstream_url: str, api_key: str, timeout_seconds: float) -> bytes:
    request = urllib.request.Request(
        upstream_url,
        headers={
            "Accept": "text/plain",
            "X-API-Key": api_key,
        },
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        return response.read()


def run_server(
    *,
    host: str,
    port: int,
    upstream_url: str,
    api_key: str,
    upstream_timeout_seconds: float,
) -> None:
    MetricsProxyHandler.upstream_url = upstream_url
    MetricsProxyHandler.api_key = api_key
    MetricsProxyHandler.upstream_timeout_seconds = upstream_timeout_seconds
    server = ThreadingHTTPServer((host, port), MetricsProxyHandler)
    print(
        "metrics proxy listening "
        f"host={host} port={port} upstream={upstream_url}",
        flush=True,
    )
    server.serve_forever()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    api_key = args.api_key or _default_api_key()
    run_server(
        host=args.host,
        port=args.port,
        upstream_url=args.upstream_url,
        api_key=api_key,
        upstream_timeout_seconds=args.upstream_timeout_seconds,
    )
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Expose a local /metrics endpoint that injects X-API-Key upstream.",
    )
    parser.add_argument("--host", default=os.environ.get("METRICS_PROXY_HOST", "0.0.0.0"))
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("METRICS_PROXY_PORT", "9100")),
    )
    parser.add_argument(
        "--upstream-url",
        default=os.environ.get("METRICS_PROXY_UPSTREAM_URL", DEFAULT_UPSTREAM_URL),
    )
    parser.add_argument("--api-key", default=os.environ.get("METRICS_PROXY_API_KEY"))
    parser.add_argument(
        "--upstream-timeout-seconds",
        type=float,
        default=float(os.environ.get("METRICS_PROXY_UPSTREAM_TIMEOUT_SECONDS", "5")),
    )
    return parser.parse_args(argv)


def _default_api_key() -> str:
    env_key = os.environ.get("APP_API_KEY")
    if env_key:
        return env_key
    settings_keys = get_settings().accepted_api_keys
    if settings_keys:
        return settings_keys[0]
    raise RuntimeError("Provide METRICS_PROXY_API_KEY, APP_API_KEY, or APP_API_KEYS.")


if __name__ == "__main__":
    raise SystemExit(main())
