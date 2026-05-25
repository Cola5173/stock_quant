"use client";

import { LineChart, Search, CandlestickChart, FlaskConical, Settings, Activity, BarChart3, Wallet } from "lucide-react";
import { cn } from "@/lib/utils";
import { useState } from "react";

const NAV_ITEMS = [
  { key: "chart", label: "K线图表", icon: CandlestickChart },
  { key: "backtest", label: "个股回测", icon: FlaskConical },
  { key: "screening", label: "策略选股", icon: Search },
  { key: "portfolio_backtest", label: "策略回测", icon: BarChart3 },
  { key: "live", label: "模拟盘", icon: Activity },
  { key: "etf", label: "ETF", icon: Wallet },
] as const;

export type NavKey = "home" | "settings" | (typeof NAV_ITEMS)[number]["key"];

export function Sidebar({ active, onChange }: { active: NavKey; onChange: (k: NavKey) => void }) {
  return (
    <aside className="w-20 shrink-0 bg-zinc-950 border-r border-zinc-800 flex flex-col items-center py-3 gap-2">
      <button
        onClick={() => onChange("home")}
        className={cn(
          "w-14 h-14 rounded-lg flex flex-col items-center justify-center gap-1 mb-3 shrink-0 transition-colors",
          active === "home"
            ? "bg-blue-600/20 text-blue-400"
            : "text-zinc-500 hover:text-zinc-300 hover:bg-zinc-800/60"
        )}
        title="首页"
      >
        <LineChart className="w-5 h-5" />
        <span className="text-xs">首页</span>
      </button>
      <div className="flex-1 flex flex-col items-center gap-2">
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon;
          const isActive = active === item.key;
          return (
            <button
              key={item.key}
              onClick={() => onChange(item.key)}
              className={cn(
                "w-14 h-14 rounded-lg flex flex-col items-center justify-center gap-1 transition-colors",
                isActive
                  ? "bg-blue-600/20 text-blue-400"
                  : "text-zinc-500 hover:text-zinc-300 hover:bg-zinc-800/60"
              )}
              title={item.label}
            >
              <Icon className="w-5 h-5" />
              <span className="text-xs">{item.label}</span>
            </button>
          );
        })}
      </div>
      <button
        onClick={() => onChange("settings")}
        className={cn(
          "w-14 h-14 rounded-lg flex flex-col items-center justify-center gap-1 transition-colors",
          active === "settings"
            ? "bg-blue-600/20 text-blue-400"
            : "text-zinc-500 hover:text-zinc-300 hover:bg-zinc-800/60"
        )}
        title="设置"
      >
        <Settings className="w-5 h-5" />
        <span className="text-xs">设置</span>
      </button>
    </aside>
  );
}

export function useNav() {
  return useState<NavKey>("home");
}
