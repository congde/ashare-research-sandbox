import type { SeriesMarker, Time } from "lightweight-charts";
import type { CurvePoint, Trade } from "../../types";

export interface CandleBar {
  time: Time;
  open: number;
  high: number;
  low: number;
  close: number;
}

export function curveToCandles(curve: CurvePoint[]): CandleBar[] {
  return curve.map((point, index) => {
    const previousClose = index > 0 ? curve[index - 1].close : point.close;
    const open = previousClose;
    const close = point.close;
    const bodySpread = Math.abs(close - open);
    const wickSpread = Math.max(bodySpread, close * 0.003);
    const high = Math.max(open, close) + wickSpread * 0.45;
    const low = Math.min(open, close) - wickSpread * 0.45;
    return {
      time: point.date as Time,
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
      time: point.date as Time,
      value: Number(point[key]),
    }));
}

export function curveToEquitySeries(curve: CurvePoint[]) {
  return curve.map((point) => ({
    time: point.date as Time,
    value: point.equity,
  }));
}

export function tradesToMarkers(trades: Trade[]): SeriesMarker<Time>[] {
  return trades.flatMap((trade) => {
    const buy = trade.action.toUpperCase() === "BUY";
    return [
      {
        time: trade.date as Time,
        position: buy ? "belowBar" : "aboveBar",
        color: buy ? "#00ffa3" : "#ff2d75",
        shape: buy ? "arrowUp" : "arrowDown",
        text: buy ? "买" : "卖",
      } satisfies SeriesMarker<Time>,
    ];
  });
}
