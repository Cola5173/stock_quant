"use client";

import { LineChart, Search } from "lucide-react";
import { cn } from "@/lib/utils";
import { useState } from "react";

const NAV_ITEMS = [
  { key: "backtest", label: "回测", icon: LineChart },
  { key: "screening", label: "选股", icon: Search },
] as const;

export type NavKey = (typeof NAV_ITEMS)[number]["key"];

export function Sidebar({ active, onChange }: { active: NavKey; onChange: (k: NavKey) => void }) {
  return (
    <aside className="w-16 shrink-0 bg-zinc-950 border-r border-zinc-800 flex flex-col items-center py-4 gap-2">
      <div className="w-9 h-9 rounded-lg bg-blue-600 flex items-center justify-center mb-4">
        <LineChart className="w-5 h-5 text-white" />
      </div>
      {NAV_ITEMS.map((item) => {
        const Icon = item.icon;
        const isActive = active === item.key;
        return (
          <button
            key={item.key}
            onClick={() => onChange(item.key)}
            className={cn(
              "w-12 h-12 rounded-lg flex flex-col items-center justify-center gap-0.5 transition-colors",
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
    </aside>
  );
}

export function useNav() {
  return useState<NavKey>("backtest");
}
