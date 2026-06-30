"""Compare sandbox forks against vendor baselines to catch silent drift."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
VENDOR_WEB3 = ROOT / "vendor/web3-trading/src/backtest"
VENDOR_AI = ROOT / "vendor/ai-trading/app/strategy_engine"

STRICT_ROLLING_FILES = [
    "models.py",
    "metrics.py",
    "risk/position.py",
    "strategies/buy_and_hold.py",
    "strategies/technical_signal.py",
    "strategies/rsi_mean_reversion.py",
    "strategies/bollinger_squeeze.py",
]

FORKED_ROLLING_FILES = [
    "indicators.py",
    "hooks.py",
    "strategies/base.py",
    "strategies/ma_crossover.py",
    "strategies/macd.py",
    "strategies/macd_crossover.py",
    "strategies/boll_mean_reversion.py",
    "strategies/adx_macd_trend.py",
    "strategies/qbot_rules.py",
]

STRICT_DSL_FILES = [
    "dsl/lookahead.py",
    "dsl/validator.py",
]

FORKED_DSL_FILES = [
    "dsl/loader.py",
]


def rewrite_rolling(text: str) -> str:
    return text.replace("from backtest.", "from backtest.rolling.").replace(
        "import backtest.", "import backtest.rolling."
    )


def patch_rolling_models(text: str) -> str:
    trial_field = "    num_trials: int = 0\n"
    if trial_field in text:
        return text
    anchor = "    window_results: List[Dict[str, Any]]\n"
    if anchor not in text:
        raise RuntimeError("models.py sync output missing WalkForwardResult anchor")
    return text.replace(anchor, anchor + trial_field)


def rewrite_dsl(text: str) -> str:
    return (
        text.replace("from app.strategy_engine.", "from strategy_engine.")
        .replace("import app.strategy_engine.", "import strategy_engine.")
    )


def strip_rolling_sma_rsi_blocks(text: str) -> str:
    patterns = (
        r"\ndef _rolling_sma\(.*?\n    return result\n",
        r"\ndef _rolling_rsi\(.*?\n    return result\n",
    )
    cleaned = text
    for pattern in patterns:
        cleaned = re.sub(pattern, "\n", cleaned, flags=re.DOTALL)
    return cleaned


def patch_rolling_indicators(text: str) -> str:
    import_line = "from ta.core import rolling_rsi as _rolling_rsi, rolling_sma as _rolling_sma\n"
    patched = strip_rolling_sma_rsi_blocks(text)
    if import_line.strip() in patched:
        return patched
    anchor = "from typing import Any, Dict, List, Optional\n"
    if anchor not in patched:
        raise RuntimeError("indicators.py sync output missing typing import anchor")
    return patched.replace(anchor, anchor + "\n" + import_line)


def patch_rolling_hooks(text: str) -> str:
    if "def build_risk_hook_manager(" in text:
        return text
    patch = '''

def build_risk_hook_manager(
    *,
    max_consecutive_losses: int = 3,
    enable_regime_filter: bool = True,
) -> HookManager:
    """Register built-in risk hooks for teaching backtests."""
    manager = HookManager()
    loss_hook = max_concurrent_loss_hook(max_consecutive_losses)
    manager.register(HookEvent.POST_TRADE_EXIT, loss_hook)
    manager.register(HookEvent.PRE_TRADE_ENTRY, loss_hook)
    if enable_regime_filter:
        regime_hook = regime_filter_hook()
        manager.register(HookEvent.PRE_TRADE_ENTRY, regime_hook)
    return manager
'''
    return text.rstrip() + patch + "\n"


def compare_file(*, vendor_path: Path, sandbox_path: Path, rewrite) -> str | None:
    if not vendor_path.is_file():
        return f"missing vendor baseline: {vendor_path.relative_to(ROOT)}"
    if not sandbox_path.is_file():
        return f"missing sandbox file: {sandbox_path.relative_to(ROOT)}"

    expected = rewrite(vendor_path.read_text(encoding="utf-8"))
    actual = sandbox_path.read_text(encoding="utf-8")
    if expected != actual:
        return f"drift detected: {sandbox_path.relative_to(ROOT)}"
    return None


def main() -> int:
    errors: list[str] = []

    for rel in STRICT_ROLLING_FILES:
        issue = compare_file(
            vendor_path=VENDOR_WEB3 / rel,
            sandbox_path=SRC / "backtest/rolling" / rel,
            rewrite=patch_rolling_models if rel == "models.py" else rewrite_rolling,
        )
        if issue:
            errors.append(issue)

    for rel in STRICT_DSL_FILES:
        issue = compare_file(
            vendor_path=VENDOR_AI / rel,
            sandbox_path=SRC / "strategy_engine" / rel,
            rewrite=rewrite_dsl,
        )
        if issue:
            errors.append(issue)

    if errors:
        print("Vendor drift check failed:", file=sys.stderr)
        for item in errors:
            print(f"  - {item}", file=sys.stderr)
        print(
            "Run `python scripts/sync_rolling_backtest.py` after upstream changes, "
            "then re-apply sandbox forks.",
            file=sys.stderr,
        )
        return 1

    forked = [f"src/backtest/rolling/{rel}" for rel in FORKED_ROLLING_FILES]
    forked.extend(f"src/strategy_engine/{rel}" for rel in FORKED_DSL_FILES)
    print("Vendor drift check passed.")
    print(f"Forked (not compared): {', '.join(forked)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
