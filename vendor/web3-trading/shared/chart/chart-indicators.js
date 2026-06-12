/**
 * Shared indicator math — aligned with frontend/src/utils/indicators.ts
 */
(function (global) {
    const ChartIndicators = {
        buildMovingAverageData(candles, period, toTime) {
            if (!Array.isArray(candles) || candles.length === 0) return [];
            const result = [];
            for (let idx = 0; idx < candles.length; idx += 1) {
                if (idx < period - 1) continue;
                let sum = 0;
                for (let j = idx - period + 1; j <= idx; j += 1) sum += Number(candles[j].close || 0);
                result.push({ time: toTime(candles[idx].tsSec), value: sum / period });
            }
            return result;
        },

        buildBollingerBands(candles, toTime, period = 20, multiplier = 2) {
            if (!Array.isArray(candles) || candles.length === 0) return { upper: [], middle: [], lower: [] };
            const upper = [];
            const middle = [];
            const lower = [];
            for (let idx = 0; idx < candles.length; idx += 1) {
                if (idx < period - 1) continue;
                let sum = 0;
                for (let j = idx - period + 1; j <= idx; j += 1) sum += Number(candles[j].close || 0);
                const ma = sum / period;
                let variance = 0;
                for (let j = idx - period + 1; j <= idx; j += 1) variance += Math.pow(Number(candles[j].close || 0) - ma, 2);
                const std = Math.sqrt(variance / period);
                const t = toTime(candles[idx].tsSec);
                upper.push({ time: t, value: ma + multiplier * std });
                middle.push({ time: t, value: ma });
                lower.push({ time: t, value: ma - multiplier * std });
            }
            return { upper, middle, lower };
        },

        buildMacdData(candles, toTime, fastPeriod = 12, slowPeriod = 26, signalPeriod = 9) {
            if (!Array.isArray(candles) || candles.length === 0) return { macdLine: [], signalLine: [], histogram: [] };
            const closes = candles.map((c) => Number(c.close || 0));
            const times = candles.map((c) => toTime(c.tsSec));
            const ema = (data, period) => {
                const k = 2 / (period + 1);
                const result = [data[0]];
                for (let i = 1; i < data.length; i += 1) result.push(data[i] * k + result[i - 1] * (1 - k));
                return result;
            };
            const emaFast = ema(closes, fastPeriod);
            const emaSlow = ema(closes, slowPeriod);
            const macdVals = closes.map((_, i) => emaFast[i] - emaSlow[i]);
            const signalVals = ema(macdVals, signalPeriod);
            const macdLine = [];
            const signalLine = [];
            const histogram = [];
            for (let i = slowPeriod - 1; i < closes.length; i += 1) {
                const t = times[i];
                const histVal = macdVals[i] - signalVals[i];
                macdLine.push({ time: t, value: macdVals[i] });
                signalLine.push({ time: t, value: signalVals[i] });
                histogram.push({ time: t, value: histVal, color: global.ChartTheme.macdHistColor(histVal) });
            }
            return { macdLine, signalLine, histogram };
        },

        buildVolumeData(candles, toTime) {
            if (!Array.isArray(candles) || candles.length === 0) return [];
            return candles.map((c) => {
                const open = Number(c.open || 0);
                const close = Number(c.close || 0);
                return {
                    time: toTime(c.tsSec),
                    value: Number(c.volume || c.v || 0),
                    color: global.ChartTheme.volumeColor(close >= open),
                };
            });
        },

        buildRsiData(candles, toTime, period = 14) {
            if (!Array.isArray(candles) || candles.length <= period) return { rsi: [], upper: [], lower: [] };
            const closes = candles.map((c) => Number(c.close || 0));
            const times = candles.map((c) => toTime(c.tsSec));
            let gainSum = 0;
            let lossSum = 0;
            for (let i = 1; i <= period; i += 1) {
                const change = closes[i] - closes[i - 1];
                if (change >= 0) gainSum += change;
                else lossSum += Math.abs(change);
            }
            let avgGain = gainSum / period;
            let avgLoss = lossSum / period;
            const rsiValues = new Array(period).fill(null);
            rsiValues.push(avgLoss === 0 ? 100 : 100 - (100 / (1 + avgGain / avgLoss)));
            for (let i = period + 1; i < closes.length; i += 1) {
                const change = closes[i] - closes[i - 1];
                const currentGain = change >= 0 ? change : 0;
                const currentLoss = change < 0 ? Math.abs(change) : 0;
                avgGain = ((avgGain * (period - 1)) + currentGain) / period;
                avgLoss = ((avgLoss * (period - 1)) + currentLoss) / period;
                rsiValues.push(avgLoss === 0 ? 100 : 100 - (100 / (1 + avgGain / avgLoss)));
            }
            const rsiLine = [];
            for (let i = period; i < closes.length; i += 1) {
                if (rsiValues[i] == null || Number.isNaN(rsiValues[i])) continue;
                rsiLine.push({ time: times[i], value: rsiValues[i] });
            }
            return {
                rsi: rsiLine,
                upper: rsiLine.map((p) => ({ time: p.time, value: 70 })),
                lower: rsiLine.map((p) => ({ time: p.time, value: 30 })),
            };
        },

        buildKdjData(candles, toTime, period = 9) {
            if (!Array.isArray(candles) || candles.length < period) return { k: [], d: [], j: [] };
            const highs = candles.map((c) => Number(c.high || 0));
            const lows = candles.map((c) => Number(c.low || 0));
            const closes = candles.map((c) => Number(c.close || 0));
            const times = candles.map((c) => toTime(c.tsSec));
            const kVals = [];
            const dVals = [];
            const jVals = [];
            let lastK = 50;
            let lastD = 50;
            for (let i = 0; i < candles.length; i += 1) {
                if (i < period - 1) continue;
                let highestHigh = -Infinity;
                let lowestLow = Infinity;
                for (let j = i - period + 1; j <= i; j += 1) {
                    highestHigh = Math.max(highestHigh, highs[j]);
                    lowestLow = Math.min(lowestLow, lows[j]);
                }
                const current = closes[i];
                if (Math.abs(highestHigh - lowestLow) < 1e-9) {
                    kVals.push(lastK);
                    dVals.push(lastD);
                    jVals.push(3 * lastK - 2 * lastD);
                    continue;
                }
                const rsv = ((current - lowestLow) / (highestHigh - lowestLow)) * 100;
                const currentK = (2 / 3) * lastK + (1 / 3) * rsv;
                const currentD = (2 / 3) * lastD + (1 / 3) * currentK;
                const currentJ = 3 * currentK - 2 * currentD;
                kVals.push(currentK);
                dVals.push(currentD);
                jVals.push(currentJ);
                lastK = currentK;
                lastD = currentD;
            }
            const start = period - 1;
            const k = [];
            const d = [];
            const j = [];
            for (let i = 0; i < kVals.length; i += 1) {
                const t = times[start + i];
                k.push({ time: t, value: kVals[i] });
                d.push({ time: t, value: dVals[i] });
                j.push({ time: t, value: jVals[i] });
            }
            return { k, d, j };
        },

        normalizeCandles(candles) {
            if (!Array.isArray(candles)) return [];
            return candles.map((c) => ({
                tsSec: Number(c.tsSec || c.t / 1000 || 0),
                open: Number(c.open || c.o || 0),
                high: Number(c.high || c.h || 0),
                low: Number(c.low || c.l || 0),
                close: Number(c.close || c.c || 0),
                volume: Number(c.volume || c.v || 0),
            }));
        },
    };

    global.ChartIndicators = ChartIndicators;
})(typeof window !== "undefined" ? window : globalThis);
