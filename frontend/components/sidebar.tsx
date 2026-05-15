"use client";

import { LineChart, Search, Library, CandlestickChart, FlaskConical } from "lucide-react";
import { cn } from "@/lib/utils";
import { useState } from "react";

const NAV_ITEMS = [
  { key: "chart", label: "K线图表", icon: CandlestickChart },
  { key: "backtest", label: "回测", icon: FlaskConical },
  { key: "screening", label: "选股", icon: Search },
  { key: "library", label: "策略库", icon: Library },
] as const;

export type NavKey = "home" | (typeof NAV_ITEMS)[number]["key"];

export function Sidebar({ active, onChange }: { active: NavKey; onChange: (k: NavKey) => void }) {
  return (
    <aside className="w-20 shrink-0 bg-zinc-950 border-r border-zinc-800 flex flex-col items-center py-3 gap-2">
      <button
        onClick={() => onChange("home")}
        className={cn(
          "w-11 h-11 rounded-lg flex items-center justify-center mb-3 shrink-0 transition-colors",
          active === "home"
            ? "bg-blue-600 ring-2 ring-blue-400"
            : "bg-blue-600 hover:bg-blue-500"
        )}
        title="首页"
      >
        <LineChart className="w-6 h-6 text-white" />
      </button>
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
    </aside>
  );
}

export function useNav() {
  return useState<NavKey>("home");
}
