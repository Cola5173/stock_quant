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

  return (
    <div className="flex flex-1 min-h-0">
      <Sidebar active={navActive} onChange={setNavActive} />
      <div className="flex-1 flex flex-col min-w-0">
        <Header />
        <main className="flex-1 overflow-auto p-6">
          {navActive === "backtest" ? (
            <div className="grid grid-cols-[320px_1fr] gap-6 max-w-[1600px] mx-auto">
              <div className="space-y-4">
                <BacktestPanel
                  onSubmit={(req) => { setResult(null); backtest.mutate(req); }}
                  onParamsChange={setParams}
                  isPending={backtest.isPending}
                />
              </div>

              <div className="space-y-6 min-w-0">
                {result && <StatsCards stats={result.stats} />}

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
                    <div className="h-96 flex items-center justify-center text-zinc-500 text-sm">
                      请在左侧选择股票
                    </div>
                  )}
                  {params?.code && klineQuery.isPending && (
                    <div className="h-96 flex items-center justify-center text-zinc-500 text-sm">加载中…</div>
                  )}
                  {params?.code && klineQuery.isError && (
                    <div className="h-96 flex items-center justify-center text-zinc-500 text-sm">
                      未找到本地数据，请先用后端拉取
                    </div>
                  )}
                  {klineQuery.data && klineQuery.data.length > 0 && (
                    <KlineChart bars={klineQuery.data} trades={result?.trades ?? []} />
                  )}
                </div>

                {result && result.equity_curve.length > 0 && (
                  <div className="bg-zinc-900/50 rounded-lg border border-zinc-800 p-4">
                    <h3 className="text-sm font-semibold text-zinc-200 mb-3">资金曲线</h3>
                    <EquityChart points={result.equity_curve} />
                  </div>
                )}

                {result && <TradesTable trades={result.trades} />}
              </div>
            </div>
          ) : (
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
