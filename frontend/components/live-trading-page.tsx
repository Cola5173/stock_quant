"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Edit, RefreshCw } from "lucide-react";

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
  const [editModalOpen, setEditModalOpen] = useState(false);

  const { data, isPending, isError } = useQuery({
    queryKey: ["advisor-latest"],
    queryFn: () => api.advisorLatest(),
    refetchInterval: 60_000,
  });

  const recalculate = useMutation({
    mutationFn: () => api.runDecision(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["advisor-latest"] });
    },
  });

  if (isPending) {
    return <div className="flex items-center justify-center h-full text-zinc-500">加载中…</div>;
  }
  if (isError) {
    return <div className="flex items-center justify-center h-full text-zinc-500">加载失败</div>;
  }

  const positions = data?.positions as { total_capital?: number; positions?: Array<Record<string, unknown>> } | null;
  const decision = data?.decision as Record<string, unknown> | null;
  const holdings = (decision?.holdings ?? []) as Array<Record<string, unknown>>;
  const actions = (decision?.actions ?? []) as Array<Record<string, unknown>>;
  const market = (decision?.market ?? {}) as Record<string, unknown>;
  const cooldown = (decision?.cooldown ?? {}) as Record<string, unknown>;
  const warnings = (decision?.warnings ?? []) as string[];
  const decisionDate = decision?.date as string | undefined;

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

      {/* 持仓表 */}
      <Section
        title="当前持仓"
        actions={
          <div className="flex gap-2">
            <button
              onClick={() => setEditModalOpen(true)}
              className="px-3 py-1.5 rounded-md bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-xs flex items-center gap-1.5"
            >
              <Edit className="w-3.5 h-3.5" />
              编辑持仓
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
        {holdings.length === 0 ? (
          <p className="text-zinc-500 text-sm">空仓</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-zinc-400 border-b border-zinc-800">
                <th className="text-left py-2 px-2">代码</th>
                <th className="text-left py-2 px-2">名称</th>
                <th className="text-right py-2 px-2">持有天数</th>
                <th className="text-right py-2 px-2">成本</th>
                <th className="text-right py-2 px-2">现价</th>
                <th className="text-right py-2 px-2">浮盈</th>
                <th className="text-right py-2 px-2">止盈档</th>
              </tr>
            </thead>
            <tbody>
              {holdings.map((h, i) => (
                <tr key={i} className="border-b border-zinc-800/50">
                  <td className="py-2 px-2 text-zinc-200">{h.symbol as string}</td>
                  <td className="py-2 px-2 text-zinc-300">{h.name as string}</td>
                  <td className="py-2 px-2 text-right">{h.hold_days as number}</td>
                  <td className="py-2 px-2 text-right">{(h.cost_price as number)?.toFixed(2)}</td>
                  <td className="py-2 px-2 text-right">{(h.current_close as number)?.toFixed(2)}</td>
                  <td className={`py-2 px-2 text-right font-medium ${(h.profit_pct as number) >= 0 ? "text-green-400" : "text-red-400"}`}>
                    {(h.profit_pct as number) >= 0 ? "+" : ""}{(h.profit_pct as number)?.toFixed(2)}%
                  </td>
                  <td className="py-2 px-2 text-right">{h.tp_level_done as number}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>

      {/* 明日动作 */}
      <Section title="明日动作">
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

      {/* 编辑模态框 */}
      {editModalOpen && (
        <EditPositionsModal
          initialData={positions ?? { total_capital: 100000, positions: [] }}
          onClose={() => setEditModalOpen(false)}
          onSave={() => {
            setEditModalOpen(false);
            queryClient.invalidateQueries({ queryKey: ["advisor-latest"] });
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

function EditPositionsModal({
  initialData,
  onClose,
  onSave,
}: {
  initialData: { total_capital?: number; positions?: Array<Record<string, unknown>> };
  onClose: () => void;
  onSave: () => void;
}) {
  const [totalCapital, setTotalCapital] = useState(initialData.total_capital ?? 100000);
  const [positions, setPositions] = useState<Array<{ symbol: string; shares: number; cost_price: number; buy_date: string }>>(
    (initialData.positions ?? []).map((p) => ({
      symbol: String(p.symbol ?? ""),
      shares: Number(p.shares ?? 0),
      cost_price: Number(p.cost_price ?? 0),
      buy_date: String(p.buy_date ?? ""),
    }))
  );

  const updateMutation = useMutation({
    mutationFn: (data: Record<string, unknown>) => api.updatePositions(data),
    onSuccess: () => onSave(),
  });

  const handleSave = () => {
    updateMutation.mutate({
      total_capital: totalCapital,
      positions: positions.filter((p) => p.symbol && p.shares > 0 && p.cost_price > 0 && p.buy_date),
    });
  };

  const addPosition = () => {
    setPositions([...positions, { symbol: "", shares: 100, cost_price: 10.0, buy_date: new Date().toISOString().slice(0, 10) }]);
  };

  const removePosition = (index: number) => {
    setPositions(positions.filter((_, i) => i !== index));
  };

  const updatePosition = (index: number, field: string, value: string | number) => {
    const updated = [...positions];
    updated[index] = { ...updated[index], [field]: value };
    setPositions(updated);
  };

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-6 w-full max-w-3xl max-h-[80vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
        <h2 className="text-lg font-semibold text-zinc-200 mb-4">编辑持仓</h2>

        {/* 总资金 */}
        <div className="mb-4">
          <label className="text-xs text-zinc-500 mb-1.5 block">总资金</label>
          <input
            type="number"
            value={totalCapital}
            onChange={(e) => setTotalCapital(Number(e.target.value))}
            className="w-full bg-zinc-950 border border-zinc-800 rounded-md px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-blue-500"
          />
        </div>

        {/* 持仓列表 */}
        <div className="mb-4">
          <div className="flex items-center justify-between mb-2">
            <label className="text-xs text-zinc-500">持仓列表</label>
            <button onClick={addPosition} className="text-xs text-blue-400 hover:text-blue-300">+ 添加持仓</button>
          </div>
          <div className="space-y-2">
            {positions.map((p, i) => (
              <div key={i} className="grid grid-cols-[1fr_1fr_1fr_1fr_auto] gap-2 items-center">
                <input
                  type="text"
                  placeholder="代码"
                  value={p.symbol}
                  onChange={(e) => updatePosition(i, "symbol", e.target.value)}
                  className="bg-zinc-950 border border-zinc-800 rounded-md px-2 py-1.5 text-xs text-zinc-200 focus:outline-none focus:border-blue-500"
                />
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
                <button onClick={() => removePosition(i)} className="text-red-400 hover:text-red-300 text-xs">删除</button>
              </div>
            ))}
          </div>
        </div>

        {/* 错误提示 */}
        {updateMutation.isError && (
          <div className="mb-4 p-3 bg-red-950/50 border border-red-900 rounded-md text-red-300 text-xs">
            保存失败：{(updateMutation.error as Error).message}
          </div>
        )}

        {/* 按钮 */}
        <div className="flex gap-2 justify-end">
          <button onClick={onClose} className="px-4 py-2 rounded-md bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-sm">
            取消
          </button>
          <button
            onClick={handleSave}
            disabled={updateMutation.isPending}
            className="px-4 py-2 rounded-md bg-blue-600 hover:bg-blue-500 disabled:bg-zinc-700 disabled:text-zinc-500 text-white text-sm"
          >
            {updateMutation.isPending ? "保存中..." : "保存"}
          </button>
        </div>
      </div>
    </div>
  );
}