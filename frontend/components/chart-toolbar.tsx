"use client";

import { useMemo } from "react";
import { StockSearchBar } from "./stock-search-bar";
import type { StockItem, KlineBar } from "@/lib/types";

type Granularity = "day" | "week";
type TimeRange = "quarter" | "6m" | "1y" | "custom";

const GRANULARITY_LABELS: { key: Granularity; label: string }[] = [
  { key: "day", label: "日" },
  { key: "week", label: "周" },
];

const RANGE_LABELS: { key: TimeRange; label: string }[] = [
  { key: "quarter", label: "季度" },
  { key: "6m", label: "半年" },
  { key: "1y", label: "1年" },
  { key: "custom", label: "自定义" },
];

interface ChartToolbarProps {
  stock: StockItem;
  bars: KlineBar[];
  granularity: Granularity;
  timeRange: TimeRange;
  nWaveEnabled: boolean;
  onSelectStock: (stock: StockItem) => void;
  onGranularityChange: (g: Granularity) => void;
  onTimeRangeChange: (r: TimeRange) => void;
  onNWaveToggle: () => void;
}

export type { Granularity, TimeRange };

export function ChartToolbar({ stock, bars, granularity, timeRange, nWaveEnabled, onSelectStock, onGranularityChange, onTimeRangeChange, onNWaveToggle }: ChartToolbarProps) {
  const quote = useMemo(() => {
    if (!bars || bars.length < 2) return null;
    const latest = bars[bars.length - 1];
    const prev = bars[bars.length - 2];
    const change = latest.close - prev.close;
    const changePercent = (change / prev.close) * 100;
    return { price: latest.close, change, changePercent };
  }, [bars]);

  const changeColor = quote
    ? quote.change > 0 ? "text-red-500" : quote.change < 0 ? "text-green-500" : "text-zinc-400"
    : "text-zinc-400";

  return (
    <div className="flex items-center gap-4 h-10">
      {/* 搜索框 */}
      <StockSearchBar onSelect={onSelectStock} />

      {/* 股票信息 */}
      <div className="flex items-center gap-3 min-w-0">
        <span className="text-sm font-medium text-zinc-200 whitespace-nowrap">{stock.name}</span>
        <span className="text-xs text-zinc-500 whitespace-nowrap">{stock.code.replace("idx_", "").replace("_", ".")}</span>
        {quote && (
          <>
            <span className={`text-lg font-semibold ${changeColor} whitespace-nowrap`}>
              {quote.price.toFixed(2)}
            </span>
            <span className={`text-sm ${changeColor} whitespace-nowrap`}>
              {quote.changePercent >= 0 ? "+" : ""}{quote.changePercent.toFixed(2)}%
            </span>
            <span className={`text-sm ${changeColor} whitespace-nowrap`}>
              {quote.change >= 0 ? "+" : ""}{quote.change.toFixed(2)}
            </span>
          </>
        )}
      </div>

      {/* 右侧：粒度 + 时间范围 */}
      <div className="ml-auto flex items-center gap-1">
        {GRANULARITY_LABELS.map(({ key, label }) => (
          <button
            key={key}
            onClick={() => onGranularityChange(key)}
            className={`px-2.5 py-1 text-xs rounded transition-colors ${
              granularity === key
                ? "bg-blue-600 text-white"
                : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800"
            }`}
          >
            {label}
          </button>
        ))}
        <span className="w-px h-4 bg-zinc-700 mx-1" />
        {RANGE_LABELS.map(({ key, label }) => (
          <button
            key={key}
            onClick={() => onTimeRangeChange(key)}
            className={`px-2.5 py-1 text-xs rounded transition-colors ${
              timeRange === key
                ? "bg-blue-600 text-white"
                : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800"
            }`}
          >
            {label}
          </button>
        ))}
        <span className="w-px h-4 bg-zinc-700 mx-1" />
        <button
          onClick={onNWaveToggle}
          className={`px-2.5 py-1 text-xs rounded transition-colors ${
            nWaveEnabled
              ? "bg-blue-600 text-white"
              : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800"
          }`}
        >
          N型波段
        </button>
      </div>
    </div>
  );
}

export function aggregateToWeekly(bars: KlineBar[]): KlineBar[] {
  if (!bars.length) return [];
  const weeks: KlineBar[] = [];
  let current: KlineBar | null = null;

  for (const bar of bars) {
    const d = new Date(bar.date);
    const dow = d.getDay();
    if (!current || dow === 1 || d.getTime() - new Date(current.date).getTime() > 6 * 86400000) {
      if (current) weeks.push(current);
      current = { ...bar };
    } else {
      current.high = Math.max(current.high, bar.high);
      current.low = Math.min(current.low, bar.low);
      current.close = bar.close;
      current.volume += bar.volume;
      current.date = bar.date;
    }
  }
  if (current) weeks.push(current);
  return weeks;
}
