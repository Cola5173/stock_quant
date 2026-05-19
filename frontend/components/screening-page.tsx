"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Download, Play, Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { SelectedDetail } from "@/lib/types";

export function ScreeningPage() {
  const [activeStrategy, setActiveStrategy] = useState("b1_small");
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [toast, setToast] = useState<{ type: "success" | "error"; msg: string } | null>(null);
  const [showRunModal, setShowRunModal] = useState(false);
  const queryClient = useQueryClient();

  const { data: strategies = [] } = useQuery({ queryKey: ["strategies"], queryFn: api.strategies });

  const showToast = (type: "success" | "error", msg: string) => {
    setToast({ type, msg });
    setTimeout(() => setToast(null), 3000);
  };

  const { data: records = [] } = useQuery({
    queryKey: ["selected-records", activeStrategy],
    queryFn: () => api.selectedRecords(activeStrategy),
  });

  const runScan = useMutation({
    mutationFn: (params: { strategy: string; date?: string }) =>
      api.runScan(params.strategy, params.date),
    onSuccess: (data) => {
      showToast("success", `选股完成：${data.date} 命中 ${data.candidates_count} 只`);
      setActiveStrategy(data.strategy);
      queryClient.invalidateQueries({ queryKey: ["selected-records", data.strategy] });
      setSelectedDate(data.date);
      setShowRunModal(false);
    },
    onError: (err: Error) => {
      showToast("error", `选股失败：${err.message}`);
    },
  });

  const firstDate = records.length > 0 ? records[0].date : null;
  const currentDate = selectedDate ?? firstDate;

  const { data: detail } = useQuery<SelectedDetail>({
    queryKey: ["selected-detail", activeStrategy, currentDate],
    queryFn: () => api.selectedDetail(activeStrategy, currentDate!),
    enabled: !!currentDate,
  });

  return (
    <div className="h-full flex flex-col p-6">
      {/* 顶部：策略标签 + 执行按钮 */}
      <div className="flex gap-3 mb-3 items-center">
        {strategies.map((s) => (
          <button
            key={s.key}
            onClick={() => { setActiveStrategy(s.key); setSelectedDate(null); }}
            className={cn(
              "px-5 py-2 text-sm rounded-full border transition-colors",
              activeStrategy === s.key
                ? "bg-red-600 border-red-600 text-white"
                : "bg-zinc-900 border-zinc-700 text-zinc-300 hover:border-zinc-500"
            )}
          >
            {s.name}
          </button>
        ))}
        <button
          onClick={() => setShowRunModal(true)}
          className="ml-auto flex items-center gap-1.5 px-4 py-2 text-sm rounded-md bg-blue-600 hover:bg-blue-500 text-white transition-colors"
        >
          <Play className="w-4 h-4" />
          执行选股
        </button>
      </div>

      {/* 日期标签行 */}
      {records.length > 0 && (
        <div className="flex gap-2 mb-5 overflow-x-auto pb-2">
          {records.map((r) => (
            <button
              key={r.date}
              onClick={() => setSelectedDate(r.date)}
              className={cn(
                "shrink-0 px-4 py-1.5 text-sm rounded-full border transition-colors",
                currentDate === r.date
                  ? "bg-red-600 border-red-600 text-white"
                  : "bg-zinc-900 border-zinc-700 text-zinc-400 hover:border-zinc-500"
              )}
            >
              {r.date} ({r.count})
            </button>
          ))}
        </div>
      )}

      {/* 统计信息栏 */}
      {detail && (
        <div className="flex items-center justify-between mb-4 text-sm text-zinc-400">
          <span>共 {detail.candidates_count} 只 · 扫描日期: {detail.scan_date}</span>
          <button
            onClick={() => handleDownload(detail)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md border border-zinc-700 text-zinc-300 hover:border-zinc-500 transition-colors"
          >
            <Download className="w-4 h-4" />
            下载股票列表
          </button>
        </div>
      )}

      {/* 股票表格 */}
      {detail && detail.candidates.length > 0 && (
        <div className="flex-1 overflow-y-auto border border-zinc-800 rounded-lg">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-zinc-900">
              <tr className="text-zinc-400 text-left border-b border-zinc-800">
                <th className="px-4 py-3 font-medium w-12">#</th>
                <th className="px-4 py-3 font-medium">代码</th>
                <th className="px-4 py-3 font-medium">名称</th>
                <th className="px-4 py-3 font-medium text-right">评分</th>
              </tr>
            </thead>
            <tbody>
              {detail.candidates.map((c, i) => (
                <tr key={c.symbol} className="border-t border-zinc-800/50 hover:bg-zinc-800/30">
                  <td className="px-4 py-2.5 text-zinc-500">{i + 1}</td>
                  <td className="px-4 py-2.5 text-zinc-200">{c.symbol}</td>
                  <td className="px-4 py-2.5 text-zinc-200">{c.name}</td>
                  <td className="px-4 py-2.5 text-right text-zinc-200">{c.score != null ? c.score : "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* 空状态 */}
      {!detail && records.length === 0 && (
        <p className="text-zinc-500 text-center mt-20">暂无选股记录，点击"执行选股"开始</p>
      )}

      {/* 执行选股弹框 */}
      {showRunModal && (
        <RunScanModal
          strategies={strategies}
          defaultStrategy={activeStrategy}
          isPending={runScan.isPending}
          onClose={() => setShowRunModal(false)}
          onSubmit={(strategy, date) => runScan.mutate({ strategy, date })}
        />
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
    </div>
  );
}

function RunScanModal({
  strategies,
  defaultStrategy,
  isPending,
  onClose,
  onSubmit,
}: {
  strategies: Array<{ key: string; name: string; description?: string }>;
  defaultStrategy: string;
  isPending: boolean;
  onClose: () => void;
  onSubmit: (strategy: string, date?: string) => void;
}) {
  const [strategy, setStrategy] = useState(defaultStrategy);
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-6 w-full max-w-sm" onClick={(e) => e.stopPropagation()}>
        <h2 className="text-lg font-semibold text-zinc-200 mb-4">执行策略选股</h2>
        <div className="space-y-4">
          <div>
            <label className="text-xs text-zinc-500 mb-1.5 block">策略</label>
            <select
              value={strategy}
              onChange={(e) => setStrategy(e.target.value)}
              className="w-full bg-zinc-950 border border-zinc-800 rounded-md px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-blue-500"
            >
              {strategies.map((s) => (
                <option key={s.key} value={s.key}>{s.name}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs text-zinc-500 mb-1.5 block">选股日期</label>
            <input
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
              className="w-full bg-zinc-950 border border-zinc-800 rounded-md px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-blue-500"
            />
          </div>
        </div>
        <div className="flex gap-2 justify-end mt-5">
          <button onClick={onClose} className="px-4 py-2 rounded-md bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-sm">
            取消
          </button>
          <button
            onClick={() => onSubmit(strategy, date)}
            disabled={isPending}
            className="px-4 py-2 rounded-md bg-blue-600 hover:bg-blue-500 disabled:bg-zinc-700 disabled:text-zinc-500 text-white text-sm flex items-center gap-1.5"
          >
            {isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
            {isPending ? "扫描中..." : "开始选股"}
          </button>
        </div>
      </div>
    </div>
  );
}

function handleDownload(detail: SelectedDetail) {
  const header = "序号,代码,名称,评分\n";
  const rows = detail.candidates
    .map((c, i) => `${i + 1},${c.symbol},${c.name},${c.score ?? ""}`)
    .join("\n");
  const blob = new Blob([header + rows], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `selected_${detail.strategy}_${detail.scan_date}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}