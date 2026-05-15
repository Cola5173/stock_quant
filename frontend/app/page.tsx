"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/lib/api";
import { Header } from "@/components/header";
import { Sidebar, useNav } from "@/components/sidebar";
import { BacktestPanel, type BacktestParams } from "@/components/backtest-panel";
import { KlineChart } from "@/components/kline-chart";
import { EquityChart } from "@/components/equity-chart";
import { StatsCards, TradesTable } from "@/components/results";
import { StrategyLibrary } from "@/components/strategy-library";
import { HomePage as HomePanel } from "@/components/home-page";
import { StockInfoPanel } from "@/components/stock-info-panel";
import { StockSearchBar } from "@/components/stock-search-bar";
import { SettingsPage } from "@/components/settings-page";
import type { BacktestRequest, BacktestResponse, StockItem } from "@/lib/types";

export default function HomePage() {
  const [navActive, setNavActive] = useNav();

  // K线图表 tab 状态（默认上证指数）
  const DEFAULT_INDEX: StockItem = { code: "idx_000001_SH", name: "上证指数", label: "上证指数 (000001.SH)", exchange: "SH" };
  const [chartStock, setChartStock] = useState<StockItem>(DEFAULT_INDEX);

  // 回测 tab 状态
  const [params, setParams] = useState<BacktestParams | null>(null);
  const [result, setResult] = useState<BacktestResponse | null>(null);

  const today = new Date().toISOString().slice(0, 10);
  const twoYearsAgo = (() => { const d = new Date(); d.setFullYear(d.getFullYear() - 2); return d.toISOString().slice(0, 10); })();

  // K线图表用的 query
  const chartKlineQuery = useQuery({
    queryKey: ["chart-kline", chartStock.code, twoYearsAgo, today],
    queryFn: () => api.kline(chartStock.code, twoYearsAgo, today),
    enabled: navActive === "chart",
  });

  // 回测用的 query
  const backtestKlineQuery = useQuery({
    queryKey: ["kline", params?.code, params?.start, params?.end],
    queryFn: () => api.kline(params!.code, params!.start, params!.end),
    enabled: navActive === "backtest" && !!params?.code,
  });

  const backtest = useMutation({
    mutationFn: (req: BacktestRequest) => api.backtest(req),
    onSuccess: (data) => setResult(data),
  });

  const subtitle = navActive === "chart" && chartStock
    ? chartStock.name
    : navActive === "backtest" && params?.selectedStock
      ? `${params.selectedStock.code}.${params.selectedStock.exchange} · ${params.selectedStock.name}`
      : undefined;

  return (
    <div className="flex flex-1 min-h-0">
      <Sidebar active={navActive} onChange={setNavActive} />
      <div className="flex-1 flex flex-col min-w-0">
        <Header subtitle={subtitle} />
        <main className="flex-1 overflow-hidden p-6">

          {/* 首页 */}
          {navActive === "home" && (
            <HomePanel onNavigate={setNavActive} />
          )}

          {/* K线图表 */}
          {navActive === "chart" && (
            <div className="flex flex-col gap-4 h-full">
              {/* 顶部搜索栏 */}
              <StockSearchBar onSelect={setChartStock} />

              {/* 内容区：K线 + 个股信息 */}
              <div className="grid grid-cols-[1fr_280px] gap-4 flex-1 min-h-0">
                <div className="bg-zinc-900/50 rounded-lg border border-zinc-800 p-4 overflow-y-auto">
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="text-sm font-semibold text-zinc-200">K 线走势</h3>
                    <span className="text-xs text-zinc-500">{chartStock.label}</span>
                  </div>
                  {chartKlineQuery.isPending && (
                    <div className="h-[400px] flex items-center justify-center text-zinc-500 text-sm">加载中…</div>
                  )}
                  {chartKlineQuery.isError && (
                    <div className="h-[400px] flex items-center justify-center text-zinc-500 text-sm">
                      未能加载数据
                    </div>
                  )}
                  {chartKlineQuery.data && chartKlineQuery.data.length > 0 && (
                    <KlineChart bars={chartKlineQuery.data} />
                  )}
                </div>

                <div className="overflow-y-auto h-full">
                  <StockInfoPanel code={chartStock.code} />
                </div>
              </div>
            </div>
          )}

          {/* 回测 */}
          {navActive === "backtest" && (
            <div className="grid grid-cols-[300px_1fr_280px] gap-4 h-full">
              {/* 左：参数 */}
              <div className="overflow-y-auto">
                <BacktestPanel
                  onSubmit={(req) => { setResult(null); backtest.mutate(req); }}
                  onParamsChange={setParams}
                  isPending={backtest.isPending}
                />
              </div>

              {/* 中：图表 */}
              <div className="flex flex-col gap-4 min-w-0 overflow-y-auto">
                {backtest.isError && (
                  <div className="bg-red-950/50 border border-red-900 rounded-lg p-4 text-red-300 text-sm">
                    回测失败：{(backtest.error as Error).message}
                  </div>
                )}

                <div className="bg-zinc-900/50 rounded-lg border border-zinc-800 p-4">
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="text-sm font-semibold text-zinc-200">K 线走势</h3>
                    {params?.selectedStock && (
                      <span className="text-xs text-zinc-500">{params.selectedStock.label}</span>
                    )}
                  </div>
                  {!params?.code && (
                    <div className="h-[400px] flex items-center justify-center text-zinc-500 text-sm">
                      请在左侧选择股票
                    </div>
                  )}
                  {params?.code && backtestKlineQuery.isPending && (
                    <div className="h-[400px] flex items-center justify-center text-zinc-500 text-sm">加载中…</div>
                  )}
                  {params?.code && backtestKlineQuery.isError && (
                    <div className="h-[400px] flex items-center justify-center text-zinc-500 text-sm">
                      未能加载数据
                    </div>
                  )}
                  {backtestKlineQuery.data && backtestKlineQuery.data.length > 0 && (
                    <KlineChart bars={backtestKlineQuery.data} trades={result?.trades ?? []} />
                  )}
                </div>

                {result && <StatsCards stats={result.stats} />}

                {result && result.equity_curve.length > 0 && (
                  <div className="bg-zinc-900/50 rounded-lg border border-zinc-800 p-4">
                    <h3 className="text-sm font-semibold text-zinc-200 mb-3">资金曲线</h3>
                    <EquityChart points={result.equity_curve} />
                  </div>
                )}

                {result && <TradesTable trades={result.trades} />}
              </div>

              {/* 右：个股信息 */}
              <div className="overflow-y-auto h-full">
                <StockInfoPanel code={params?.code ?? ""} />
              </div>
            </div>
          )}

          {/* 策略库 */}
          {navActive === "library" && (
            <div className="max-w-3xl mx-auto h-full">
              <StrategyLibrary />
            </div>
          )}

          {/* 选股 */}
          {navActive === "screening" && (
            <div className="max-w-2xl mx-auto mt-20 text-center">
              <h2 className="text-2xl font-semibold text-zinc-300">选股</h2>
              <p className="mt-2 text-zinc-500">功能开发中…</p>
            </div>
          )}

          {/* 设置 */}
          {navActive === "settings" && (
            <SettingsPage />
          )}
        </main>
      </div>
    </div>
  );
}
