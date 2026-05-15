"use client";

import { LineChart, Search, BarChart3, RefreshCcw, Settings } from "lucide-react";
import { cn } from "@/lib/utils";
import { useState } from "react";

const NAV_ITEMS = [
  { key: "overview", label: "概览", icon: BarChart3, disabled: true },
  { key: "reversal", label: "反转", icon: RefreshCcw, disabled: true },
  { key: "backtest", label: "回测", icon: LineChart, disabled: false },
  { key: "screening", label: "选股", icon: Search, disabled: false },
] as const;

export type NavKey = (typeof NAV_ITEMS)[number]["key"];

export function Sidebar({ active, onChange }: { active: NavKey; onChange: (k: NavKey) => void }) {
  return (
    <aside className="w-16 shrink-0 bg-zinc-950 border-r border-zinc-800 flex flex-col items-center py-3 gap-1.5">
      <div className="w-9 h-9 rounded-lg bg-blue-600 flex items-center justify-center mb-3 shrink-0">
        <LineChart className="w-5 h-5 text-white" />
      </div>
      <div className="flex-1 flex flex-col items-center gap-1.5">
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon;
          const isActive = active === item.key;
          return (
            <button
              key={item.key}
              onClick={() => !item.disabled && onChange(item.key)}
              disabled={item.disabled}
              className={cn(
                "w-12 h-12 rounded-lg flex flex-col items-center justify-center gap-0.5 transition-colors",
                item.disabled && "opacity-40 cursor-not-allowed",
                isActive
                  ? "bg-blue-600/20 text-blue-400"
                  : "text-zinc-500 hover:text-zinc-300 hover:bg-zinc-800/60"
              )}
              title={item.label}
            >
              <Icon className="w-4 h-4" />
              <span className="text-[10px]">{item.label}</span>
            </button>
          );
        })}
      </div>
      <button
        className="w-12 h-12 rounded-lg flex flex-col items-center justify-center gap-0.5 text-zinc-500 hover:text-zinc-300 hover:bg-zinc-800/60"
        title="设置"
      >
        <Settings className="w-4 h-4" />
        <span className="text-[10px]">设置</span>
      </button>
    </aside>
  );
}

export function useNav() {
  return useState<NavKey>("backtest");
}
