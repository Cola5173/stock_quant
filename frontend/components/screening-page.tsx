"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { SelectedDetail } from "@/lib/types";

const STRATEGY_TABS = [
  { key: "b1", label: "b1"},
];

export function ScreeningPage() {
  const [activeStrategy, setActiveStrategy] = useState("b1");
  const [selectedDate, setSelectedDate] = useState<string | null>(null);

  const { data: records = [] } = useQuery({
    queryKey: ["selected-records", activeStrategy],
    queryFn: () => api.selectedRecords(activeStrategy),
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
      {/* 策略 Tab 栏 */}
      <div className="flex gap-3 mb-3">
        {STRATEGY_TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => {
              setActiveStrategy(tab.key);
              setSelectedDate(null);
            }}
            className={cn(
              "px-5 py-2 text-sm rounded-full border transition-colors",
              activeStrategy === tab.key
                ? "bg-red-600 border-red-600 text-white"
                : "bg-zinc-900 border-zinc-700 text-zinc-300 hover:border-zinc-500"
            )}
          >
            {tab.label}
          </button>
        ))}
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
        <p className="text-zinc-500 text-center mt-20">暂无选股记录</p>
      )}
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