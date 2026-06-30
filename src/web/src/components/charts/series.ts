import type { SeriesMarker, Time } from "lightweight-charts";
import type { CurvePoint, RollingTrade, Trade } from "../../types";
import { compareChartTime, toChartTime, tsToChartDay } from "./chartTime";

export interface CandleBar {
  time: Time;
  open: number;
  high: number;
  low: number;
  close: number;
}

function curveTime(point: CurvePoint): Time {
  return toChartTime(point.date ?? point.ts);
}

export function curveToCandles(curve: CurvePoint[]): CandleBar[] {
  return curve.map((point, index) => {
    if (point.open != null && point.high != null && point.low != null) {
      return {
        time: curveTime(point),
        open: point.open,
        high: point.high,
        low: point.low,
        close: point.close,
      };
    }
    const previousClose = index > 0 ? curve[index - 1].close : point.close;
    const open = previousClose;
    const close = point.close;
    const bodySpread = Math.abs(close - open);
    const wickSpread = Math.max(bodySpread, close * 0.003);
    const high = Math.max(open, close) + wickSpread * 0.45;
    const low = Math.min(open, close) - wickSpread * 0.45;
    return {
      time: curveTime(point),
      open,
      high,
      low,
      close,
    };
  });
}

export function curveToMaSeries(curve: CurvePoint[], key: "short_ma" | "long_ma") {
  return curve
    .filter((point) => point[key] != null)
    .map((point) => ({
      time: curveTime(point),
      value: Number(point[key]),
    }));
}

export function curveToEquitySeries(curve: CurvePoint[]) {
  return curve.map((point) => ({
    time: curveTime(point),
    value: point.equity,
  }));
}

export function tradesToMarkers(trades: Trade[]): SeriesMarker<Time>[] {
  return trades
    .map((trade) => {
      const buy = trade.action.toUpperCase() === "BUY";
      return {
        time: trade.date as Time,
        position: buy ? "belowBar" : "aboveBar",
        color: buy ? "#00ffa3" : "#ff2d75",
        shape: buy ? "arrowUp" : "arrowDown",
        text: buy ? "买" : "卖",
      } satisfies SeriesMarker<Time>;
    })
    .sort((left, right) => compareChartTime(left.time, right.time));
}

/** Entry/exit markers aligned with rolling backtest trades (web3-trading style). */
export function rollingTradesToMarkers(trades: RollingTrade[]): SeriesMarker<Time>[] {
  const markers: SeriesMarker<Time>[] = [];

  trades.forEach((trade) => {
    const isLong = trade.direction === "LONG";
    markers.push({
      time: toChartTime(trade.entryTs),
      position: isLong ? "belowBar" : "aboveBar",
      color: isLong ? "#00ffa3" : "#ff2d75",
      shape: isLong ? "arrowUp" : "arrowDown",
      text: isLong ? "买" : "开空",
    });
    markers.push({
      time: toChartTime(trade.exitTs),
      position: isLong ? "aboveBar" : "belowBar",
      color: trade.pnlPct >= 0 ? "#00ffa3" : "#ff2d75",
      shape: "circle",
      text: `${trade.pnlPct >= 0 ? "+" : ""}${trade.pnlPct.toFixed(1)}%`,
    });
  });

  return markers.sort((left, right) => compareChartTime(left.time, right.time));
}

/** Ensure every trade timestamp has a bar on the curve so markers render. */
export function mergeTradeTimesIntoCurve(curve: CurvePoint[], trades: RollingTrade[]): CurvePoint[] {
  if (!curve.length || !trades.length) {
    return curve;
  }

  const byTime = new Map<number, CurvePoint>();
  curve.forEach((point) => {
    if (point.ts != null) {
      byTime.set(point.ts, point);
    }
  });

  const seed = curve[0];
  trades.forEach((trade) => {
    for (const ts of [trade.entryTs, trade.exitTs]) {
      if (byTime.has(ts)) {
        continue;
      }
      const anchor =
        [...byTime.values()].reduce((best, point) => {
          const pointTs = point.ts ?? 0;
          if (!best) {
            return point;
          }
          const bestTs = best.ts ?? 0;
          return Math.abs(pointTs - ts) < Math.abs(bestTs - ts) ? point : best;
        }, null as CurvePoint | null) ?? seed;

      byTime.set(ts, {
        date: tsToChartDay(ts),
        ts,
        close: trade.entryTs === ts ? trade.entryPrice : trade.exitPrice,
        equity: anchor.equity,
      });
    }
  });

  return [...byTime.values()].sort((left, right) => (left.ts ?? 0) - (right.ts ?? 0));
}
