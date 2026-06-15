"""One-off sync of web3-trading rolling backtest modules into src/backtest/rolling/."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "vendor/web3-trading/src/backtest"
DST = ROOT / "src/backtest/rolling"

FILES = [
    "models.py",
    "indicators.py",
    "metrics.py",
    "hooks.py",
    "risk/position.py",
    "strategies/base.py",
    "strategies/buy_and_hold.py",
    "strategies/ma_crossover.py",
    "strategies/technical_signal.py",
    "strategies/rsi_mean_reversion.py",
    "strategies/macd.py",
    "strategies/bollinger_squeeze.py",
]


def rewrite(text: str) -> str:
    return text.replace("from backtest.", "from backtest.rolling.").replace(
        "import backtest.", "import backtest.rolling."
    )


def main() -> None:
    for rel in FILES:
        src = SRC / rel
        dst = DST / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(rewrite(src.read_text(encoding="utf-8")), encoding="utf-8")

    engine_src = (SRC / "engine.py").read_text(encoding="utf-8")
    marker = "# ---------------------------------------------------------------------------\n# High-level entry point"
    engine_body = rewrite(engine_src[: engine_src.index(marker)])
    engine_body = engine_body.replace(
        "from backtest.rolling.cache import cache_get, cache_put\n", ""
    )
    (DST / "engine.py").write_text(engine_body, encoding="utf-8")

    registry = '''# -*- coding: utf-8 -*-
"""Strategy registry adapted from web3-trading."""
from __future__ import annotations

import logging
from typing import Dict, List

from backtest.rolling.strategies.base import Strategy

logger = logging.getLogger(__name__)
STRATEGY_REGISTRY: Dict[str, Strategy] = {}
_loaded = False


def register(cls: type) -> type:
    instance = cls()
    STRATEGY_REGISTRY[instance.name] = instance
    return cls


def get_strategy(name: str) -> Strategy:
    _ensure_loaded()
    return STRATEGY_REGISTRY.get(name, STRATEGY_REGISTRY["technical_signal"])


def list_strategies() -> List[dict[str, str]]:
    _ensure_loaded()
    return [
        {"name": s.name, "displayName": s.display_name}
        for s in STRATEGY_REGISTRY.values()
    ]


def _ensure_loaded() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    from backtest.rolling.strategies.bollinger_squeeze import BollingerSqueezeStrategy
    from backtest.rolling.strategies.buy_and_hold import BuyAndHoldStrategy
    from backtest.rolling.strategies.ma_crossover import MACrossoverStrategy
    from backtest.rolling.strategies.macd import MACDStrategy
    from backtest.rolling.strategies.rsi_mean_reversion import RSIMeanReversionStrategy
    from backtest.rolling.strategies.technical_signal import TechnicalSignalStrategy

    for cls in [
        TechnicalSignalStrategy,
        MACrossoverStrategy,
        RSIMeanReversionStrategy,
        MACDStrategy,
        BollingerSqueezeStrategy,
        BuyAndHoldStrategy,
    ]:
        register(cls)
'''
    (DST / "registry.py").write_text(registry, encoding="utf-8")

    for rel in ("", "risk", "strategies"):
        init_path = DST / rel / "__init__.py" if rel else DST / "__init__.py"
        if not init_path.exists():
            init_path.write_text("", encoding="utf-8")

    print(f"synced {len(list(DST.rglob('*.py')))} files into {DST}")


if __name__ == "__main__":
    main()
