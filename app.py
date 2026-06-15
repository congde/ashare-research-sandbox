from __future__ import annotations

import json
import mimetypes
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import sys


ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
HOST = "127.0.0.1"
PORT = 8765
sys.path.insert(0, str(SRC))

from backtest.rolling.service import execute_backtest, list_backtest_strategies  # noqa: E402
from config.env import load_env  # noqa: E402
from dashboard import api as dashboard_api  # noqa: E402
from paths import WEB_STATIC_DIR  # noqa: E402
from research.report import build_report  # noqa: E402
from strategy_engine.dsl import (  # noqa: E402
    check_lookahead_bias,
    validate_strategy_code,
)

load_env()

STATIC_ASSET_SUFFIXES = frozenset(
    {
        ".html",
        ".js",
        ".css",
        ".svg",
        ".json",
        ".ico",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".woff",
        ".woff2",
        ".map",
    }
)

STATIC_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".json": "application/json; charset=utf-8",
}


def looks_like_static_asset(rel: str) -> bool:
    suffix = Path(rel).suffix.lower()
    return bool(suffix) and suffix in STATIC_ASSET_SUFFIXES


def assert_port_available(host: str, port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
        except OSError as exc:
            raise SystemExit(
                f"Cannot bind {host}:{port} ({exc}). "
                "Stop other app.py instances, then retry."
            ) from exc


class SandboxHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


class Handler(BaseHTTPRequestHandler):
    server_version = "Web3ResearchSandbox/1.0"

    def do_GET(self) -> None:
        try:
            parsed = urlparse(self.path)
            if parsed.path == "/api/report":
                self.send_report(parsed.query)
                return
            if parsed.path.startswith("/api/"):
                if self.send_dashboard_api(parsed.path, parsed.query):
                    return
            rel = parsed.path.lstrip("/") or "index.html"
            static_path = self.resolve_static(rel)
            if static_path is not None:
                content_type = self.guess_content_type(static_path)
                self.send_file(static_path, content_type)
                return
            if not looks_like_static_asset(rel):
                index_path = self.resolve_static("index.html")
                if index_path is not None:
                    self.send_file(index_path, STATIC_CONTENT_TYPES[".html"])
                    return
            self.send_error(404)
        except Exception as error:  # pragma: no cover - defensive guard for threaded server
            self.send_json({"error": str(error)}, status=500)

    def resolve_static(self, rel: str) -> Path | None:
        if ".." in rel or rel.startswith(("/", "\\")):
            return None
        candidate = (WEB_STATIC_DIR / rel).resolve()
        static_root = WEB_STATIC_DIR.resolve()
        if not str(candidate).startswith(str(static_root)) or not candidate.is_file():
            return None
        return candidate

    def guess_content_type(self, path: Path) -> str:
        known = STATIC_CONTENT_TYPES.get(path.suffix.lower())
        if known:
            return known
        guessed, _ = mimetypes.guess_type(str(path))
        return guessed or "application/octet-stream"

    def do_POST(self) -> None:
        try:
            parsed = urlparse(self.path)
            if parsed.path == "/api/validate-strategy":
                self.validate_strategy()
                return
            self.send_error(404)
        except Exception as error:  # pragma: no cover
            self.send_json({"error": str(error)}, status=500)

    def send_report(self, query: str) -> None:
        params = parse_qs(query)
        try:
            short = int(params.get("short", ["3"])[0])
            long = int(params.get("long", ["7"])[0])
            payload = build_report(short=short, long=long)
            status = 200
        except (ValueError, TypeError) as error:
            payload = {"error": str(error)}
            status = 400
        self.send_json(payload, status=status)

    def send_dashboard_api(self, path: str, query: str) -> bool:
        params = parse_qs(query)

        def q(name: str, default: str) -> str:
            return params.get(name, [default])[0]

        def qi(name: str, default: int) -> int:
            try:
                return int(q(name, str(default)))
            except ValueError:
                return default

        def qf(name: str, default: float) -> float:
            try:
                return float(q(name, str(default)))
            except ValueError:
                return default

        routes = {
            "/api/dashboard/config": lambda: dashboard_api.runtime_config(),
            "/api/dashboard/sources/status": lambda: dashboard_api.sources_status(),
            "/api/dashboard/snapshots": lambda: dashboard_api.snapshots_status(),
            "/api/dashboard/vs/ai-picks": lambda: dashboard_api.ai_picks(),
            "/api/dashboard/vs/sector-fund": lambda: dashboard_api.sector_fund(qi("trade_type", 1)),
            "/api/dashboard/vs/token-fund": lambda: dashboard_api.token_fund(q("symbol", "BTC")),
            "/api/dashboard/onchain": lambda: dashboard_api.onchain(q("symbol", "BTC"), limit=qi("limit", 1)),
            "/api/dashboard/dex/trending": lambda: dashboard_api.dex_trending(
                chain=q("chain", "solana"),
                limit=qi("limit", 5),
            ),
            "/api/dashboard/opportunity-scan": lambda: dashboard_api.opportunity_scan(
                top_k=qi("topK", 5),
                max_symbols=qi("maxSymbols", 30),
                min_volume_24h=float(q("minVolume24h", "200000")),
            ),
            "/api/market/candles": lambda: dashboard_api.market_candles(
                symbol=q("symbol", "") or None,
                kline_type=q("type", "1day"),
                limit=qi("limit", 120),
                short=qi("short", 3),
                long=qi("long", 7),
            ),
            "/api/market/tickers": lambda: dashboard_api.market_tickers(
                quote=q("quote", "USDT"),
                limit=qi("limit", 300),
            ),
            "/api/market/ticker": lambda: dashboard_api.ticker_stats(q("symbol", "BTC-USDT")),
            "/api/market/kline-analysis": lambda: dashboard_api.kline_analysis(
                symbol=q("symbol", "BTC-USDT"),
                kline_type=q("type", "1hour"),
                limit=qi("limit", 120),
            ),
            "/api/dashboard/signal-analysis": lambda: dashboard_api.signal_analysis(q("symbol", "BTC")),
            "/api/dashboard/llm-signal-analysis": lambda: dashboard_api.llm_signal_analysis(
                q("symbol", "BTC"),
                model=q("model", "") or None,
            ),
            "/api/dashboard/llm-signal-analysis/poll": lambda: dashboard_api.llm_signal_poll(q("taskId", "")),
            "/api/dashboard/backtest/strategies": lambda: {
                "ok": True,
                "strategies": list_backtest_strategies(),
            },
            "/api/dashboard/backtest": lambda: execute_backtest(
                strategy_name=q("strategy", "technical_signal"),
                symbol=q("symbol", "") or None,
                kline_type=q("type", "") or None,
                limit=qi("limit", 120),
                stop_loss_pct=qf("stopLoss", 3.0),
                take_profit_pct=qf("takeProfit", 5.0),
                trailing_stop_pct=qf("trailingStop", 0.0),
                max_hold_bars=qi("maxHoldBars", 0),
            ),
        }
        handler = routes.get(path)
        if handler is None:
            return False
        try:
            payload = handler()
            self.send_json(payload, status=200 if payload.get("ok", True) else 500)
        except ValueError as error:
            self.send_json(
                {"ok": False, "error": "insufficient_data", "message": str(error)},
                status=422,
            )
        except Exception as error:  # pragma: no cover
            self.send_json({"ok": False, "message": str(error)}, status=500)
        return True

    def validate_strategy(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(body.decode("utf-8"))
            code = payload.get("code", "")
        except json.JSONDecodeError as error:
            self.send_json({"error": str(error)}, status=400)
            return

        validation = validate_strategy_code(code)
        lookahead = check_lookahead_bias(code)
        self.send_json(
            {
                "valid": validation.valid and lookahead.clean,
                "validation": {
                    "valid": validation.valid,
                    "errors": [
                        {
                            "line": item.line,
                            "col": item.col,
                            "rule": item.rule,
                            "message": item.message,
                            "suggestion": item.suggestion,
                        }
                        for item in validation.errors
                    ],
                },
                "lookahead": {
                    "clean": lookahead.clean,
                    "findings": [
                        {
                            "line": item.line,
                            "col": item.col,
                            "rule": item.rule,
                            "severity": item.severity,
                            "message": item.message,
                            "suggestion": item.suggestion,
                        }
                        for item in lookahead.findings
                    ],
                },
                "source": "strategy_engine/dsl",
            },
            status=200,
        )

    def send_json(self, payload: dict, *, status: int) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path: Path, content_type: str) -> None:
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        message = format % args
        print(f"[{self.log_date_time_string()}] {self.address_string()} {message}", flush=True)


if __name__ == "__main__":
    assert_port_available(HOST, PORT)
    server = SandboxHTTPServer((HOST, PORT), Handler)
    print(f"Web3 research sandbox: http://{HOST}:{PORT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.", flush=True)
