import type { KlineBar } from "./types";

export interface NWavePoint {
  date: string;
  price: number;
  type: "H" | "L";
}

function calcAdaptiveThreshold(bars: KlineBar[]): number {
  let sumRange = 0;
  for (const bar of bars) {
    sumRange += (bar.high - bar.low) / bar.close;
  }
  const avgDailyRange = sumRange / bars.length;
  const t = avgDailyRange * 5;
  return Math.max(0.025, Math.min(0.08, t));
}

export function detectNWave(bars: KlineBar[], threshold?: number): NWavePoint[] {
  if (bars.length < 5) return [];

  const t = threshold ?? calcAdaptiveThreshold(bars);

  const points: NWavePoint[] = [];
  let trend: "up" | "down" | null = null;
  let pivotIdx = 0;
  let pivotHigh = bars[0].high;
  let pivotHighIdx = 0;
  let pivotLow = bars[0].low;
  let pivotLowIdx = 0;

  for (let i = 1; i < bars.length; i++) {
    const bar = bars[i];

    if (trend === null) {
      if (bar.high > pivotHigh) {
        pivotHigh = bar.high;
        pivotHighIdx = i;
      }
      if (bar.low < pivotLow) {
        pivotLow = bar.low;
        pivotLowIdx = i;
      }
      if (pivotHighIdx > pivotLowIdx && (pivotHigh - pivotLow) / pivotLow >= t) {
        points.push({ date: bars[pivotLowIdx].date, price: pivotLow, type: "L" });
        trend = "up";
        pivotIdx = pivotHighIdx;
      } else if (pivotLowIdx > pivotHighIdx && (pivotHigh - pivotLow) / pivotHigh >= t) {
        points.push({ date: bars[pivotHighIdx].date, price: pivotHigh, type: "H" });
        trend = "down";
        pivotIdx = pivotLowIdx;
      }
      continue;
    }

    if (trend === "up") {
      if (bar.high > pivotHigh) {
        pivotHigh = bar.high;
        pivotIdx = i;
      }
      const drop = (pivotHigh - bar.low) / pivotHigh;
      if (drop >= t) {
        points.push({ date: bars[pivotIdx].date, price: pivotHigh, type: "H" });
        trend = "down";
        pivotLow = bar.low;
        pivotIdx = i;
      }
    } else {
      if (bar.low < pivotLow) {
        pivotLow = bar.low;
        pivotIdx = i;
      }
      const rise = (bar.high - pivotLow) / pivotLow;
      if (rise >= t) {
        points.push({ date: bars[pivotIdx].date, price: pivotLow, type: "L" });
        trend = "up";
        pivotHigh = bar.high;
        pivotIdx = i;
      }
    }
  }

  const merged: NWavePoint[] = [];
  for (const p of points) {
    if (merged.length === 0) {
      merged.push(p);
      continue;
    }
    const last = merged[merged.length - 1];
    if (last.type === p.type) {
      if (p.type === "H" && p.price > last.price) {
        merged[merged.length - 1] = p;
      } else if (p.type === "L" && p.price < last.price) {
        merged[merged.length - 1] = p;
      }
    } else {
      merged.push(p);
    }
  }

  return merged;
}
