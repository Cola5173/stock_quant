import type { KlineBar } from "./types";

export interface ChipBin {
  price: number;
  volume: number;
}

export interface ChipResult {
  bins: ChipBin[];
  profitRatio: number;
  avgCost: number;
}

export function calcChipDistribution(
  bars: KlineBar[],
  currentPrice: number,
  binCount: number = 80,
  decay: number = 0.97
): ChipResult {
  if (!bars.length) return { bins: [], profitRatio: 0, avgCost: 0 };

  let minPrice = Infinity;
  let maxPrice = -Infinity;
  for (const bar of bars) {
    if (bar.low < minPrice) minPrice = bar.low;
    if (bar.high > maxPrice) maxPrice = bar.high;
  }

  const range = maxPrice - minPrice;
  if (range <= 0) return { bins: [], profitRatio: 0, avgCost: 0 };

  const binSize = range / binCount;
  const volumes = new Float64Array(binCount);

  for (let i = 0; i < bars.length; i++) {
    const bar = bars[i];
    const weight = Math.pow(decay, bars.length - 1 - i);
    const barRange = bar.high - bar.low;

    if (barRange <= 0) {
      const idx = Math.min(Math.floor((bar.close - minPrice) / binSize), binCount - 1);
      volumes[idx] += bar.volume * weight;
      continue;
    }

    const startBin = Math.max(0, Math.floor((bar.low - minPrice) / binSize));
    const endBin = Math.min(binCount - 1, Math.floor((bar.high - minPrice) / binSize));

    const volPerBin = (bar.volume * weight) / (endBin - startBin + 1);
    for (let b = startBin; b <= endBin; b++) {
      volumes[b] += volPerBin;
    }
  }

  const bins: ChipBin[] = [];
  let profitVol = 0;
  let totalVol = 0;
  let costSum = 0;

  for (let i = 0; i < binCount; i++) {
    const price = minPrice + (i + 0.5) * binSize;
    bins.push({ price, volume: volumes[i] });
    totalVol += volumes[i];
    costSum += volumes[i] * price;
    if (price <= currentPrice) {
      profitVol += volumes[i];
    }
  }

  const profitRatio = totalVol > 0 ? profitVol / totalVol : 0;
  const avgCost = totalVol > 0 ? costSum / totalVol : 0;

  return { bins, profitRatio, avgCost };
}
