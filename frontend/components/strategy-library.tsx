"use client";

import { Lightbulb, Pencil, Trash2, Plus } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

export function StrategyLibrary({
  activeKey,
  onSelect,
}: {
  activeKey?: string;
  onSelect?: (key: string) => void;
}) {
  const { data: strategies = [] } = useQuery({ queryKey: ["strategies"], queryFn: api.strategies });

  return (
    <aside className="bg-zinc-900/50 rounded-lg border border-zinc-800 p-4 flex flex-col">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-zinc-200">策略库</h3>
        <button
          className="text-xs px-2 py-1 rounded-md bg-blue-600/80 hover:bg-blue-600 text-white flex items-center gap-1 disabled:opacity-50"
          disabled
          title="开发中"
        >
          <Plus className="w-3 h-3" />
          新建
        </button>
      </div>
      <div className="flex-1 overflow-y-auto space-y-2.5 pr-1">
        {strategies.map((s) => {
          const isActive = activeKey === s.key;
          return (
            <button
              key={s.key}
              onClick={() => onSelect?.(s.key)}
              className={
                "w-full text-left rounded-md p-3 border transition-colors " +
                (isActive
                  ? "bg-zinc-800 border-zinc-700"
                  : "bg-zinc-950/50 border-zinc-800 hover:border-zinc-700")
              }
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className={"w-2 h-2 rounded-full " + (isActive ? "bg-amber-400" : "bg-zinc-700")} />
                  <span className="text-sm font-medium text-zinc-200">{s.name}</span>
                </div>
                <div className="flex items-center gap-1 text-zinc-600">
                  <Lightbulb className="w-3 h-3 hover:text-zinc-400" />
                  <Pencil className="w-3 h-3 hover:text-zinc-400" />
                  <Trash2 className="w-3 h-3 hover:text-zinc-400" />
                </div>
              </div>
              {s.description && (
                <p className="mt-1.5 text-xs text-zinc-500 leading-relaxed">{s.description}</p>
              )}
            </button>
          );
        })}
        {strategies.length === 0 && (
          <div className="text-xs text-zinc-500 py-8 text-center">暂无策略</div>
        )}
      </div>
    </aside>
  );
}
