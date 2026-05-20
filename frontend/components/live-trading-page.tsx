"use client";

import { useState, useEffect, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { RefreshCw, ChevronRight } from "lucide-react";
import type { StockItem } from "@/lib/types";

const ACTION_COLORS: Record<string, string> = {
  sell: "bg-red-900/40 border-red-700",
  buy: "bg-green-900/40 border-green-700",
  hold: "bg-zinc-800/60 border-zinc-700",
  wait: "bg-zinc-800/60 border-zinc-700",
};

const ACTION_LABELS: Record<string, string> = {
  sell: "卖出",
  buy: "买入",
  hold: "持有",
  wait: "观望",
};

export function LiveTradingPage() {
  const [strategy, setStrategy] = useState<string | null>(() => {
    if (typeof window !== "undefined") {
      return localStorage.getItem("live_strategy") || null;
    }
    return null;
  });

  if (!strategy) {
    return <StrategySelector onSelect={(key) => {
      localStorage.setItem("live_strategy", key);
      setStrategy(key);
    }} />;
  }

  return <LiveTradingMain strategy={strategy} onChangeStrategy={() => {
    localStorage.removeItem("live_strategy");
    setStrategy(null);
  }} />;
}

function StrategySelector({ onSelect }: { onSelect: (key: string) => void }) {
  const { data: strategies = [] } = useQuery({ queryKey: ["strategies"], queryFn: api.strategies });
  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-2xl mx-auto pt-20 px-6 space-y-4">
        <h2 className="text-2xl font-bold text-zinc-200 text-center">选择策略</h2>
        <p className="text-sm text-zinc-500 text-center">模拟盘将根据所选策略生成明日建议</p>
        <div className="space-y-2 pt-4">
          {strategies.map((s) => (
            <button
              key={s.key}
              onClick={() => onSelect(s.key)}
              className="w-full flex items-center justify-between bg-zinc-900/50 border border-zinc-800 rounded-lg p-4 hover:border-blue-600 transition-colors"
            >
              <div className="text-left">
                <div className="text-sm font-medium text-zinc-200">{s.name}</div>
                {s.description && <div className="text-xs text-zinc-500 mt-0.5">{s.description}</div>}
              </div>
              <ChevronRight className="w-4 h-4 text-zinc-500" />
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

function LiveTradingMain({ strategy, onChangeStrategy }: { strategy: string; onChangeStrategy: () => void }) {
  const queryClient = useQueryClient();
  const [toast, setToast] = useState<{ type: "success" | "error"; msg: string } | null>(null);
  const [addTxModalOpen, setAddTxModalOpen] = useState(false);
  const [txLogModalOpen, setTxLogModalOpen] = useState(false);

  const showToast = (type: "success" | "error", msg: string) => {
    setToast({ type, msg });
    setTimeout(() => setToast(null), 3000);
  };

  const { data: strategies = [] } = useQuery({ queryKey: ["strategies"], queryFn: api.strategies });
  const strategyName = strategies.find((s) => s.key === strategy)?.name ?? strategy;

  const { data, isPending, isError } = useQuery({
    queryKey: ["advisor-latest"],
    queryFn: () => api.advisorLatest(),
    refetchInterval: 60_000,
  });

  const recalculate = useMutation({
    mutationFn: () => api.runDecision(undefined, strategy),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["advisor-latest"] });
    },
  });

  const addTxMutation = useMutation({
    mutationFn: (tx: Record<string, unknown>) => api.addTransaction(tx),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["advisor-latest"] });
      showToast("success", "交易已添加");
      setAddTxModalOpen(false);
    },
    onError: (err: Error) => {
      showToast("error", `添加失败：${err.message}`);
    },
  });

  if (isPending) {
    return <div className="flex items-center justify-center h-full text-zinc-500">加载中…</div>;
  }
  if (isError) {
    return <div className="flex items-center justify-center h-full text-zinc-500">加载失败</div>;
  }

  const positionsData = data?.positions as { total_capital?: number; positions?: Array<Record<string, unknown>> } | null;
  const positions = (positionsData?.positions ?? []).map((p) => ({
    symbol: String(p.symbol ?? ""),
    name: String(p.name ?? ""),
    shares: Number(p.shares ?? 0),
    cost_price: Number(p.cost_price ?? 0),
    buy_date: String(p.buy_date ?? ""),
  }));
  const totalCapital = positionsData?.total_capital ?? 100000;

  const decision = data?.decision as Record<string, unknown> | null;
  const holdings = (decision?.holdings ?? []) as Array<Record<string, unknown>>;
  const actions = (decision?.actions ?? []) as Array<Record<string, unknown>>;
  const market = (decision?.market ?? {}) as Record<string, unknown>;
  const cooldown = (decision?.cooldown ?? {}) as Record<string, unknown>;
  const warnings = (decision?.warnings ?? []) as string[];
  const decisionDate = decision?.date as string | undefined;

  // 计算市值与仓位
  const totalMarketValue = positions.reduce((sum, p) => {
    const holdingInfo = holdings.find((h) => h.symbol === p.symbol);
    const price = holdingInfo
      ? Number(holdingInfo.current_close)
      : p.cost_price;
    return sum + p.shares * price;
  }, 0);
  const totalPositionPct = totalCapital > 0 ? (totalMarketValue / totalCapital) * 100 : 0;

  return (
    <div className="h-full overflow-y-auto space-y-4">
      {/* 策略标识 + 切换 */}
      <div className="flex items-center gap-3">
        <button onClick={onChangeStrategy} className="text-sm font-bold text-blue-400 hover:text-blue-300">‹ 切换策略</button>
        <span className="px-4 py-1.5 text-sm font-bold rounded-full bg-red-600 text-white">
          {strategyName}
        </span>
      </div>

      {/* 持仓展示（只读，由交易流水派生） */}
      <Section
        title="当前持仓"
        actions={
          <div className="flex gap-2">
            <button
              onClick={() => setTxLogModalOpen(true)}
              className="px-3 py-1.5 rounded-md bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-xs"
            >
              查看交易记录
            </button>
            <button
              onClick={() => recalculate.mutate()}
              disabled={recalculate.isPending}
              className="px-3 py-1.5 rounded-md bg-blue-600 hover:bg-blue-500 disabled:bg-zinc-700 disabled:text-zinc-500 text-white text-xs flex items-center gap-1.5"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${recalculate.isPending ? "animate-spin" : ""}`} />
              {recalculate.isPending ? "计算中..." : "重新计算决策"}
            </button>
          </div>
        }
      >
        {/* 总资金（只读展示） */}
        <div className="mb-4">
          <div className="flex items-center justify-between mb-1.5">
            <label className="text-xs text-zinc-500">总资金</label>
            <span className="text-xs text-zinc-500">
              总仓位 <span className={`font-medium ${totalPositionPct > 90 ? "text-red-400" : totalPositionPct > 50 ? "text-amber-400" : "text-zinc-300"}`}>
                {totalPositionPct.toFixed(1)}%
              </span>
              <span className="text-zinc-600 ml-2">
                市值 {totalMarketValue.toLocaleString(undefined, { maximumFractionDigits: 0 })} / 现金 {(totalCapital - totalMarketValue).toLocaleString(undefined, { maximumFractionDigits: 0 })}
              </span>
            </span>
          </div>
          <div className="w-full bg-zinc-950 border border-zinc-800 rounded-md px-3 py-2 text-sm text-zinc-200">
            {totalCapital.toLocaleString()}
          </div>
        </div>

        {/* 持仓列表（只读） */}
        <div className="mb-2">
          <div className="flex items-center justify-between mb-2">
            <label className="text-xs text-zinc-500">持仓列表（由交易流水自动计算）</label>
            <button onClick={() => setAddTxModalOpen(true)} className="text-xs text-blue-400 hover:text-blue-300">+ 添加交易</button>
          </div>
          {positions.length === 0 ? (
            <p className="text-zinc-500 text-sm py-2">暂无持仓，点击右上角"添加交易"</p>
          ) : (
            <div className="space-y-2">
              <div className="grid grid-cols-[1.2fr_0.6fr_0.8fr_0.8fr_1fr] gap-2 text-xs text-zinc-500 px-2">
                <span>代码</span><span>仓位</span><span>股数</span><span>成本价</span><span>买入日期</span>
              </div>
              {positions.map((p, i) => {
                const holdingInfo = holdings.find((h) => h.symbol === p.symbol);
                const price = holdingInfo ? Number(holdingInfo.current_close) : p.cost_price;
                const marketValue = p.shares * price;
                const positionPct = totalCapital > 0 ? (marketValue / totalCapital) * 100 : 0;
                return (
                  <div key={i} className="grid grid-cols-[1.2fr_0.6fr_0.8fr_0.8fr_1fr] gap-2 items-center bg-zinc-950 border border-zinc-800 rounded-md px-2 py-1.5">
                    <span className="text-xs text-zinc-200">{p.name || p.symbol}</span>
                    <span className={`text-xs text-center ${positionPct > 50 ? "text-amber-400" : "text-zinc-300"}`}>{positionPct.toFixed(1)}%</span>
                    <span className="text-xs text-zinc-200 text-center">{p.shares}</span>
                    <span className="text-xs text-zinc-200 text-center">{p.cost_price.toFixed(2)}</span>
                    <span className="text-xs text-zinc-500">{p.buy_date}</span>
                  </div>
                );
              })}
            </div>
          )}
        </div>

      </Section>

      {/* 今日持仓分析（基于已有数据） */}
      {holdings.length > 0 && (
        <Section title="今日持仓分析">
          <div className="space-y-2">
            {holdings.map((h, i) => {
              const risk = (h.risk ?? {}) as Record<string, unknown>;
              const level = String(risk.risk_level ?? "low");
              const notes = (risk.risk_notes ?? []) as string[];
              const levelColor = level === "high" ? "border-red-700 bg-red-900/30"
                : level === "medium" ? "border-amber-700 bg-amber-900/20"
                : "border-zinc-700 bg-zinc-800/40";
              const levelLabel = level === "high" ? "高风险" : level === "medium" ? "中风险" : "低风险";
              const levelTextColor = level === "high" ? "text-red-300" : level === "medium" ? "text-amber-300" : "text-zinc-400";
              return (
                <div key={i} className={`rounded-lg border p-3 ${levelColor}`}>
                  <div className="flex items-center gap-2 mb-1">
                    <span className={`text-xs font-bold ${levelTextColor}`}>{levelLabel}</span>
                    <span className="text-sm text-zinc-300">{String(h.symbol)} {String(h.name ?? "")}</span>
                    <span className="text-xs text-zinc-500 ml-auto">
                      浮盈 <span className={Number(h.profit_pct) >= 0 ? "text-green-400" : "text-red-400"}>
                        {Number(h.profit_pct) >= 0 ? "+" : ""}{Number(h.profit_pct).toFixed(2)}%
                      </span>
                    </span>
                  </div>
                  <div className="grid grid-cols-3 gap-2 text-xs text-zinc-500 mt-2">
                    <span>距硬止损 {Number(risk.stop_loss_distance).toFixed(1)}%</span>
                    <span>距大哥黄 {Number(risk.yellow_distance).toFixed(1)}%</span>
                    <span>T+3 倒计时 {Number(risk.t3_countdown)} 天</span>
                  </div>
                  {notes.length > 0 && (
                    <ul className="mt-2 space-y-0.5">
                      {notes.map((n, j) => (
                        <li key={j} className="text-xs text-amber-300">⚠ {n}</li>
                      ))}
                    </ul>
                  )}
                </div>
              );
            })}
          </div>
        </Section>
      )}

      {/* 大盘状态（放在明日建议上方，便于与建议对照） */}
      <div className="flex gap-3 flex-wrap">
        <StatusBadge
          label="大盘"
          value={market.allow_buy ? "允许买入" : "禁止买入"}
          positive={!!market.allow_buy}
        />
        <StatusBadge
          label="强弱"
          value={market.is_strong ? "强势" : "弱势"}
          positive={!!market.is_strong}
        />
        {Boolean(cooldown.active) && (
          <StatusBadge label="冷却" value={`剩余 ${String(cooldown.remaining_days)} 天`} positive={false} />
        )}
        {decisionDate && (
          <span className="text-xs text-zinc-500 self-center ml-auto">决策日期：{decisionDate}</span>
        )}
      </div>

      {/* 明日建议（仅在有最新数据时显示） */}
      {decision && (
        <Section title={
          (decision as Record<string, unknown>).has_latest_data
            ? `明日建议（基于 ${decisionDate} 收盘数据）`
            : "明日建议（数据未更新，仅参考）"
        }>
          {actions.length === 0 ? (
            <p className="text-zinc-500 text-sm">无动作</p>
          ) : (
            <div className="space-y-2">
              {actions.map((a, i) => (
                <div key={i} className={`rounded-lg border p-3 ${ACTION_COLORS[a.kind as string] ?? "bg-zinc-800/60 border-zinc-700"}`}>
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-xs font-bold uppercase text-zinc-100">
                      {ACTION_LABELS[a.kind as string] ?? String(a.kind)}
                    </span>
                    {Boolean(a.symbol) && (
                      <span className="text-sm text-zinc-300">{String(a.symbol)} {String(a.name ?? "")}</span>
                    )}
                  </div>
                  {Boolean(a.reason) && <p className="text-xs text-zinc-400">{String(a.reason)}</p>}
                  {Boolean(a.exec_desc) && <p className="text-xs text-zinc-500 mt-1">{String(a.exec_desc)}</p>}
                  {(a.kind === "buy") && (
                    <p className="text-xs text-zinc-400 mt-1">
                      ≈{String(a.estimated_shares)}股 · 金额 {Number(a.amount).toLocaleString()}
                    </p>
                  )}
                  {(a.kind === "sell") && Boolean(a.shares) && (
                    <p className="text-xs text-zinc-400 mt-1">{String(a.shares)}股</p>
                  )}
                </div>
              ))}
            </div>
          )}
        </Section>
      )}

      {/* 警告 */}
      {warnings.length > 0 && (
        <Section title="警告">
          <ul className="space-y-1">
            {warnings.map((w, i) => (
              <li key={i} className="text-xs text-amber-400">⚠ {w}</li>
            ))}
          </ul>
        </Section>
      )}
      {/* Toast */}
      {toast && (
        <div className={`fixed top-6 right-6 z-50 px-4 py-3 rounded-lg shadow-lg text-sm ${
          toast.type === "success"
            ? "bg-green-900/90 border border-green-700 text-green-200"
            : "bg-red-900/90 border border-red-700 text-red-200"
        }`}>
          {toast.msg}
        </div>
      )}

      {/* 添加交易 Modal */}
      {addTxModalOpen && (
        <AddTransactionModal
          onClose={() => setAddTxModalOpen(false)}
          onSubmit={(tx) => addTxMutation.mutate(tx)}
        />
      )}

      {/* 交易记录 Modal */}
      {txLogModalOpen && (
        <TransactionLogModal
          onClose={() => setTxLogModalOpen(false)}
        />
      )}
    </div>
  );
}

function Section({ title, children, actions }: { title: string; children: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <div className="bg-zinc-900/50 rounded-lg border border-zinc-800 p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-zinc-200">{title}</h3>
        {actions}
      </div>
      {children}
    </div>
  );
}

function StatusBadge({ label, value, positive }: { label: string; value: string; positive: boolean }) {
  return (
    <div className={`px-3 py-1.5 rounded-md border text-sm ${positive ? "border-green-700 bg-green-900/30 text-green-300" : "border-red-700 bg-red-900/30 text-red-300"}`}>
      <span className="text-zinc-400 mr-1">{label}:</span>{value}
    </div>
  );
}

function SymbolSearchInput({ value, onChange }: { value: string; onChange: (code: string) => void }) {
  const { data: stocks = [] } = useQuery({ queryKey: ["stocks"], queryFn: api.stocks });
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(false);

  // 当前选中的股票（用于展示 label）
  const selected = useMemo(
    () => stocks.find((s: StockItem) => s.code === value),
    [stocks, value]
  );

  const displayValue = editing
    ? search
    : selected
      ? `${selected.name} (${selected.code}.${selected.exchange})`
      : value;

  const filtered = useMemo(() => {
    if (!search) return [];
    const q = search.toLowerCase();
    return stocks.filter((s: StockItem) =>
      s.code.includes(q) || s.name.toLowerCase().includes(q)
    ).slice(0, 8);
  }, [stocks, search]);

  return (
    <div className="relative">
      <input
        type="text"
        placeholder="代码/名称"
        value={displayValue}
        onFocus={() => { setEditing(true); setSearch(""); setOpen(true); }}
        onBlur={() => setTimeout(() => { setOpen(false); setEditing(false); }, 150)}
        onChange={(e) => { setSearch(e.target.value); onChange(e.target.value); setOpen(true); }}
        className="w-full bg-zinc-950 border border-zinc-800 rounded-md px-2 py-1.5 text-xs text-zinc-200 focus:outline-none focus:border-blue-500"
      />
      {open && filtered.length > 0 && (
        <div className="absolute z-20 mt-1 w-64 max-h-48 overflow-auto bg-zinc-950 border border-zinc-800 rounded-md shadow-lg">
          {filtered.map((s: StockItem) => (
            <button
              key={s.code}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => {
                onChange(s.code);
                setOpen(false);
                setEditing(false);
              }}
              className="w-full text-left px-2 py-1.5 text-xs text-zinc-300 hover:bg-zinc-800"
            >
              <span className="text-zinc-200">{s.name}</span>
              <span className="text-zinc-500 ml-1.5">({s.code}.{s.exchange})</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// PLACEHOLDER_ADD_MODAL
function AddTransactionModal({
  onClose,
  onSubmit,
}: {
  onClose: () => void;
  onSubmit: (tx: Record<string, unknown>) => void;
}) {
  const [type, setType] = useState<"B" | "S">("B");
  const [symbol, setSymbol] = useState("");
  const [shares, setShares] = useState(100);
  const [totalAmount, setTotalAmount] = useState(1000);
  const [tradeDate, setTradeDate] = useState(new Date().toISOString().slice(0, 10));
  const [error, setError] = useState("");

  const handleSubmit = () => {
    if (!symbol || !/^\d{6}$/.test(symbol)) {
      setError("代码必须是 6 位数字（请从下拉中选择）");
      return;
    }
    if (shares <= 0 || shares % 100 !== 0) {
      setError("股数必须是 100 的整数倍且 > 0");
      return;
    }
    if (totalAmount <= 0) {
      setError("总成交价必须 > 0");
      return;
    }
    if (!tradeDate) {
      setError("请选择交易日期");
      return;
    }
    onSubmit({ type, symbol, shares, total_amount: totalAmount, trade_date: tradeDate });
  };

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-6 w-full max-w-md" onClick={(e) => e.stopPropagation()}>
        <h2 className="text-lg font-semibold text-zinc-200 mb-4">添加交易</h2>

        <div className="space-y-3">
          <div>
            <label className="text-xs text-zinc-500 mb-1.5 block">类型</label>
            <div className="flex gap-2">
              <button
                onClick={() => setType("B")}
                className={`flex-1 px-4 py-2 rounded-md text-sm font-medium transition-colors ${
                  type === "B"
                    ? "bg-green-600 text-white"
                    : "bg-zinc-800 text-zinc-400 hover:bg-zinc-700"
                }`}
              >
                买入 (B)
              </button>
              <button
                onClick={() => setType("S")}
                className={`flex-1 px-4 py-2 rounded-md text-sm font-medium transition-colors ${
                  type === "S"
                    ? "bg-red-600 text-white"
                    : "bg-zinc-800 text-zinc-400 hover:bg-zinc-700"
                }`}
              >
                卖出 (S)
              </button>
            </div>
          </div>
          <div>
            <label className="text-xs text-zinc-500 mb-1.5 block">代码</label>
            <SymbolSearchInput value={symbol} onChange={setSymbol} />
          </div>
          <div>
            <label className="text-xs text-zinc-500 mb-1.5 block">股数</label>
            <input type="number" step="100" value={shares} onChange={(e) => setShares(Number(e.target.value))}
              className="w-full bg-zinc-950 border border-zinc-800 rounded-md px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-blue-500" />
          </div>
          <div>
            <label className="text-xs text-zinc-500 mb-1.5 block">总成交价（含交易费用）</label>
            <input type="number" step="0.01" value={totalAmount} onChange={(e) => setTotalAmount(Number(e.target.value))}
              className="w-full bg-zinc-950 border border-zinc-800 rounded-md px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-blue-500" />
            <p className="text-xs text-zinc-600 mt-1">成本价 = 总成交价 / 股数 = {shares > 0 ? (totalAmount / shares).toFixed(4) : "-"}</p>
          </div>
          <div>
            <label className="text-xs text-zinc-500 mb-1.5 block">交易日期</label>
            <input type="date" value={tradeDate} onChange={(e) => setTradeDate(e.target.value)}
              className="w-full bg-zinc-950 border border-zinc-800 rounded-md px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-blue-500" />
          </div>
        </div>

        {error && (
          <div className="mt-3 p-2 bg-red-950/50 border border-red-900 rounded-md text-red-300 text-xs">
            {error}
          </div>
        )}

        <div className="flex gap-2 justify-end mt-4">
          <button onClick={onClose} className="px-4 py-2 rounded-md bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-sm">
            取消
          </button>
          <button onClick={handleSubmit} className="px-4 py-2 rounded-md bg-blue-600 hover:bg-blue-500 text-white text-sm">
            添加
          </button>
        </div>
      </div>
    </div>
  );
}

function TransactionLogModal({ onClose }: { onClose: () => void }) {
  const { data, isPending } = useQuery({
    queryKey: ["transactions"],
    queryFn: api.listTransactions,
  });

  const queryClient = useQueryClient();
  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.deleteTransaction(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["transactions"] });
      queryClient.invalidateQueries({ queryKey: ["advisor-latest"] });
    },
  });

  const transactions = (data?.transactions ?? []) as Array<Record<string, unknown>>;
  const sorted = [...transactions].sort((a, b) => {
    const dateA = String(a.trade_date ?? "");
    const dateB = String(b.trade_date ?? "");
    if (dateA !== dateB) return dateB.localeCompare(dateA);
    return String(b.created_at ?? "").localeCompare(String(a.created_at ?? ""));
  });

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-6 w-full max-w-3xl max-h-[80vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
        <h2 className="text-lg font-semibold text-zinc-200 mb-4">交易记录</h2>

        {isPending ? (
          <p className="text-zinc-500 text-sm">加载中...</p>
        ) : sorted.length === 0 ? (
          <p className="text-zinc-500 text-sm">暂无交易记录</p>
        ) : (
          <div className="space-y-2">
            <div className="grid grid-cols-[60px_80px_1fr_80px_100px_100px_80px_60px] gap-2 text-xs text-zinc-500 px-2">
              <span>类型</span><span>代码</span><span>名称</span><span>股数</span><span>总成交价</span><span>成本价</span><span>交易日期</span><span></span>
            </div>
            {sorted.map((tx) => {
              const kind = String(tx.type ?? "B");
              const shares = Number(tx.shares ?? 0);
              const amount = Number(tx.total_amount ?? 0);
              const costPrice = shares > 0 ? amount / shares : 0;
              return (
                <div key={String(tx.id)} className="grid grid-cols-[60px_80px_1fr_80px_100px_100px_80px_60px] gap-2 items-center bg-zinc-950 border border-zinc-800 rounded-md px-2 py-1.5">
                  <span className={`text-xs font-medium ${kind === "B" ? "text-green-400" : "text-red-400"}`}>
                    {kind === "B" ? "买入" : "卖出"}
                  </span>
                  <span className="text-xs text-zinc-200">{String(tx.symbol ?? "")}</span>
                  <span className="text-xs text-zinc-400">{String(tx.name ?? "")}</span>
                  <span className="text-xs text-zinc-200 text-right">{shares}</span>
                  <span className="text-xs text-zinc-200 text-right">{amount.toFixed(2)}</span>
                  <span className="text-xs text-zinc-400 text-right">{costPrice.toFixed(4)}</span>
                  <span className="text-xs text-zinc-500">{String(tx.trade_date ?? "")}</span>
                  <button
                    onClick={() => {
                      if (confirm("确定删除该交易？")) {
                        deleteMutation.mutate(String(tx.id));
                      }
                    }}
                    className="text-xs text-red-400 hover:text-red-300"
                  >
                    删除
                  </button>
                </div>
              );
            })}
          </div>
        )}

        <div className="flex justify-end mt-4">
          <button onClick={onClose} className="px-4 py-2 rounded-md bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-sm">
            关闭
          </button>
        </div>
      </div>
    </div>
  );
}
