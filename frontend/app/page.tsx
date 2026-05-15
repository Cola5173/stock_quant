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
import type { BacktestRequest, BacktestResponse } from "@/lib/types";

export default function HomePage() {
  const [navActive, setNavActive] = useNav();
  const [params, setParams] = useState<BacktestParams | null>(null);
  const [result, setResult] = useState<BacktestResponse | null>(null);

  const klineQuery = useQuery({
    queryKey: ["kline", params?.code, params?.start, params?.end],
    queryFn: () => api.kline(params!.code, params!.start, params!.end),
    enabled: !!params?.code,
  });

  const backtest = useMutation({
    mutationFn: (req: BacktestRequest) => api.backtest(req),
    onSuccess: (data) => setResult(data),
  });

  const subtitle = navActive === "backtest" && params?.selectedStock
    ? `${params.selectedStock.code}.${params.selectedStock.exchange} · ${params.selectedStock.name}`
    : undefined;
  const dateRange = navActive === "backtest" && params
    ? `${params.start} ~ ${params.end}`
    : undefined;

  return (
    <div className="flex flex-1 min-h-0">
      <Sidebar active={navActive} onChange={setNavActive} />
      <div className="flex-1 flex flex-col min-w-0">
        <Header subtitle={subtitle} dateRange={dateRange} />
        <main className="flex-1 overflow-hidden p-6">
          {navActive === "home" && (
            <HomePanel onNavigate={setNavActive} />
          )}

          {navActive === "backtest" && (
            <div className="grid grid-cols-[300px_1fr] gap-4 h-full max-w-[1600px]">
              {/* 左：参数 */}
              <div className="overflow-y-auto pr-1">
                <BacktestPanel
                  onSubmit={(req) => { setResult(null); backtest.mutate(req); }}
                  onParamsChange={setParams}
                  isPending={backtest.isPending}
                />
              </div>

              {/* 右：图表 */}
              <div className="flex flex-col gap-4 min-w-0 overflow-y-auto pr-1">
                {backtest.isError && (
                  <div className="bg-red-950/50 border border-red-900 rounded-lg p-4 text-red-300 text-sm">
                    回测失败：{(backtest.error as Error).message}
                  </div>
                )}

                {/* K 线始终在最上方 */}
                <div className="bg-zinc-900/50 rounded-lg border border-zinc-800 p-4 flex flex-col flex-1 min-h-[420px]">
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="text-sm font-semibold text-zinc-200">K 线走势</h3>
                    {params?.selectedStock && (
                      <span className="text-xs text-zinc-500">{params.selectedStock.label}</span>
                    )}
                  </div>
                  <div className="flex-1 flex flex-col">
                    {!params?.code && (
                      <div className="flex-1 flex items-center justify-center text-zinc-500 text-sm">
                        请在左侧选择股票
                      </div>
                    )}
                    {params?.code && klineQuery.isPending && (
                      <div className="flex-1 flex items-center justify-center text-zinc-500 text-sm">加载中…</div>
                    )}
                    {params?.code && klineQuery.isError && (
                      <div className="flex-1 flex items-center justify-center text-zinc-500 text-sm text-center px-4">
                        未能从后端拉到数据
                        <br />
                        <span className="text-xs text-zinc-600 mt-1 block">
                          {(klineQuery.error as Error)?.message}
                        </span>
                      </div>
                    )}
                    {klineQuery.data && klineQuery.data.length > 0 && (
                      <KlineChart bars={klineQuery.data} trades={result?.trades ?? []} />
                    )}
                  </div>
                </div>

                {/* 回测结果：仅点击开始回测后显示 */}
                {result && <StatsCards stats={result.stats} />}

                {result && result.equity_curve.length > 0 && (
                  <div className="bg-zinc-900/50 rounded-lg border border-zinc-800 p-4">
                    <h3 className="text-sm font-semibold text-zinc-200 mb-3">资金曲线</h3>
                    <EquityChart points={result.equity_curve} />
                  </div>
                )}

                {result && <TradesTable trades={result.trades} />}
              </div>
            </div>
          )}

          {navActive === "library" && (
            <div className="max-w-3xl mx-auto h-full">
              <StrategyLibrary />
            </div>
          )}

          {navActive === "screening" && (
            <div className="max-w-2xl mx-auto mt-20 text-center">
              <h2 className="text-2xl font-semibold text-zinc-300">选股</h2>
              <p className="mt-2 text-zinc-500">功能开发中…</p>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
