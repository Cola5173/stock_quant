import { LineChart, RefreshCw } from "lucide-react";

export function Header({ subtitle, dateRange }: { subtitle?: string; dateRange?: string }) {
  return (
    <header className="h-14 shrink-0 flex items-center justify-between px-6 border-b border-zinc-800 bg-zinc-950">
      <div className="flex items-center gap-3">
        <LineChart className="w-5 h-5 text-blue-500" />
        <div className="flex flex-col leading-tight">
          <span className="text-base font-bold text-zinc-100">Cola Quant</span>
          <span className="text-[10px] text-zinc-500">{subtitle ?? "A 股量化回测平台"}</span>
        </div>
      </div>
      <div className="flex items-center gap-3">
        {dateRange && (
          <span className="text-xs px-2.5 py-1 rounded-md bg-green-500/10 text-green-400 border border-green-500/30">
            真实数据 · {dateRange}
          </span>
        )}
        <button className="text-xs px-3 py-1.5 rounded-md border border-zinc-800 text-zinc-300 hover:bg-zinc-800 flex items-center gap-1.5">
          <RefreshCw className="w-3 h-3" />
          刷新数据
        </button>
      </div>
    </header>
  );
}
