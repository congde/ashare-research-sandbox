"""K线技术指标计算工具函数（numpy 实现，无重量级依赖）。"""

from __future__ import annotations

from typing import Optional

import numpy as np

from ..models import KlineFrame, KlineSnapshot

# timeframe → KlineSnapshot 属性名映射
_TF_ATTR = {"15m": "tf_15m", "1h": "tf_1h", "4h": "tf_4h", "1d": "tf_1d"}


def _snapshot_frame(snapshot: KlineSnapshot, timeframe: str) -> Optional[KlineFrame]:
    attr = _TF_ATTR.get(timeframe)
    return getattr(snapshot, attr) if attr else None


def ema(data: np.ndarray, period: int) -> np.ndarray:
    """指数移动平均。"""
    if len(data) < period:
        return np.full_like(data, np.nan)
    alpha = 2.0 / (period + 1)
    result = np.full_like(data, np.nan)

    # 找到第一个连续 period 个非 NaN 的窗口作为种子
    valid = ~np.isnan(data)
    seed_pos = -1
    for i in range(period - 1, len(data)):
        if np.all(valid[i - period + 1:i + 1]):
            seed_pos = i
            break
    if seed_pos < 0:
        return result

    result[seed_pos] = np.mean(data[seed_pos - period + 1:seed_pos + 1])
    for i in range(seed_pos + 1, len(data)):
        result[i] = alpha * data[i] + (1 - alpha) * result[i - 1]
    return result


def sma(data: np.ndarray, period: int) -> np.ndarray:
    """简单移动平均。"""
    if len(data) < period:
        return np.full_like(data, np.nan)
    result = np.full_like(data, np.nan)
    cumsum = np.cumsum(np.insert(data, 0, 0))
    result[period - 1:] = (cumsum[period:] - cumsum[:-period]) / period
    return result


def rsi(close: np.ndarray, period: int = 14) -> np.ndarray:
    """相对强弱指数 RSI。"""
    if len(close) < period + 1:
        return np.full_like(close, np.nan)
    delta = np.diff(close)
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    avg_gain = np.full(len(close), np.nan)
    avg_loss = np.full(len(close), np.nan)
    avg_gain[period] = np.mean(gain[:period])
    avg_loss[period] = np.mean(loss[:period])
    for i in range(period + 1, len(close)):
        avg_gain[i] = (avg_gain[i - 1] * (period - 1) + gain[i - 1]) / period
        avg_loss[i] = (avg_loss[i - 1] * (period - 1) + loss[i - 1]) / period
    rs = avg_gain / np.where(avg_loss == 0, 1e-10, avg_loss)
    return 100.0 - (100.0 / (1.0 + rs))


def macd(close: np.ndarray, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """MACD 指标。
    Returns: (macd_line, signal_line, histogram)
    """
    ema_fast = ema(close, fast)
    ema_slow = ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def adx(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    """平均趋向指数 ADX。"""
    n = len(close)
    if n < period + 1:
        return np.full(n, np.nan)

    tr = np.zeros(n)
    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)

    for i in range(1, n):
        hl = high[i] - low[i]
        hc = abs(high[i] - close[i - 1])
        lc = abs(low[i] - close[i - 1])
        tr[i] = max(hl, hc, lc)
        up_move = high[i] - high[i - 1]
        down_move = low[i - 1] - low[i]
        if up_move > down_move and up_move > 0:
            plus_dm[i] = up_move
        if down_move > up_move and down_move > 0:
            minus_dm[i] = down_move

    atr_val = ema(tr, period)
    plus_di = np.full(n, np.nan)
    minus_di = np.full(n, np.nan)
    for i in range(period, n):
        plus_di[i] = 100.0 * ema(plus_dm, period)[i] / max(atr_val[i], 1e-10)
        minus_di[i] = 100.0 * ema(minus_dm, period)[i] / max(atr_val[i], 1e-10)

    dx = np.full(n, np.nan)
    for i in range(period, n):
        denom = plus_di[i] + minus_di[i]
        dx[i] = 100.0 * abs(plus_di[i] - minus_di[i]) / max(denom, 1e-10)

    return ema(dx, period)


def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    """平均真实波幅 ATR。"""
    n = len(close)
    if n < 2:
        return np.full(n, np.nan)
    tr = np.zeros(n)
    for i in range(1, n):
        hl = high[i] - low[i]
        hc = abs(high[i] - close[i - 1])
        lc = abs(low[i] - close[i - 1])
        tr[i] = max(hl, hc, lc)
    return ema(tr, period)


def bollinger_bands(close: np.ndarray, period: int = 20, num_std: float = 2.0) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """布林带。
    Returns: (middle, upper, lower)
    """
    middle = sma(close, period)
    std = np.full_like(close, np.nan)
    for i in range(period - 1, len(close)):
        std[i] = np.std(close[i - period + 1:i + 1], ddof=1)
    upper = middle + num_std * std
    lower = middle - num_std * std
    return middle, upper, lower


def vwap(close: np.ndarray, volume: np.ndarray, period: int = 24) -> np.ndarray:
    """滚动成交量加权均价 VWAP。"""
    n = len(close)
    if n < period:
        return np.full(n, np.nan)
    result = np.full(n, np.nan)
    pv = close * volume
    for i in range(period - 1, n):
        result[i] = np.sum(pv[i - period + 1:i + 1]) / max(np.sum(volume[i - period + 1:i + 1]), 1e-10)
    return result


def log_returns(close: np.ndarray, lookback: int) -> np.ndarray:
    """对数收益率，间隔 lookback 根K线。"""
    n = len(close)
    if n <= lookback:
        return np.full(n, np.nan)
    result = np.full(n, np.nan)
    result[lookback:] = np.log(close[lookback:] / close[:-lookback])
    return result


def rolling_volatility(close: np.ndarray, period: int = 20, annualize_factor: float = 1.0) -> np.ndarray:
    """滚动对数收益率波动率。"""
    lr = np.diff(np.log(close))
    if len(lr) < period:
        return np.full(len(close), np.nan)
    vol = np.full(len(close), np.nan)
    for i in range(period, len(lr) + 1):
        vol[i] = np.std(lr[i - period:i], ddof=1) * np.sqrt(annualize_factor)
    return vol


def rolling_percentile(data: np.ndarray, window: int) -> np.ndarray:
    """滚动分位数（当前值在滚动窗口中的分位）。"""
    n = len(data)
    if n < window:
        return np.full(n, np.nan)
    result = np.full(n, np.nan)
    for i in range(window - 1, n):
        window_data = data[i - window + 1:i + 1]
        result[i] = np.sum(window_data <= data[i]) / len(window_data)
    return result


def get_kline_column(klines: KlineSnapshot, timeframe: str, column: str) -> np.ndarray | None:
    """从 K线快照中提取指定周期的列数据。"""
    if isinstance(klines, KlineSnapshot):
        frame = _snapshot_frame(klines, timeframe)
        if frame is None:
            return None
        arr = getattr(frame, column, None)
        if arr is None or len(arr) == 0:
            return None
        return np.asarray(arr, dtype=np.float64)

    return None
