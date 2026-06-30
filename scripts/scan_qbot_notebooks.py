#!/usr/bin/env python3
"""Scan vendor/Qbot notebooks for plot patterns and chapter mapping hints."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QBOT = ROOT / "vendor" / "Qbot"

PATTERNS = {
    "matplotlib": re.compile(r"plt\.|pyplot|matplotlib|figsize|subplots|savefig", re.I),
    "seaborn": re.compile(r"sns\.|seaborn", re.I),
    "backtrader_plot": re.compile(r"cerebro\.plot|bt\.plot", re.I),
    "quantstats": re.compile(r"quantstats|qs\.reports|qs\.plots|qs\.stats", re.I),
    "alphalens": re.compile(r"alphalens|create_full_tear_sheet|plot_returns|plot_ic", re.I),
    "rolling_perf": re.compile(r"rolling_sharpe|rolling_volatility|drawdown|monthly_returns", re.I),
    "pairs": re.compile(r"cointegration|spread|pairs", re.I),
    "portfolio": re.compile(r"efficient.?frontier|portfolio|kurtosis", re.I),
    "indicators": re.compile(r"macd|boll|rsi|adx|atr|sma|ema", re.I),
    "bitcoin": re.compile(r"bitcoin|btc|binance", re.I),
    "qlib": re.compile(r"qlib|workflow_by_code", re.I),
    "tushare": re.compile(r"tushare|akshare|efinance", re.I),
    "equity_curve": re.compile(r"equity|cumsum|cumprod|累计|净值", re.I),
    "three_panel": re.compile(r"signal.*shift|shift\(1\)|三|面板|subplots\(3", re.I),
}


def scan_notebook(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    md_titles: list[str] = []
    code_snippets: list[str] = []
    for cell in data.get("cells", []):
        src = "".join(cell.get("source", []))
        if cell.get("cell_type") == "markdown":
            for line in src.splitlines():
                line = line.strip()
                if line.startswith("#"):
                    md_titles.append(line.lstrip("#").strip()[:100])
        else:
            code_snippets.append(src)
    full = "\n".join(code_snippets)
    hits = {k: len(p.findall(full)) for k, p in PATTERNS.items() if p.search(full)}
    plot_calls = sorted(set(re.findall(r"(?:plt\.|ax\d?\.|sns\.)([a-z_]+)\(", full, re.I)))
    key_lines = []
    for line in full.splitlines():
        s = line.strip()
        if any(
            kw in s.lower()
            for kw in (
                "plot(",
                "subplots",
                "cerebro.plot",
                "qs.",
                "alphalens",
                "heatmap",
                "fill_between",
                "scatter",
                "bar(",
                "report",
            )
        ):
            key_lines.append(s[:120])
    return {
        "path": str(path.relative_to(QBOT)),
        "score": sum(hits.values()),
        "hits": hits,
        "titles": md_titles[:4],
        "plot_calls": plot_calls[:15],
        "key_lines": key_lines[:8],
    }


def main() -> int:
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    rows = [scan_notebook(p) for p in sorted(QBOT.rglob("*.ipynb"))]
    rows = [r for r in rows if r["score"] > 0]
    rows.sort(key=lambda r: r["score"], reverse=True)
    for r in rows:
        print(f"\n{'='*72}")
        print(f"{r['path']}  (score={r['score']})")
        if r["titles"]:
            print("  MD:", " | ".join(r["titles"]))
        print("  tags:", ", ".join(f"{k}:{v}" for k, v in sorted(r["hits"].items(), key=lambda x: -x[1])))
        if r["plot_calls"]:
            print("  fns:", ", ".join(r["plot_calls"]))
        for line in r["key_lines"]:
            print("  >", line)
    print(f"\nTotal notebooks with plots: {len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
