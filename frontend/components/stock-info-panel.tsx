"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Building2, Users, Phone, Globe, MapPin, Calendar, Banknote } from "lucide-react";

const INFO_FIELDS = [
  { key: "short_name", label: "公司简称", icon: Building2 },
  { key: "company_name", label: "公司全称" },
  { key: "main_business", label: "主营业务" },
  { key: "legal_representative", label: "法人代表", icon: Users },
  { key: "industry", label: "所属行业" },
  { key: "market", label: "所属市场" },
  { key: "reg_capital", label: "注册资本", icon: Banknote, format: "capital" },
  { key: "established_date", label: "成立日期", icon: Calendar },
  { key: "listed_date", label: "上市日期", icon: Calendar },
  { key: "telephone", label: "联系电话", icon: Phone },
  { key: "website", label: "官网", icon: Globe },
  { key: "reg_address", label: "注册地址", icon: MapPin },
  { key: "总市值", label: "总市值", icon: Banknote, format: "capital" },
  { key: "流通市值", label: "流通市值", icon: Banknote, format: "capital" },
] as const;

function formatValue(value: string | number | null, format?: string): string {
  if (value == null || value === "None") return "—";
  if (format === "timestamp") {
    const ts = Number(value);
    if (!isNaN(ts) && ts > 1e10) {
      return new Date(ts).toLocaleDateString("zh-CN");
    }
    return String(value);
  }
  if (format === "capital") {
    const num = Number(value);
    if (!isNaN(num)) {
      if (num >= 1e8) return `${(num / 1e8).toFixed(2)} 亿`;
      if (num >= 1e4) return `${(num / 1e4).toFixed(0)} 万`;
    }
    return String(value);
  }
  return String(value);
}

export function StockInfoPanel({ code }: { code: string }) {
  const { data, isPending, isError } = useQuery({
    queryKey: ["stock-info", code],
    queryFn: () => api.stockInfo(code),
    enabled: !!code,
    staleTime: 5 * 60_000,
  });

  if (!code) {
    return (
      <div className="bg-zinc-900/50 rounded-lg border border-zinc-800 p-4 h-full flex items-center justify-center">
        <span className="text-xs text-zinc-500">选择股票后显示详情</span>
      </div>
    );
  }

  if (isPending) {
    return (
      <div className="bg-zinc-900/50 rounded-lg border border-zinc-800 p-4 h-full flex items-center justify-center">
        <span className="text-xs text-zinc-500">加载中…</span>
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="bg-zinc-900/50 rounded-lg border border-zinc-800 p-4 h-full flex items-center justify-center">
        <span className="text-xs text-zinc-500">暂无信息</span>
      </div>
    );
  }

  const intro = data["introduction"];

  return (
    <div className="bg-zinc-900/50 rounded-lg border border-zinc-800 p-4 overflow-y-auto h-full">
      <h3 className="text-sm font-semibold text-zinc-200 mb-3">个股信息</h3>

      {intro && intro !== "None" && (
        <p className="text-xs text-zinc-400 leading-relaxed mb-4 pb-3 border-b border-zinc-800">
          {String(intro).slice(0, 200)}{String(intro).length > 200 ? "…" : ""}
        </p>
      )}

      <div className="space-y-2.5">
        {INFO_FIELDS.map((field) => {
          const val = data[field.key];
          if (val == null || val === "None" || val === "") return null;
          return (
            <div key={field.key} className="flex items-start gap-2">
              <span className="text-[11px] text-zinc-500 w-16 shrink-0 pt-0.5">{field.label}</span>
              <span className="text-xs text-zinc-300 leading-relaxed break-all">
                {formatValue(val, "format" in field ? field.format : undefined)}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
