"use client";

import { useState, useEffect, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Edit, RefreshCw } from "lucide-react";
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
  const queryClient = useQueryClient();
  const [totalCapital, setTotalCapital] = useState(100000);
  const [positions, setPositions] = useState<Array<{ symbol: string; shares: number; cost_price: number; buy_date: string }>>([]);
  const [initialized, setInitialized] = useState(false);
  const [toast, setToast] = useState<{ type: "success" | "error"; msg: string } | null>(null);
  const [addModalOpen, setAddModalOpen] = useState(false);

  const showToast = (type: "success" | "error", msg: string) => {
    setToast({ type, msg });
    setTimeout(() => setToast(null), 3000);
  };

  const { data, isPending, isError } = useQuery({
    queryKey: ["advisor-latest"],
    queryFn: () => api.advisorLatest(),
    refetchInterval: 60_000,
  });

  // 初始化编辑数据（仅在首次加载时同步，避免覆盖用户编辑）
  const positionsData = data?.positions as { total_capital?: number; positions?: Array<Record<string, unknown>> } | null;
  useEffect(() => {
    if (positionsData && !initialized) {
      setTotalCapital(positionsData.total_capital ?? 100000);
      setPositions(
        (positionsData.positions ?? []).map((p) => ({
          symbol: String(p.symbol ?? ""),
          shares: Number(p.shares ?? 0),
          cost_price: Number(p.cost_price ?? 0),
          buy_date: String(p.buy_date ?? ""),
        }))
      );
      setInitialized(true);
    }
  }, [positionsData, initialized]);

  const updateMutation = useMutation({
    mutationFn: (data: Record<string, unknown>) => api.updatePositions(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["advisor-latest"] });
      showToast("success", "持仓保存成功");
    },
    onError: (err: Error) => {
      showToast("error", `保存失败：${err.message}`);
    },
  });

  const recalculate = useMutation({
    mutationFn: () => api.runDecision(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["advisor-latest"] });
    },
  });

  const handleSave = () => {
    updateMutation.mutate({
      total_capital: totalCapital,
      positions: positions.filter((p) => p.symbol && p.shares > 0 && p.cost_price > 0 && p.buy_date),
    });
  };

  const appendPosition = (newPos: { symbol: string; shares: number; cost_price: number; buy_date: string }) => {
    setPositions([...positions, newPos]);
  };

  const removePosition = (index: number) => {
    setPositions(positions.filter((_, i) => i !== index));
  };

  const updatePosition = (index: number, field: string, value: string | number) => {
    const updated = [...positions];
    updated[index] = { ...updated[index], [field]: value };
    setPositions(updated);
  };

  if (isPending) {
    return <div className="flex items-center justify-center h-full text-zinc-500">加载中…</div>;
  }
  if (isError) {
    return <div className="flex items-center justify-center h-full text-zinc-500">加载失败</div>;
  }

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
      {/* 大盘状态 */}
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

      {/* 持仓编辑 */}
      <Section
        title="当前持仓"
        actions={
          <div className="flex gap-2">
            <button
              onClick={handleSave}
              disabled={updateMutation.isPending}
              className="px-3 py-1.5 rounded-md bg-zinc-800 hover:bg-zinc-700 disabled:bg-zinc-700 disabled:text-zinc-500 text-zinc-300 text-xs flex items-center gap-1.5"
            >
              <Edit className="w-3.5 h-3.5" />
              {updateMutation.isPending ? "保存中..." : "保存持仓"}
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
        {/* 总资金 */}
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
          <input
            type="number"
            value={totalCapital}
            onChange={(e) => setTotalCapital(Number(e.target.value))}
            className="w-full bg-zinc-950 border border-zinc-800 rounded-md px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-blue-500"
          />
        </div>

        {/* 持仓列表（编辑） */}
        <div className="mb-2">
          <div className="flex items-center justify-between mb-2">
            <label className="text-xs text-zinc-500">持仓列表（可编辑）</label>
            <button onClick={() => setAddModalOpen(true)} className="text-xs text-blue-400 hover:text-blue-300">+ 添加持仓</button>
          </div>
          {positions.length === 0 ? (
            <p className="text-zinc-500 text-sm py-2">暂无持仓，点击右上角"添加持仓"</p>
          ) : (
            <div className="space-y-2">
              <div className="grid grid-cols-[1.2fr_0.6fr_0.8fr_0.8fr_1fr_1.4fr_50px] gap-2 text-xs text-zinc-500 px-2">
                <span>代码</span><span>仓位</span><span>股数</span><span>成本价</span><span>买入日期</span><span>状态</span><span></span>
              </div>
              {positions.map((p, i) => {
                const holdingInfo = holdings.find((h) => h.symbol === p.symbol);
                const price = holdingInfo ? Number(holdingInfo.current_close) : p.cost_price;
                const marketValue = p.shares * price;
                const positionPct = totalCapital > 0 ? (marketValue / totalCapital) * 100 : 0;
                return (
                  <div key={i}>
                    <div className="grid grid-cols-[1.2fr_0.6fr_0.8fr_0.8fr_1fr_1.4fr_50px] gap-2 items-center">
                      <SymbolSearchInput
                        value={p.symbol}
                        onChange={(code) => updatePosition(i, "symbol", code)}
                      />
                      {/* 仓位列（只读，表格样式） */}
                      <div className="bg-zinc-950 border border-zinc-800 rounded-md px-2 py-1.5 text-xs text-center">
                        <span className={positionPct > 50 ? "text-amber-400" : "text-zinc-300"}>{positionPct.toFixed(1)}%</span>
                      </div>
                      <input
                        type="number"
                        placeholder="股数"
                        value={p.shares}
                        onChange={(e) => updatePosition(i, "shares", Number(e.target.value))}
                        className="bg-zinc-950 border border-zinc-800 rounded-md px-2 py-1.5 text-xs text-zinc-200 focus:outline-none focus:border-blue-500"
                      />
                      <input
                        type="number"
                        step="0.01"
                        placeholder="成本价"
                        value={p.cost_price}
                        onChange={(e) => updatePosition(i, "cost_price", Number(e.target.value))}
                        className="bg-zinc-950 border border-zinc-800 rounded-md px-2 py-1.5 text-xs text-zinc-200 focus:outline-none focus:border-blue-500"
                      />
                      <input
                        type="date"
                        value={p.buy_date}
                        onChange={(e) => updatePosition(i, "buy_date", e.target.value)}
                        className="bg-zinc-950 border border-zinc-800 rounded-md px-2 py-1.5 text-xs text-zinc-200 focus:outline-none focus:border-blue-500"
                      />
                      {/* 状态列（只读，表格样式） */}
                      <div className="bg-zinc-950 border border-zinc-800 rounded-md px-2 py-1.5 text-xs text-zinc-400">
                        {holdingInfo ? (
                          <>
                            持{String(holdingInfo.hold_days)}天 · {Number(holdingInfo.current_close).toFixed(2)}
                            {decisionDate && <span className="text-zinc-600">@{decisionDate}</span>}
                          </>
                        ) : "—"}
                      </div>
                      <button onClick={() => removePosition(i)} className="text-red-400 hover:text-red-300 text-xs">删除</button>
                    </div>
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

      {/* 添加持仓 Modal */}
      {addModalOpen && (
        <AddPositionModal
          onClose={() => setAddModalOpen(false)}
          onSubmit={(p) => {
            appendPosition(p);
            setAddModalOpen(false);
            showToast("success", `已添加 ${p.symbol}，记得点"保存持仓"持久化`);
          }}
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
function AddPositionModal({
  onClose,
  onSubmit,
}: {
  onClose: () => void;
  onSubmit: (p: { symbol: string; shares: number; cost_price: number; buy_date: string }) => void;
}) {
  const [symbol, setSymbol] = useState("");
  const [shares, setShares] = useState(100);
  const [costPrice, setCostPrice] = useState(10);
  const [buyDate, setBuyDate] = useState(new Date().toISOString().slice(0, 10));
  const [error, setError] = useState("");

  const handleSubmit = () => {
    if (!symbol || !/^\d{6}$/.test(symbol)) {
      setError("代码必须是 6 位数字（请从下拉中选择）");
      return;
    }
    if (shares <= 0) {
      setError("股数必须 > 0");
      return;
    }
    if (costPrice <= 0) {
      setError("成本价必须 > 0");
      return;
    }
    if (!buyDate) {
      setError("请选择买入日期");
      return;
    }
    onSubmit({ symbol, shares, cost_price: costPrice, buy_date: buyDate });
  };

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-6 w-full max-w-md" onClick={(e) => e.stopPropagation()}>
        <h2 className="text-lg font-semibold text-zinc-200 mb-4">添加持仓</h2>

        <div className="space-y-3">
          <div>
            <label className="text-xs text-zinc-500 mb-1.5 block">代码</label>
            <SymbolSearchInput value={symbol} onChange={setSymbol} />
          </div>
          <div>
            <label className="text-xs text-zinc-500 mb-1.5 block">股数</label>
            <input type="number" value={shares} onChange={(e) => setShares(Number(e.target.value))}
              className="w-full bg-zinc-950 border border-zinc-800 rounded-md px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-blue-500" />
          </div>
          <div>
            <label className="text-xs text-zinc-500 mb-1.5 block">成本价</label>
            <input type="number" step="0.01" value={costPrice} onChange={(e) => setCostPrice(Number(e.target.value))}
              className="w-full bg-zinc-950 border border-zinc-800 rounded-md px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-blue-500" />
          </div>
          <div>
            <label className="text-xs text-zinc-500 mb-1.5 block">买入日期</label>
            <input type="date" value={buyDate} onChange={(e) => setBuyDate(e.target.value)}
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
