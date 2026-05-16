import type { BacktestStats, TradeRecord } from "@/lib/types";

export function StatsCards({ stats }: { stats: BacktestStats }) {
  const items = [
    { label: "总收益率", value: `${stats.total_return >= 0 ? "+" : ""}${stats.total_return.toFixed(2)}%`, positive: stats.total_return >= 0 },
    { label: "最大回撤", value: `${stats.max_drawdown.toFixed(2)}%`, negative: true },
    { label: "夏普比率", value: stats.sharpe_ratio.toFixed(2) },
    { label: "交易笔数", value: stats.total_trade_count },
  ];
  return (
    <div className="grid grid-cols-4 gap-4">
      {items.map((it) => (
        <div key={it.label} className="bg-zinc-900/50 rounded-lg border border-zinc-800 p-4">
          <div className="text-xs text-zinc-500">{it.label}</div>
          <div
            className={`text-2xl font-bold mt-1 ${
              it.positive ? "text-red-400" : it.negative ? "text-green-400" : "text-zinc-200"
            }`}
          >
            {it.value}
          </div>
        </div>
      ))}
    </div>
  );
}

export function TradesTable({ trades }: { trades: TradeRecord[] }) {
  if (!trades.length) return null;
  return (
    <div className="bg-zinc-900/50 rounded-lg border border-zinc-800 overflow-hidden">
      <div className="px-4 py-3 border-b border-zinc-800 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-zinc-200">交易明细</h3>
        <span className="text-xs text-zinc-500">共 {trades.length} 笔</span>
      </div>
      <div className="max-h-72 overflow-auto">
        <table className="w-full text-sm">
          <thead className="bg-zinc-900 text-zinc-500 text-xs sticky top-0">
            <tr>
              <th className="text-left px-4 py-2 font-medium">日期</th>
              <th className="text-left px-4 py-2 font-medium">方向</th>
              <th className="text-right px-4 py-2 font-medium">价格</th>
              <th className="text-right px-4 py-2 font-medium">数量</th>
            </tr>
          </thead>
          <tbody>
            {trades.map((t, i) => (
              <tr key={i} className="border-t border-zinc-800/60">
                <td className="px-4 py-2 text-zinc-300">{t.date}</td>
                <td className="px-4 py-2">
                  <span
                    className={`text-xs px-2 py-0.5 rounded ${
                      t.direction === "buy" ? "bg-red-500/15 text-red-400" : "bg-green-500/15 text-green-400"
                    }`}
                  >
                    {t.direction === "buy" ? "买入" : "卖出"}
                  </span>
                </td>
                <td className="px-4 py-2 text-right text-zinc-300 font-mono">{t.price.toFixed(2)}</td>
                <td className="px-4 py-2 text-right text-zinc-300 font-mono">{t.volume}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
