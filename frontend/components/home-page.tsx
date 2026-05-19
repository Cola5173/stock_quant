"use client";

import { LineChart, Search } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { NavKey } from "@/components/sidebar";

export function HomePage({ onNavigate }: { onNavigate: (k: NavKey) => void }) {
  const { data: stats } = useQuery({ queryKey: ["home-stats"], queryFn: api.stats });

  const features = [
    {
      icon: LineChart,
      title: "单股回测",
      desc: "基于 vnpy 引擎，分钟级完成完整 K 线回测，输出收益率、回撤、夏普、交易明细。",
      action: () => onNavigate("backtest"),
      cta: "进入回测",
    },
    {
      icon: Search,
      title: "选股扫描",
      desc: "全市场策略筛选 + LLM 两阶段打分，自动产出每日候选与买入信号。",
      action: () => onNavigate("screening"),
      cta: "进入选股",
      disabled: true,
    },
  ];

  return (
    <div className="max-w-5xl mx-auto h-full overflow-y-auto pr-2">
      {/* Hero */}
      <div className="mt-4 mb-8">
        <div className="flex items-center gap-3 mb-3">
          <div className="w-12 h-12 rounded-xl bg-blue-600 flex items-center justify-center">
            <LineChart className="w-7 h-7 text-white" />
          </div>
          <div>
            <h1 className="text-3xl font-bold text-zinc-100">Cola Quant</h1>
            <p className="text-sm text-zinc-500">A 股量化回测平台 · 自用工具</p>
          </div>
        </div>
        <p className="text-zinc-400 leading-relaxed max-w-3xl">
          一个面向个人投资者的 A 股量化研究平台。覆盖
          <span className="text-zinc-200">数据获取、策略回测、全市场扫描、LLM 辅助决策</span>
          的完整链路；前端为 Next.js + TradingView 图表，后端为 FastAPI + vnpy 回测引擎。
        </p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-3 gap-4 mb-8">
        <StatCard label="可选股票" value={stats?.stock_count ?? "—"} hint="A 股全市场（已过滤 ST）" />
        <StatCard label="可用策略" value={stats?.strategy_count ?? "—"} hint="实现于 strategy/ 模块" />
        <StatCard label="数据源" value={stats?.data_source_count ?? "—"} hint="Tushare / AkShare / BaoStock" />
      </div>

      {/* Features */}
      <h2 className="text-lg font-semibold text-zinc-200 mb-3">功能模块</h2>
      <div className="grid grid-cols-3 gap-4 mb-8">
        {features.map((f) => {
          const Icon = f.icon;
          return (
            <div
              key={f.title}
              className="bg-zinc-900/50 rounded-lg border border-zinc-800 p-5 flex flex-col"
            >
              <Icon className="w-5 h-5 text-blue-400 mb-3" />
              <h3 className="text-base font-semibold text-zinc-100 mb-1.5">{f.title}</h3>
              <p className="text-xs text-zinc-500 leading-relaxed flex-1 mb-4">{f.desc}</p>
              <button
                onClick={f.action}
                disabled={f.disabled}
                className={
                  "text-xs px-3 py-1.5 rounded-md border transition-colors w-fit " +
                  (f.disabled
                    ? "border-zinc-800 text-zinc-600 cursor-not-allowed"
                    : "border-blue-600/40 text-blue-400 hover:bg-blue-600/10")
                }
              >
                {f.disabled ? "开发中" : f.cta} →
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function StatCard({ label, value, hint }: { label: string; value: number | string; hint: string }) {
  return (
    <div className="bg-zinc-900/50 rounded-lg border border-zinc-800 p-4">
      <div className="text-xs text-zinc-500">{label}</div>
      <div className="text-2xl font-bold text-zinc-100 mt-1">{value}</div>
      <div className="text-[11px] text-zinc-600 mt-0.5">{hint}</div>
    </div>
  );
}
