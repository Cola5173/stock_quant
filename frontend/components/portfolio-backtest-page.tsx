"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, Play, Loader2, RefreshCw } from "lucide-react";
import { api } from "@/lib/api";

interface RunSummary {
  id: string;
  strategy_key: string;
  strategy_label: string;
  run_time: string;
  start: string;
  end: string;
  total_return_pct: number;
  annual_return_pct: number;
  max_drawdown_pct: number;
  win_rate_pct: number;
  trades_closed: number;
}

export function PortfolioBacktestPage() {
  const [selectedId, setSelectedId] = useState<string | null>(null);

  if (selectedId) {
    return (
      <PortfolioBacktestDetail
        runId={selectedId}
        onBack={() => setSelectedId(null)}
      />
    );
  }

  return <PortfolioBacktestList onSelect={setSelectedId} />;
}

function PortfolioBacktestList({ onSelect }: { onSelect: (id: string) => void }) {
  const queryClient = useQueryClient();
  const [showRunModal, setShowRunModal] = useState(false);
  const [toast, setToast] = useState<{ type: "success" | "error"; msg: string } | null>(null);

  const { data: runs = [], isPending } = useQuery({
    queryKey: ["portfolio-runs"],
    queryFn: () => api.portfolioRuns() as Promise<unknown> as Promise<RunSummary[]>,
    refetchInterval: 5000,
  });

  const { data: running = [] } = useQuery({
    queryKey: ["portfolio-running"],
    queryFn: () => api.portfolioRunning(),
    refetchInterval: 3000,
  });

  const showToast = (type: "success" | "error", msg: string) => {
    setToast({ type, msg });
    setTimeout(() => setToast(null), 3000);
  };

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center justify-between mb-2">
        <div>
          <h1 className="text-xl font-semibold text-zinc-100">策略回测</h1>
          <p className="text-xs text-zinc-500 mt-1">共 {runs.length} 条记录，按运行时间倒序</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => queryClient.invalidateQueries({ queryKey: ["portfolio-runs"] })}
            className="px-3 py-1.5 rounded-md bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-xs flex items-center gap-1.5"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            刷新
          </button>
          <button
            onClick={() => setShowRunModal(true)}
            className="px-4 py-1.5 rounded-md bg-blue-600 hover:bg-blue-500 text-white text-xs flex items-center gap-1.5"
          >
            <Play className="w-3.5 h-3.5" />
            运行新回测
          </button>
        </div>
      </div>

      {running.length > 0 && (
        <div className="mb-3 px-3 py-2 bg-amber-900/30 border border-amber-700 rounded-md text-amber-300 text-xs flex items-center gap-2">
          <Loader2 className="w-3.5 h-3.5 animate-spin" />
          正在运行：{running.map(r => `${r.strategy_key} ${r.start}~${r.end}`).join("，")}
        </div>
      )}

      <div className="flex-1 overflow-y-auto border border-zinc-800 rounded-lg">
        {isPending ? (
          <div className="text-zinc-500 text-center py-20">加载中…</div>
        ) : runs.length === 0 ? (
          <div className="text-zinc-500 text-center py-20">暂无回测记录</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-zinc-900">
              <tr className="text-zinc-400 text-left border-b border-zinc-800">
                <th className="px-4 py-3 font-medium">运行时间</th>
                <th className="px-4 py-3 font-medium">策略</th>
                <th className="px-4 py-3 font-medium">区间</th>
                <th className="px-4 py-3 font-medium text-right">总收益</th>
                <th className="px-4 py-3 font-medium text-right">年化</th>
                <th className="px-4 py-3 font-medium text-right">最大回撤</th>
                <th className="px-4 py-3 font-medium text-right">胜率</th>
                <th className="px-4 py-3 font-medium text-right">交易笔数</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr
                  key={r.id}
                  onClick={() => onSelect(r.id)}
                  className="border-t border-zinc-800/50 hover:bg-zinc-800/30 cursor-pointer transition-colors"
                >
                  <td className="px-4 py-3 text-zinc-300 font-mono text-xs">{r.run_time}</td>
                  <td className="px-4 py-3 text-zinc-200">{r.strategy_label}</td>
                  <td className="px-4 py-3 text-zinc-400 text-xs">{r.start} ~ {r.end}</td>
                  <td className={`px-4 py-3 text-right font-semibold ${r.total_return_pct >= 0 ? "text-red-400" : "text-green-400"}`}>
                    {r.total_return_pct >= 0 ? "+" : ""}{r.total_return_pct.toFixed(2)}%
                  </td>
                  <td className={`px-4 py-3 text-right ${r.annual_return_pct >= 0 ? "text-red-400" : "text-green-400"}`}>
                    {r.annual_return_pct >= 0 ? "+" : ""}{r.annual_return_pct.toFixed(2)}%
                  </td>
                  <td className="px-4 py-3 text-right text-zinc-300">{r.max_drawdown_pct.toFixed(2)}%</td>
                  <td className="px-4 py-3 text-right text-zinc-300">{r.win_rate_pct.toFixed(1)}%</td>
                  <td className="px-4 py-3 text-right text-zinc-400">{r.trades_closed}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {showRunModal && (
        <RunBacktestModal
          onClose={() => setShowRunModal(false)}
          onStarted={() => {
            setShowRunModal(false);
            showToast("success", "回测已启动，结果将在完成后显示");
            queryClient.invalidateQueries({ queryKey: ["portfolio-running"] });
          }}
          onError={(msg) => showToast("error", msg)}
        />
      )}

      {toast && (
        <div className={`fixed top-6 right-6 z-50 px-4 py-3 rounded-lg shadow-lg text-sm ${
          toast.type === "success"
            ? "bg-green-900/90 border border-green-700 text-green-200"
            : "bg-red-900/90 border border-red-700 text-red-200"
        }`}>
          {toast.msg}
        </div>
      )}
    </div>
  );
}

function RunBacktestModal({
  onClose,
  onStarted,
  onError,
}: {
  onClose: () => void;
  onStarted: () => void;
  onError: (msg: string) => void;
}) {
  const { data: strategies = [] } = useQuery({
    queryKey: ["portfolio-strategies"],
    queryFn: () => api.portfolioStrategies(),
  });

  const today = new Date().toISOString().slice(0, 10);
  const oneYearAgo = new Date();
  oneYearAgo.setFullYear(oneYearAgo.getFullYear() - 1);
  const defaultStart = oneYearAgo.toISOString().slice(0, 10);

  const [strategy, setStrategy] = useState("b1_small");
  const [start, setStart] = useState(defaultStart);
  const [end, setEnd] = useState(today);
  const [capital, setCapital] = useState(200000);

  const startMutation = useMutation({
    mutationFn: () => api.portfolioRunStart({ strategy, start, end, capital }),
    onSuccess: () => onStarted(),
    onError: (e: Error) => onError(`启动失败: ${e.message}`),
  });

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-6 w-full max-w-md" onClick={(e) => e.stopPropagation()}>
        <h2 className="text-lg font-semibold text-zinc-200 mb-4">运行新回测</h2>
        <div className="space-y-3">
          <div>
            <label className="text-xs text-zinc-500 mb-1.5 block">策略</label>
            <select
              value={strategy}
              onChange={(e) => setStrategy(e.target.value)}
              className="w-full bg-zinc-950 border border-zinc-800 rounded-md px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-blue-500"
            >
              {strategies.map((s) => (
                <option key={s.key} value={s.key}>{s.label}</option>
              ))}
            </select>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-zinc-500 mb-1.5 block">开始日期</label>
              <input
                type="date"
                value={start}
                onChange={(e) => setStart(e.target.value)}
                className="w-full bg-zinc-950 border border-zinc-800 rounded-md px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-blue-500"
              />
            </div>
            <div>
              <label className="text-xs text-zinc-500 mb-1.5 block">结束日期</label>
              <input
                type="date"
                value={end}
                onChange={(e) => setEnd(e.target.value)}
                className="w-full bg-zinc-950 border border-zinc-800 rounded-md px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-blue-500"
              />
            </div>
          </div>
          <div>
            <label className="text-xs text-zinc-500 mb-1.5 block">初始资金</label>
            <input
              type="number"
              value={capital}
              onChange={(e) => setCapital(Number(e.target.value))}
              className="w-full bg-zinc-950 border border-zinc-800 rounded-md px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-blue-500"
            />
          </div>
        </div>
        <div className="mt-3 p-3 bg-amber-900/20 border border-amber-700/50 rounded-md text-amber-300 text-xs">
          全市场扫描 + 多日回测，预计耗时 5~10 分钟。提交后请等待。
        </div>
        <div className="flex gap-2 justify-end mt-4">
          <button onClick={onClose} className="px-4 py-2 rounded-md bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-sm">
            取消
          </button>
          <button
            onClick={() => startMutation.mutate()}
            disabled={startMutation.isPending}
            className="px-4 py-2 rounded-md bg-blue-600 hover:bg-blue-500 disabled:bg-zinc-700 text-white text-sm flex items-center gap-1.5"
          >
            {startMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
            {startMutation.isPending ? "启动中..." : "开始回测"}
          </button>
        </div>
      </div>
    </div>
  );
}

function PortfolioBacktestDetail({ runId, onBack }: { runId: string; onBack: () => void }) {
  const { data, isPending, isError } = useQuery({
    queryKey: ["portfolio-run", runId],
    queryFn: () => api.portfolioRunDetail(runId),
  });

  if (isPending) return <div className="p-6 text-zinc-500">加载中…</div>;
  if (isError || !data) return <div className="p-6 text-zinc-500">加载失败</div>;

  const meta = (data.strategy_meta ?? {}) as { label?: string; description?: string[] };
  const stats = (data.stats ?? {}) as Record<string, unknown>;
  const period = (data.period ?? {}) as Record<string, unknown>;
  const dailyValues = (data.daily_values ?? []) as Array<{ date: string; total: number }>;
  const trades = (data.trades ?? []) as Array<Record<string, unknown>>;
  const closedTrades = trades.filter(t => t.sell_date && t.pnl_pct !== null);

  const totalReturn = Number(stats.total_return_pct ?? 0);

  return (
    <div className="h-full overflow-y-auto space-y-3">
      {/* 头部导航 */}
      <div className="flex items-center justify-between">
        <button
          onClick={onBack}
          className="text-blue-400 hover:text-blue-300 text-sm flex items-center gap-1"
        >
          <ChevronLeft className="w-4 h-4" />
          策略回测 / {meta.label ?? "详情"}
        </button>
      </div>

      {/* 策略说明 */}
      <div className="bg-zinc-900/50 border border-zinc-800 rounded-lg p-4">
        <h2 className="text-base font-semibold text-zinc-200 mb-2">{meta.label}</h2>
        {meta.description && (
          <ul className="space-y-1 text-xs text-zinc-400">
            {meta.description.map((d, i) => (
              <li key={i}>• {d}</li>
            ))}
          </ul>
        )}
      </div>

      {/* 关键指标 */}
      <div className="grid grid-cols-5 gap-3">
        <StatCard label="总收益率" value={`${totalReturn >= 0 ? "+" : ""}${totalReturn.toFixed(2)}%`} highlight={totalReturn >= 0} />
        <StatCard label="年化收益率" value={`${Number(stats.annual_return_pct ?? 0) >= 0 ? "+" : ""}${Number(stats.annual_return_pct ?? 0).toFixed(2)}%`} highlight={Number(stats.annual_return_pct ?? 0) >= 0} />
        <StatCard label="最大回撤" value={`${Number(stats.max_drawdown_pct ?? 0).toFixed(2)}%`} />
        <StatCard label="胜率" value={`${Number(stats.win_rate_pct ?? 0).toFixed(2)}%`} />
        <StatCard label="交易笔数" value={`${stats.trades_closed ?? 0}`} />
      </div>

      <div className="grid grid-cols-5 gap-3">
        <StatCard label="初始资金" value={Number(stats.initial_capital ?? 0).toLocaleString()} />
        <StatCard label="最终净值" value={Number(stats.final_value ?? 0).toLocaleString()} />
        <StatCard label="平均盈利" value={`${Number(stats.avg_win_pct ?? 0) >= 0 ? "+" : ""}${Number(stats.avg_win_pct ?? 0).toFixed(2)}%`} highlight />
        <StatCard label="平均亏损" value={`${Number(stats.avg_loss_pct ?? 0).toFixed(2)}%`} negative />
        <StatCard label="交易天数" value={`${(period.days ?? 0)}`} />
      </div>

      {/* 最佳/最差交易 */}
      <div className="grid grid-cols-2 gap-3">
        <BestWorstCard label="最佳交易" trade={stats.best_trade as Record<string, unknown> | null} positive />
        <BestWorstCard label="最差交易" trade={stats.worst_trade as Record<string, unknown> | null} positive={false} />
      </div>

      {/* 净值曲线 */}
      <div className="bg-zinc-900/50 border border-zinc-800 rounded-lg p-4">
        <h3 className="text-sm font-semibold text-zinc-200 mb-3">净值曲线</h3>
        <EquityChart points={dailyValues} initialCapital={Number(stats.initial_capital ?? 200000)} />
      </div>

      {/* 交易明细 */}
      <PortfolioTradesTable trades={closedTrades} />
    </div>
  );
}

function StatCard({ label, value, highlight, negative }: { label: string; value: string; highlight?: boolean; negative?: boolean }) {
  const valueColor = negative ? "text-green-400" : highlight ? "text-red-400" : "text-zinc-100";
  return (
    <div className="bg-zinc-900/50 border border-zinc-800 rounded-lg p-3">
      <div className="text-xs text-zinc-500">{label}</div>
      <div className={`text-lg font-semibold mt-1 ${valueColor}`}>{value}</div>
    </div>
  );
}

function BestWorstCard({ label, trade, positive }: { label: string; trade: Record<string, unknown> | null; positive: boolean }) {
  if (!trade) {
    return (
      <div className="bg-zinc-900/50 border border-zinc-800 rounded-lg p-3">
        <div className="text-xs text-zinc-500">{label}</div>
        <div className="text-sm text-zinc-500 mt-1">—</div>
      </div>
    );
  }
  const pnlPct = Number(trade.pnl_pct ?? 0);
  return (
    <div className="bg-zinc-900/50 border border-zinc-800 rounded-lg p-3">
      <div className="text-xs text-zinc-500">{label}</div>
      <div className="flex items-baseline gap-2 mt-1">
        <span className="text-sm text-zinc-200">{String(trade.symbol ?? "")} {String(trade.name ?? "")}</span>
        <span className={`text-base font-semibold ${positive ? "text-red-400" : "text-green-400"}`}>
          {pnlPct >= 0 ? "+" : ""}{pnlPct.toFixed(2)}%
        </span>
      </div>
      <div className="text-xs text-zinc-500 mt-0.5">{String(trade.buy_date ?? "")} → {String(trade.sell_date ?? "")}</div>
    </div>
  );
}

function EquityChart({ points, initialCapital }: { points: Array<{ date: string; total: number }>; initialCapital: number }) {
  if (points.length === 0) return <div className="text-zinc-500 text-sm py-10 text-center">无数据</div>;

  const width = 800;
  const height = 240;
  const padding = { left: 50, right: 10, top: 10, bottom: 30 };
  const w = width - padding.left - padding.right;
  const h = height - padding.top - padding.bottom;

  const totals = points.map(p => p.total);
  const minVal = Math.min(...totals, initialCapital);
  const maxVal = Math.max(...totals, initialCapital);
  const range = maxVal - minVal || 1;

  const xStep = w / Math.max(1, points.length - 1);
  const pathD = points.map((p, i) => {
    const x = padding.left + i * xStep;
    const y = padding.top + h - ((p.total - minVal) / range) * h;
    return `${i === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`;
  }).join(" ");

  // 基准线（初始资金）
  const baseY = padding.top + h - ((initialCapital - minVal) / range) * h;

  // 标签
  const yLabels = [minVal, (minVal + maxVal) / 2, maxVal];

  // x 轴稀疏采样
  const xLabelCount = 6;
  const xLabels = Array.from({ length: xLabelCount }, (_, i) => {
    const idx = Math.floor(i * (points.length - 1) / (xLabelCount - 1));
    return { idx, date: points[idx]?.date ?? "" };
  });

  return (
    <div className="w-full overflow-x-auto">
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full" style={{ minWidth: 600 }}>
        {/* y 轴标签 */}
        {yLabels.map((v, i) => {
          const y = padding.top + h - ((v - minVal) / range) * h;
          return (
            <g key={i}>
              <line x1={padding.left} y1={y} x2={width - padding.right} y2={y} stroke="#3f3f46" strokeWidth={0.5} strokeDasharray="2 2" />
              <text x={padding.left - 5} y={y + 3} fontSize="10" fill="#71717a" textAnchor="end">
                {(v / 10000).toFixed(1)}w
              </text>
            </g>
          );
        })}
        {/* 基准线 */}
        <line x1={padding.left} y1={baseY} x2={width - padding.right} y2={baseY} stroke="#71717a" strokeWidth={1} strokeDasharray="4 2" />
        {/* 曲线 */}
        <path d={pathD} fill="none" stroke="#ef4444" strokeWidth={1.5} />
        {/* x 轴标签 */}
        {xLabels.map((l, i) => (
          <text key={i} x={padding.left + l.idx * xStep} y={height - 10} fontSize="10" fill="#71717a" textAnchor="middle">
            {l.date}
          </text>
        ))}
      </svg>
    </div>
  );
}

type PortfolioRound = {
  symbol: string;
  name: string;
  buyDate: string;
  buyPrice: number;
  totalShares: number;
  sells: Array<{ date: string; price: number; shares: number; reason: string }>;
};

function groupPortfolioRounds(trades: Array<Record<string, unknown>>): PortfolioRound[] {
  const map = new Map<string, PortfolioRound>();
  const order: string[] = [];
  for (const t of trades) {
    const key = `${t.symbol}_${t.buy_date}`;
    if (!map.has(key)) {
      order.push(key);
      map.set(key, {
        symbol: String(t.symbol ?? ""),
        name: String(t.name ?? ""),
        buyDate: String(t.buy_date ?? ""),
        buyPrice: Number(t.buy_price ?? 0),
        totalShares: 0,
        sells: [],
      });
    }
    const round = map.get(key)!;
    const shares = Number(t.shares ?? 0);
    round.totalShares += shares;
    round.sells.push({
      date: String(t.sell_date ?? ""),
      price: Number(t.sell_price ?? 0),
      shares,
      reason: String(t.sell_reason ?? ""),
    });
  }
  return order.map(k => map.get(k)!);
}

function daysBetween(a: string, b: string): number {
  return Math.round((new Date(b).getTime() - new Date(a).getTime()) / 86400000);
}

function PortfolioTradesTable({ trades }: { trades: Array<Record<string, unknown>> }) {
  if (!trades.length) return null;
  const rounds = groupPortfolioRounds(trades);
  return (
    <div className="bg-zinc-900/50 rounded-lg border border-zinc-800 overflow-hidden">
      <div className="px-4 py-3 border-b border-zinc-800 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-zinc-200">买卖明细</h3>
        <span className="text-xs text-zinc-500">共 {rounds.length} 笔</span>
      </div>
      <div className="max-h-[500px] overflow-auto">
        <table className="w-full text-sm">
          <thead className="bg-zinc-900 text-zinc-500 text-xs sticky top-0">
            <tr>
              <th className="text-left px-3 py-2 font-medium w-10">#</th>
              <th className="text-left px-3 py-2 font-medium">代码</th>
              <th className="text-left px-3 py-2 font-medium">名称</th>
              <th className="text-left px-3 py-2 font-medium">时间</th>
              <th className="text-left px-3 py-2 font-medium w-12">操作</th>
              <th className="text-right px-3 py-2 font-medium">价格</th>
              <th className="text-right px-3 py-2 font-medium">数量</th>
              <th className="text-left px-3 py-2 font-medium">原因</th>
              <th className="text-right px-3 py-2 font-medium w-24">盈亏/耗时</th>
            </tr>
          </thead>
          {rounds.map((r, ri) => {
            const rowCount = 1 + r.sells.length;
            const cost = r.buyPrice * r.totalShares;
            const revenue = r.sells.reduce((s, t) => s + t.price * t.shares, 0);
            const pnl = cost > 0 ? ((revenue - cost) / cost) * 100 : null;
            const lastSellDate = r.sells.length ? r.sells[r.sells.length - 1].date : null;
            const days = lastSellDate ? daysBetween(r.buyDate, lastSellDate) : null;
            return (
              <tbody key={ri} className="border-t-2 border-zinc-800/80">
                <tr>
                  <td rowSpan={rowCount} className="px-3 py-2 text-zinc-400 font-mono align-top">{ri + 1}</td>
                  <td rowSpan={rowCount} className="px-3 py-2 text-zinc-300 align-top">{r.symbol}</td>
                  <td rowSpan={rowCount} className="px-3 py-2 text-zinc-400 align-top">{r.name}</td>
                  <td className="px-3 py-2 text-red-400 whitespace-nowrap font-mono">{r.buyDate}</td>
                  <td className="px-3 py-2"><span className="text-xs px-2 py-0.5 rounded bg-red-500/15 text-red-400 font-bold">B</span></td>
                  <td className="px-3 py-2 text-right text-red-400 font-mono">{r.buyPrice.toFixed(2)}</td>
                  <td className="px-3 py-2 text-right text-zinc-400 font-mono">{r.totalShares}</td>
                  <td className="px-3 py-2 text-zinc-500 text-xs">—</td>
                  <td rowSpan={rowCount} className={`px-3 py-2 text-right font-mono text-xs align-top leading-5 ${pnl == null ? "text-zinc-500" : pnl >= 0 ? "text-red-400" : "text-green-400"}`}>
                    {pnl != null ? <>{pnl >= 0 ? "+" : ""}{pnl.toFixed(2)}%<br/>{days}天</> : <span className="italic">—</span>}
                  </td>
                </tr>
                {r.sells.map((s, si) => (
                  <tr key={si}>
                    <td className="px-3 py-2 text-green-400 whitespace-nowrap font-mono">{s.date}</td>
                    <td className="px-3 py-2"><span className="text-xs px-2 py-0.5 rounded bg-green-500/15 text-green-400 font-bold">S</span></td>
                    <td className="px-3 py-2 text-right text-green-400 font-mono">{s.price.toFixed(2)}</td>
                    <td className="px-3 py-2 text-right text-zinc-400 font-mono">{s.shares}</td>
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
