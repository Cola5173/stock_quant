"use client";

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, Play, Search } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { BacktestRequest, StockItem } from "@/lib/types";

export interface BacktestParams {
  strategy: string;
  code: string;
  start: string;
  end: string;
  capital: number;
  selectedStock: StockItem | null;
}

const PERIOD_OPTIONS = [
  { key: "1y", label: "近1年", years: 1 },
  { key: "2y", label: "近2年", years: 2 },
  { key: "3y", label: "近3年", years: 3 },
] as const;

export function BacktestPanel({
  onSubmit,
  onParamsChange,
  isPending,
}: {
  onSubmit: (req: BacktestRequest) => void;
  onParamsChange: (p: BacktestParams) => void;
  isPending: boolean;
}) {
  const today = new Date().toISOString().slice(0, 10);
  const yearsAgo = (n: number) => {
    const d = new Date();
    d.setFullYear(d.getFullYear() - n);
    return d.toISOString().slice(0, 10);
  };

  const { data: stocks = [] } = useQuery({ queryKey: ["stocks"], queryFn: api.stocks });
  const { data: strategies = [] } = useQuery({ queryKey: ["strategies"], queryFn: api.strategies });

  const [strategy, setStrategy] = useState("b1");
  const [stockSearch, setStockSearch] = useState("");
  const [stockOpen, setStockOpen] = useState(false);
  const [selectedStock, setSelectedStock] = useState<StockItem | null>(null);
  const [period, setPeriod] = useState<"1y" | "2y" | "3y">("1y");
  const [capitalW, setCapitalW] = useState(10);

  const filteredStocks = useMemo(() => {
    if (!stockSearch) return stocks.slice(0, 30);
    const q = stockSearch.toLowerCase();
    return stocks.filter((s) =>
      s.code.includes(q) || s.name.toLowerCase().includes(q)
    ).slice(0, 30);
  }, [stocks, stockSearch]);

  const { start, end } = useMemo(() => {
    const years = PERIOD_OPTIONS.find((p) => p.key === period)?.years ?? 1;
    return { start: yearsAgo(years), end: today };
  }, [period, today]);

  const code = selectedStock?.code ?? "";

  // 同步参数到父级（用于预览 K 线）
  useEffect(() => {
    onParamsChange({ strategy, code, start, end, capital: capitalW * 10000, selectedStock });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [strategy, code, start, end, capitalW]);

  const canSubmit = !!selectedStock && !isPending;

  return (
    <div className="bg-zinc-900/50 rounded-lg border border-zinc-800 p-4 space-y-5">
      <div>
        <Label>策略</Label>
        <select
          value={strategy}
          onChange={(e) => setStrategy(e.target.value)}
          className="w-full mt-1.5 bg-zinc-950 border border-zinc-800 rounded-md px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-blue-500"
        >
          {strategies.length === 0 ? (
            <option value={strategy}>加载中…</option>
          ) : (
            strategies.map((s) => (
              <option key={s.key} value={s.key}>{s.name}</option>
            ))
          )}
        </select>
      </div>

      <div className="relative">
        <Label>股票代码 / 名称</Label>
        <div className="relative mt-1.5">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-500" />
          <input
            type="text"
            value={selectedStock ? selectedStock.label : stockSearch}
            onFocus={() => { setStockOpen(true); if (selectedStock) setStockSearch(""); }}
            onChange={(e) => { setStockSearch(e.target.value); setSelectedStock(null); setStockOpen(true); }}
            placeholder="输入代码或名称搜索…"
            className="w-full bg-zinc-950 border border-zinc-800 rounded-md pl-9 pr-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-blue-500"
          />
        </div>
        {stockOpen && filteredStocks.length > 0 && (
          <div className="absolute z-10 mt-1 w-full max-h-60 overflow-auto bg-zinc-950 border border-zinc-800 rounded-md shadow-lg">
            {filteredStocks.map((s) => (
              <button
                key={s.code}
                onClick={() => { setSelectedStock(s); setStockOpen(false); setStockSearch(""); }}
                className="w-full text-left px-3 py-1.5 text-sm text-zinc-300 hover:bg-zinc-800"
              >
                {s.label}
              </button>
            ))}
          </div>
        )}
      </div>

      <div>
        <Label>回测区间</Label>
        <div className="grid grid-cols-3 gap-2 mt-1.5">
          {PERIOD_OPTIONS.map((p) => (
            <button
              key={p.key}
              onClick={() => setPeriod(p.key)}
              className={cn(
                "px-3 py-1.5 text-sm rounded-md border transition-colors",
                period === p.key
                  ? "bg-blue-600 border-blue-600 text-white"
                  : "bg-zinc-950 border-zinc-800 text-zinc-400 hover:border-zinc-600"
              )}
            >
              {p.label}
            </button>
          ))}
        </div>
        <div className="mt-1 text-xs text-zinc-500">{start} ~ {end}</div>
      </div>

      <div>
        <Label>初始资金 (万)</Label>
        <input
          type="number"
          min={1}
          step={1}
          value={capitalW}
          onChange={(e) => setCapitalW(Math.max(1, parseInt(e.target.value) || 1))}
          className="w-full mt-1.5 bg-zinc-950 border border-zinc-800 rounded-md px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-blue-500"
        />
      </div>

      <button
        onClick={() => canSubmit && onSubmit({ strategy, code, start, end, capital: capitalW * 10000 })}
        disabled={!canSubmit}
        className={cn(
          "w-full py-2.5 rounded-md font-medium text-sm flex items-center justify-center gap-2 transition-colors",
          canSubmit
            ? "bg-blue-600 hover:bg-blue-500 text-white"
            : "bg-zinc-800 text-zinc-500 cursor-not-allowed"
        )}
      >
        <Play className="w-4 h-4" />
        {isPending ? "回测中…" : "开始回测"}
      </button>
    </div>
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return <label className="text-xs font-medium text-zinc-400">{children}</label>;
}
