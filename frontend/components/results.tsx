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

type TradeRound = { buy: TradeRecord; sells: TradeRecord[] };

function groupRounds(trades: TradeRecord[]): TradeRound[] {
  const rounds: TradeRound[] = [];
  let current: TradeRound | null = null;
  for (const t of trades) {
    if (t.direction === "buy") {
      if (current) rounds.push(current);
      current = { buy: t, sells: [] };
    } else if (current) {
      current.sells.push(t);
    }
  }
  if (current) rounds.push(current);
  return rounds;
}

function daysBetween(a: string, b: string): number {
  return Math.round((new Date(b).getTime() - new Date(a).getTime()) / 86400000);
}

export function TradesTable({ trades }: { trades: TradeRecord[] }) {
  if (!trades.length) return null;
  const rounds = groupRounds(trades);
  return (
    <div className="bg-zinc-900/50 rounded-lg border border-zinc-800 overflow-hidden shrink-0">
      <div className="px-4 py-3 border-b border-zinc-800 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-zinc-200">交易明细</h3>
        <span className="text-xs text-zinc-500">共 {rounds.length} 笔</span>
      </div>
      <div className="max-h-[420px] overflow-auto">
        <table className="w-full text-sm">
          <thead className="bg-zinc-900 text-zinc-500 text-xs sticky top-0">
            <tr>
              <th className="text-left px-3 py-2 font-medium w-10">#</th>
              <th className="text-left px-3 py-2 font-medium">时间</th>
              <th className="text-left px-3 py-2 font-medium w-16">操作</th>
              <th className="text-right px-3 py-2 font-medium">价格</th>
              <th className="text-right px-3 py-2 font-medium">数量</th>
              <th className="text-left px-3 py-2 font-medium">原因</th>
              <th className="text-right px-3 py-2 font-medium w-24">盈亏/耗时</th>
            </tr>
          </thead>
          {rounds.map((r, ri) => {
            const rowCount = 1 + r.sells.length;
            const cost = r.buy.price * r.buy.volume;
            const revenue = r.sells.reduce((s, t) => s + t.price * t.volume, 0);
            const soldVol = r.sells.reduce((s, t) => s + t.volume, 0);
            const isOpen = soldVol < r.buy.volume;
            const pnl = cost > 0 && !isOpen ? ((revenue - cost) / cost) * 100 : null;
            const lastDate = r.sells.length ? r.sells[r.sells.length - 1].date : null;
            const days = lastDate ? daysBetween(r.buy.date, lastDate) : null;
            return (
              <tbody key={ri} className="border-t-2 border-zinc-800/80">
                <tr>
                  <td rowSpan={rowCount} className="px-3 py-2 text-zinc-400 font-mono align-top">{ri + 1}</td>
                  <td className="px-3 py-2 text-red-400 whitespace-nowrap font-mono">{r.buy.date}</td>
                  <td className="px-3 py-2"><span className="text-xs px-2 py-0.5 rounded bg-red-500/15 text-red-400 font-bold">B</span></td>
                  <td className="px-3 py-2 text-right text-red-400 font-mono">{r.buy.price.toFixed(2)}</td>
                  <td className="px-3 py-2 text-right text-zinc-400 font-mono">{r.buy.volume}</td>
                  <td className="px-3 py-2 text-red-300/90 text-xs">{r.buy.reason || "—"}</td>
                  <td rowSpan={rowCount} className={`px-3 py-2 text-right font-mono text-xs align-top leading-5 ${pnl == null ? "text-zinc-500" : pnl >= 0 ? "text-red-400" : "text-green-400"}`}>
                    {pnl != null ? <>{pnl >= 0 ? "+" : ""}{pnl.toFixed(2)}%<br/>{days}天</> : <span className="italic">持仓中</span>}
                  </td>
                </tr>
                {r.sells.map((s, si) => (
                  <tr key={si}>
                    <td className="px-3 py-2 text-green-400 whitespace-nowrap font-mono">{s.date}</td>
                    <td className="px-3 py-2"><span className="text-xs px-2 py-0.5 rounded bg-green-500/15 text-green-400 font-bold">S</span></td>
                    <td className="px-3 py-2 text-right text-green-400 font-mono">{s.price.toFixed(2)}</td>
                    <td className="px-3 py-2 text-right text-zinc-400 font-mono">{s.volume}</td>
                    <td className="px-3 py-2 text-green-300/90 text-xs">{s.reason || "—"}</td>
                  </tr>
                ))}
              </tbody>
            );
          })}
        </table>
      </div>
    </div>
  );
}
