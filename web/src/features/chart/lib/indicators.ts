export interface OHLCV {
  timestamp: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export function calcEMA(data: number[], period: number): (number | null)[] {
  const result: (number | null)[] = new Array(data.length).fill(null);
  if (data.length < period) return result;

  const k = 2 / (period + 1);
  let ema = 0;
  for (let i = 0; i < period; i++) ema += data[i];
  ema /= period;
  result[period - 1] = ema;

  for (let i = period; i < data.length; i++) {
    ema = data[i] * k + ema * (1 - k);
    result[i] = ema;
  }
  return result;
}

export function calcSMA(data: number[], period: number): (number | null)[] {
  const result: (number | null)[] = new Array(data.length).fill(null);
  if (data.length < period) return result;

  let sum = 0;
  for (let i = 0; i < period; i++) sum += data[i];
  result[period - 1] = sum / period;

  for (let i = period; i < data.length; i++) {
    sum += data[i] - data[i - period];
    result[i] = sum / period;
  }
  return result;
}

export function calcBB(
  data: number[],
  period: number = 20,
  mult: number = 2
): { upper: (number | null)[]; middle: (number | null)[]; lower: (number | null)[] } {
  const middle = calcSMA(data, period);
  const upper: (number | null)[] = new Array(data.length).fill(null);
  const lower: (number | null)[] = new Array(data.length).fill(null);

  for (let i = period - 1; i < data.length; i++) {
    const m = middle[i]!;
    let variance = 0;
    for (let j = i - period + 1; j <= i; j++) {
      variance += (data[j] - m) ** 2;
    }
    const std = Math.sqrt(variance / period);
    upper[i] = m + mult * std;
    lower[i] = m - mult * std;
  }
  return { upper, middle, lower };
}

export function calcRSI(closes: number[], period: number = 14): (number | null)[] {
  const n = closes.length;
  const result: (number | null)[] = new Array(n).fill(null);
  if (n <= period) return result;

  let avgGain = 0,
    avgLoss = 0;
  for (let i = 1; i <= period; i++) {
    const d = closes[i] - closes[i - 1];
    if (d > 0) avgGain += d;
    else avgLoss -= d;
  }
  avgGain /= period;
  avgLoss /= period;

  result[period] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);

  for (let i = period + 1; i < n; i++) {
    const d = closes[i] - closes[i - 1];
    avgGain = (avgGain * (period - 1) + (d > 0 ? d : 0)) / period;
    avgLoss = (avgLoss * (period - 1) + (d < 0 ? -d : 0)) / period;
    result[i] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
  }
  return result;
}

export function calcMACD(
  closes: number[],
  fast: number = 12,
  slow: number = 26,
  signal: number = 9
): {
  macd: (number | null)[];
  signal: (number | null)[];
  histogram: (number | null)[];
} {
  const emaFast = calcEMA(closes, fast);
  const emaSlow = calcEMA(closes, slow);
  const macdLine: (number | null)[] = new Array(closes.length).fill(null);

  for (let i = 0; i < closes.length; i++) {
    if (emaFast[i] !== null && emaSlow[i] !== null) {
      macdLine[i] = emaFast[i]! - emaSlow[i]!;
    }
  }

  const macdValues = macdLine.filter((v) => v !== null) as number[];
  const signalEma = calcEMA(macdValues, signal);
  const signalLine: (number | null)[] = new Array(closes.length).fill(null);
  const histogram: (number | null)[] = new Array(closes.length).fill(null);

  let idx = 0;
  for (let i = 0; i < closes.length; i++) {
    if (macdLine[i] !== null) {
      if (signalEma[idx] !== null) {
        signalLine[i] = signalEma[idx];
        histogram[i] = macdLine[i]! - signalEma[idx]!;
      }
      idx++;
    }
  }

  return { macd: macdLine, signal: signalLine, histogram };
}

export function calcATR(candles: OHLCV[], period: number = 14): (number | null)[] {
  const n = candles.length;
  const result: (number | null)[] = new Array(n).fill(null);
  if (n < 2) return result;

  const tr: number[] = [candles[0].high - candles[0].low];
  for (let i = 1; i < n; i++) {
    const c = candles[i];
    const pc = candles[i - 1].close;
    tr.push(Math.max(c.high - c.low, Math.abs(c.high - pc), Math.abs(c.low - pc)));
  }

  if (n <= period) return result;

  let atr = 0;
  for (let i = 0; i < period; i++) atr += tr[i];
  atr /= period;
  result[period - 1] = atr;

  for (let i = period; i < n; i++) {
    atr = (atr * (period - 1) + tr[i]) / period;
    result[i] = atr;
  }
  return result;
}

export function calcVWAP(candles: OHLCV[]): (number | null)[] {
  const result: (number | null)[] = [];
  let cumVolPrice = 0;
  let cumVol = 0;

  for (const c of candles) {
    const tp = (c.high + c.low + c.close) / 3;
    cumVolPrice += tp * c.volume;
    cumVol += c.volume;
    result.push(cumVol > 0 ? cumVolPrice / cumVol : null);
  }
  return result;
}

export function calcStochRSI(
  closes: number[],
  rsiPeriod: number = 14,
  stochPeriod: number = 14,
  kSmooth: number = 3,
  dSmooth: number = 3
): { k: (number | null)[]; d: (number | null)[] } {
  const rsi = calcRSI(closes, rsiPeriod);
  const n = closes.length;
  const stochRsi: (number | null)[] = new Array(n).fill(null);

  for (let i = 0; i < n; i++) {
    if (rsi[i] === null) continue;
    let min = Infinity,
      max = -Infinity;
    let valid = true;
    for (let j = i - stochPeriod + 1; j <= i; j++) {
      if (j < 0 || rsi[j] === null) {
        valid = false;
        break;
      }
      min = Math.min(min, rsi[j]!);
      max = Math.max(max, rsi[j]!);
    }
    if (valid && max !== min) {
      stochRsi[i] = ((rsi[i]! - min) / (max - min)) * 100;
    }
  }

  const kValues = smoothArray(stochRsi, kSmooth);
  const dValues = smoothArray(kValues, dSmooth);
  return { k: kValues, d: dValues };
}

function smoothArray(data: (number | null)[], period: number): (number | null)[] {
  const result: (number | null)[] = new Array(data.length).fill(null);
  for (let i = 0; i < data.length; i++) {
    let sum = 0,
      count = 0;
    for (let j = i - period + 1; j <= i; j++) {
      if (j >= 0 && data[j] !== null) {
        sum += data[j]!;
        count++;
      }
    }
    if (count === period) result[i] = sum / period;
  }
  return result;
}

export function calcCCI(candles: OHLCV[], period: number = 20): (number | null)[] {
  const n = candles.length;
  const result: (number | null)[] = new Array(n).fill(null);
  const tp = candles.map((c) => (c.high + c.low + c.close) / 3);

  for (let i = period - 1; i < n; i++) {
    let sum = 0;
    for (let j = i - period + 1; j <= i; j++) sum += tp[j];
    const mean = sum / period;

    let meanDev = 0;
    for (let j = i - period + 1; j <= i; j++) meanDev += Math.abs(tp[j] - mean);
    meanDev /= period;

    result[i] = meanDev === 0 ? 0 : (tp[i] - mean) / (0.015 * meanDev);
  }
  return result;
}

export function calcADX(candles: OHLCV[], period: number = 14): (number | null)[] {
  const n = candles.length;
  const result: (number | null)[] = new Array(n).fill(null);
  if (n < period * 2) return result;

  const tr: number[] = [];
  const plusDM: number[] = [];
  const minusDM: number[] = [];

  for (let i = 1; i < n; i++) {
    const h = candles[i].high,
      l = candles[i].low,
      pc = candles[i - 1].close;
    const ph = candles[i - 1].high,
      pl = candles[i - 1].low;
    tr.push(Math.max(h - l, Math.abs(h - pc), Math.abs(l - pc)));
    const upMove = h - ph;
    const downMove = pl - l;
    plusDM.push(upMove > downMove && upMove > 0 ? upMove : 0);
    minusDM.push(downMove > upMove && downMove > 0 ? downMove : 0);
  }

  let atr = 0,
    aPlusDM = 0,
    aMinusDM = 0;
  for (let i = 0; i < period; i++) {
    atr += tr[i];
    aPlusDM += plusDM[i];
    aMinusDM += minusDM[i];
  }

  const dx: number[] = [];
  const calcDX = () => {
    const plusDI = atr === 0 ? 0 : (aPlusDM / atr) * 100;
    const minusDI = atr === 0 ? 0 : (aMinusDM / atr) * 100;
    const sum = plusDI + minusDI;
    return sum === 0 ? 0 : (Math.abs(plusDI - minusDI) / sum) * 100;
  };

  dx.push(calcDX());

  for (let i = period; i < tr.length; i++) {
    atr = atr - atr / period + tr[i];
    aPlusDM = aPlusDM - aPlusDM / period + plusDM[i];
    aMinusDM = aMinusDM - aMinusDM / period + minusDM[i];
    dx.push(calcDX());
  }

  if (dx.length < period) return result;

  let adx = 0;
  for (let i = 0; i < period; i++) adx += dx[i];
  adx /= period;
  result[period * 2 - 1] = adx;

  for (let i = period; i < dx.length; i++) {
    adx = (adx * (period - 1) + dx[i]) / period;
    result[period + i] = adx;
  }
  return result;
}

export function calcWilliamsR(candles: OHLCV[], period: number = 14): (number | null)[] {
  const n = candles.length;
  const result: (number | null)[] = new Array(n).fill(null);

  for (let i = period - 1; i < n; i++) {
    let high = -Infinity,
      low = Infinity;
    for (let j = i - period + 1; j <= i; j++) {
      high = Math.max(high, candles[j].high);
      low = Math.min(low, candles[j].low);
    }
    result[i] = high === low ? 0 : ((high - candles[i].close) / (high - low)) * -100;
  }
  return result;
}

export function calcMFI(candles: OHLCV[], period: number = 14): (number | null)[] {
  const n = candles.length;
  const result: (number | null)[] = new Array(n).fill(null);
  if (n < period + 1) return result;

  const tp = candles.map((c) => (c.high + c.low + c.close) / 3);

  for (let i = period; i < n; i++) {
    let posFlow = 0,
      negFlow = 0;
    for (let j = i - period + 1; j <= i; j++) {
      const flow = tp[j] * candles[j].volume;
      if (tp[j] > tp[j - 1]) posFlow += flow;
      else negFlow += flow;
    }
    result[i] = negFlow === 0 ? 100 : 100 - 100 / (1 + posFlow / negFlow);
  }
  return result;
}

export function calcOBV(candles: OHLCV[]): (number | null)[] {
  const result: (number | null)[] = [0];
  let obv = 0;
  for (let i = 1; i < candles.length; i++) {
    if (candles[i].close > candles[i - 1].close) obv += candles[i].volume;
    else if (candles[i].close < candles[i - 1].close) obv -= candles[i].volume;
    result.push(obv);
  }
  return result;
}

export function calcSuperTrend(
  candles: OHLCV[],
  period: number = 10,
  multiplier: number = 3
): { value: (number | null)[]; direction: number[] } {
  const atr = calcATR(candles, period);
  const n = candles.length;
  const value: (number | null)[] = new Array(n).fill(null);
  const direction: number[] = new Array(n).fill(1);

  let upperBand = 0,
    lowerBand = 0;
  let prevUpper = 0,
    prevLower = 0;

  for (let i = period - 1; i < n; i++) {
    if (atr[i] === null) continue;
    const hl2 = (candles[i].high + candles[i].low) / 2;
    const basicUpper = hl2 + multiplier * atr[i]!;
    const basicLower = hl2 - multiplier * atr[i]!;

    upperBand =
      i === period - 1
        ? basicUpper
        : basicUpper < prevUpper || candles[i - 1].close > prevUpper
          ? basicUpper
          : prevUpper;
    lowerBand =
      i === period - 1
        ? basicLower
        : basicLower > prevLower || candles[i - 1].close < prevLower
          ? basicLower
          : prevLower;

    if (i === period - 1) {
      direction[i] = candles[i].close > upperBand ? 1 : -1;
    } else {
      if (direction[i - 1] === 1) {
        direction[i] = candles[i].close < lowerBand ? -1 : 1;
      } else {
        direction[i] = candles[i].close > upperBand ? 1 : -1;
      }
    }

    value[i] = direction[i] === 1 ? lowerBand : upperBand;
    prevUpper = upperBand;
    prevLower = lowerBand;
  }

  return { value, direction };
}

export function calcParabolicSAR(
  candles: OHLCV[],
  step: number = 0.02,
  max: number = 0.2
): { value: (number | null)[]; direction: number[] } {
  const n = candles.length;
  const value: (number | null)[] = new Array(n).fill(null);
  const direction: number[] = new Array(n).fill(1);
  if (n < 2) return { value, direction };

  let isLong = candles[1].close > candles[0].close;
  let af = step;
  let ep = isLong ? candles[0].high : candles[0].low;
  let sar = isLong ? candles[0].low : candles[0].high;

  value[0] = sar;
  direction[0] = isLong ? 1 : -1;

  for (let i = 1; i < n; i++) {
    const prevSar = sar;
    sar = prevSar + af * (ep - prevSar);

    if (isLong) {
      sar = Math.min(sar, candles[i - 1].low, i > 1 ? candles[i - 2].low : candles[i - 1].low);
      if (candles[i].low < sar) {
        isLong = false;
        sar = ep;
        ep = candles[i].low;
        af = step;
      } else {
        if (candles[i].high > ep) {
          ep = candles[i].high;
          af = Math.min(af + step, max);
        }
      }
    } else {
      sar = Math.max(sar, candles[i - 1].high, i > 1 ? candles[i - 2].high : candles[i - 1].high);
      if (candles[i].high > sar) {
        isLong = true;
        sar = ep;
        ep = candles[i].high;
        af = step;
      } else {
        if (candles[i].low < ep) {
          ep = candles[i].low;
          af = Math.min(af + step, max);
        }
      }
    }

    value[i] = sar;
    direction[i] = isLong ? 1 : -1;
  }

  return { value, direction };
}

export function calcIchimoku(
  candles: OHLCV[],
  tenkan: number = 9,
  kijun: number = 26,
  senkou: number = 52
): {
  tenkanSen: (number | null)[];
  kijunSen: (number | null)[];
  senkouA: (number | null)[];
  senkouB: (number | null)[];
} {
  const n = candles.length;
  const tenkanSen: (number | null)[] = new Array(n).fill(null);
  const kijunSen: (number | null)[] = new Array(n).fill(null);
  const senkouA: (number | null)[] = new Array(n).fill(null);
  const senkouB: (number | null)[] = new Array(n).fill(null);

  const midpoint = (start: number, period: number): number | null => {
    if (start - period + 1 < 0) return null;
    let high = -Infinity,
      low = Infinity;
    for (let j = start - period + 1; j <= start; j++) {
      high = Math.max(high, candles[j].high);
      low = Math.min(low, candles[j].low);
    }
    return (high + low) / 2;
  };

  for (let i = 0; i < n; i++) {
    tenkanSen[i] = midpoint(i, tenkan);
    kijunSen[i] = midpoint(i, kijun);

    // Senkou spans are plotted 26 periods ahead, but we calculate from current
    if (tenkanSen[i] !== null && kijunSen[i] !== null) {
      const aIdx = i + kijun;
      if (aIdx < n) senkouA[aIdx] = (tenkanSen[i]! + kijunSen[i]!) / 2;
    }
    const sb = midpoint(i, senkou);
    if (sb !== null) {
      const bIdx = i + kijun;
      if (bIdx < n) senkouB[bIdx] = sb;
    }
  }

  return { tenkanSen, kijunSen, senkouA, senkouB };
}

export interface SRLevel {
  price: number;
  strength: number; // number of touches
  type: "support" | "resistance";
}

/**
 * Detects support/resistance zones by finding price levels
 * where highs/lows cluster (multiple touches within a tolerance).
 */
export function detectSupportResistance(
  candles: OHLCV[],
  maxLevels: number = 5
): SRLevel[] {
  const n = candles.length;
  if (n < 5) return [];

  const currentPrice = candles[n - 1].close;

  // Use ATR for adaptive zone tolerance
  const atr = calcATR(candles, 14);
  const lastAtr = [...atr].reverse().find((v): v is number => v !== null) ?? (currentPrice * 0.005);
  const tolerance = lastAtr * 0.5;

  // Collect swing highs and swing lows (local extremes)
  const pivots: { price: number; type: "high" | "low" }[] = [];
  const lookback = 3;

  for (let i = lookback; i < n - lookback; i++) {
    let isHigh = true;
    let isLow = true;

    for (let j = 1; j <= lookback; j++) {
      if (candles[i].high <= candles[i - j].high || candles[i].high <= candles[i + j].high) {
        isHigh = false;
      }
      if (candles[i].low >= candles[i - j].low || candles[i].low >= candles[i + j].low) {
        isLow = false;
      }
    }

    if (isHigh) pivots.push({ price: candles[i].high, type: "high" });
    if (isLow) pivots.push({ price: candles[i].low, type: "low" });
  }

  if (pivots.length === 0) return [];

  // Cluster nearby pivots into zones
  const sorted = [...pivots].sort((a, b) => a.price - b.price);
  const zones: { price: number; touches: number; types: Set<string> }[] = [];

  for (const p of sorted) {
    const existing = zones.find((z) => Math.abs(z.price - p.price) <= tolerance);
    if (existing) {
      // Weighted average to refine the zone center
      existing.price = (existing.price * existing.touches + p.price) / (existing.touches + 1);
      existing.touches++;
      existing.types.add(p.type);
    } else {
      zones.push({ price: p.price, touches: 1, types: new Set([p.type]) });
    }
  }

  // Filter: need at least 2 touches to be a valid S/R level
  const valid = zones.filter((z) => z.touches >= 2);

  // Sort by strength (touches), take top N
  valid.sort((a, b) => b.touches - a.touches);
  const top = valid.slice(0, maxLevels);

  // Classify as support or resistance relative to current price
  return top.map((z) => ({
    price: z.price,
    strength: z.touches,
    type: z.price < currentPrice ? "support" : "resistance",
  }));
}
