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

type TradePair = {
  buy: TradeRecord;
  sell?: TradeRecord;
};

function pairTrades(trades: TradeRecord[]): TradePair[] {
  const pairs: TradePair[] = [];
  let pendingBuy: TradeRecord | null = null;
  for (const t of trades) {
    if (t.direction === "buy") {
      if (pendingBuy) pairs.push({ buy: pendingBuy });
      pendingBuy = t;
    } else if (pendingBuy) {
      pairs.push({ buy: pendingBuy, sell: t });
      pendingBuy = null;
    }
  }
  if (pendingBuy) pairs.push({ buy: pendingBuy });
  return pairs;
}

export function TradesTable({ trades }: { trades: TradeRecord[] }) {
  if (!trades.length) return null;
  const pairs = pairTrades(trades);
  return (
    <div className="bg-zinc-900/50 rounded-lg border border-zinc-800 overflow-hidden shrink-0">
      <div className="px-4 py-3 border-b border-zinc-800 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-zinc-200">交易明细</h3>
        <span className="text-xs text-zinc-500">共 {pairs.length} 笔</span>
      </div>
      <div className="max-h-[420px] overflow-auto">
        <table className="w-full text-sm">
          <thead className="bg-zinc-900 text-zinc-500 text-xs sticky top-0">
            <tr>
              <th className="text-left px-3 py-2 font-medium w-10">#</th>
              <th className="text-left px-3 py-2 font-medium">时间</th>
              <th className="text-left px-3 py-2 font-medium w-16">操作</th>
              <th className="text-right px-3 py-2 font-medium">价格</th>
              <th className="text-left px-3 py-2 font-medium">原因</th>
              <th className="text-right px-3 py-2 font-medium w-20">盈亏</th>
            </tr>
          </thead>
          {pairs.map((p, i) => {
            const pnl =
              p.sell && p.buy.price > 0
                ? ((p.sell.price - p.buy.price) / p.buy.price) * 100
                : null;
            return (
              <tbody key={i} className="border-t-2 border-zinc-800">
                <tr>
                  <td
                    rowSpan={p.sell ? 2 : 1}
                    className="px-3 py-2 text-zinc-400 font-mono align-top"
                  >
                    {i + 1}
                  </td>
                  <td className="px-3 py-2 text-red-400 whitespace-nowrap font-mono">
                    {p.buy.date}
                  </td>
                  <td className="px-3 py-2">
                    <span className="text-xs px-2 py-0.5 rounded bg-red-500/15 text-red-400 font-bold">B</span>
                  </td>
                  <td className="px-3 py-2 text-right text-red-400 font-mono">
                    {p.buy.price.toFixed(2)}
                  </td>
                  <td className="px-3 py-2 text-red-300/90">{p.buy.reason || "—"}</td>
                  <td
                    rowSpan={p.sell ? 2 : 1}
                    className={`px-3 py-2 text-right font-mono font-semibold align-middle ${
                      pnl == null ? "text-zinc-500" : pnl >= 0 ? "text-red-400" : "text-green-400"
                    }`}
                  >
                    {pnl == null ? (p.sell ? "—" : <span className="text-zinc-500 italic text-xs">持仓中</span>) : `${pnl >= 0 ? "+" : ""}${pnl.toFixed(2)}%`}
                  </td>
                </tr>
                {p.sell && (
                  <tr>
                    <td className="px-3 py-2 text-green-400 whitespace-nowrap font-mono">
                      {p.sell.date}
                    </td>
                    <td className="px-3 py-2">
                      <span className="text-xs px-2 py-0.5 rounded bg-green-500/15 text-green-400 font-bold">S</span>
                    </td>
                    <td className="px-3 py-2 text-right text-green-400 font-mono">
                      {p.sell.price.toFixed(2)}
                    </td>
                    <td className="px-3 py-2 text-green-300/90">{p.sell.reason || "—"}</td>
                  </tr>
                )}
              </tbody>
            );
          })}
        </table>
      </div>
    </div>
  );
}
