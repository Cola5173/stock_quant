"use client";

import { LineChart, RefreshCw, Loader2 } from "lucide-react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

export function Header({ subtitle, dateRange }: { subtitle?: string; dateRange?: string }) {
  const [now, setNow] = useState<string>("");

  useEffect(() => {
    const tick = () => {
      const d = new Date();
      const pad = (n: number) => String(n).padStart(2, "0");
      setNow(`${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`);
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);
  const statusQuery = useQuery({
    queryKey: ["fetch-status"],
    queryFn: api.fetchStatus,
    refetchInterval: (q) => (q.state.data?.running ? 2000 : false),
  });

  const trigger = useMutation({
    mutationFn: () => api.fetchLatest("akshare"),
    onSuccess: () => statusQuery.refetch(),
  });

  const running = !!statusQuery.data?.running;
  const lastError = statusQuery.data?.error;
  const lastFinishedAt = statusQuery.data?.finished_at;

  return (
    <header className="h-14 shrink-0 flex items-center justify-between px-6 border-b border-zinc-800 bg-zinc-950">
      <div className="flex items-center gap-3">
        <LineChart className="w-5 h-5 text-blue-500" />
        <div className="flex flex-col leading-tight">
          <span className="text-base font-bold text-zinc-100">Cola Quant</span>
          {subtitle && <span className="text-[10px] text-zinc-500">{subtitle}</span>}
        </div>
      </div>
      <div className="flex items-center gap-3">
        {dateRange && (
          <span className="text-xs px-2.5 py-1 rounded-md bg-green-500/10 text-green-400 border border-green-500/30">
            真实数据 · {dateRange}
          </span>
        )}
        {running && (
          <span className="text-xs text-zinc-400">
            拉取中…{statusQuery.data?.source ? `（${statusQuery.data.source}）` : ""}
          </span>
        )}
        {!running && lastError && (
          <span className="text-xs text-red-400" title={lastError}>
            上次失败
          </span>
        )}
        {!running && !lastError && lastFinishedAt && (
          <span className="text-xs text-zinc-500">
            上次完成 {lastFinishedAt.slice(11, 16)}
          </span>
        )}
        <button
          onClick={() => !running && trigger.mutate()}
          disabled={running || trigger.isPending}
          className="text-xs px-3 py-1.5 rounded-md border border-zinc-800 text-zinc-300 hover:bg-zinc-800 flex items-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {running ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
          拉取最新数据
        </button>
        <span className="text-xs text-zinc-400 font-mono tabular-nums">{now}</span>
      </div>
    </header>
  );
}
