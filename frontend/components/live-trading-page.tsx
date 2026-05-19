"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

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
  const { data, isPending, isError } = useQuery({
    queryKey: ["advisor-latest"],
    queryFn: () => api.advisorLatest(),
    refetchInterval: 60_000,
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
      <Section title="当前持仓">
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
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-zinc-900/50 rounded-lg border border-zinc-800 p-4">
      <h3 className="text-sm font-semibold text-zinc-200 mb-3">{title}</h3>
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