"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { Header } from "@/components/header";
import { Sidebar, useNav } from "@/components/sidebar";
import { BacktestPanel, type BacktestParams } from "@/components/backtest-panel";
import { KlineChart } from "@/components/kline-chart";
import { EquityChart } from "@/components/equity-chart";
import { StatsCards, TradesTable } from "@/components/results";
import { HomePage as HomePanel } from "@/components/home-page";
import { StockInfoPanel } from "@/components/stock-info-panel";
import { ChartToolbar, aggregateToWeekly, type Granularity, type TimeRange } from "@/components/chart-toolbar";
import { SettingsPage } from "@/components/settings-page";
import { ScreeningPage } from "@/components/screening-page";
import { LiveTradingPage } from "@/components/live-trading-page";
import { PortfolioBacktestPage } from "@/components/portfolio-backtest-page";
import { EtfPage } from "@/components/etf-page";
import type { BacktestRequest, BacktestResponse, StockItem } from "@/lib/types";

function getDateRange(range: TimeRange): { start: string; end: string } {
  const end = new Date();
  const start = new Date();
  switch (range) {
    case "quarter": start.setMonth(end.getMonth() - 3); break;
    case "6m": start.setMonth(end.getMonth() - 6); break;
    case "1y": start.setFullYear(end.getFullYear() - 1); break;
    case "all": return { start: "2000-01-01", end: end.toISOString().slice(0, 10) };
    case "custom": start.setFullYear(end.getFullYear() - 2); break;
  }
  return { start: start.toISOString().slice(0, 10), end: end.toISOString().slice(0, 10) };
}

const INDICATOR_PREFETCH_DAYS = 240;

function getFetchStart(displayStart: string): string {
  const d = new Date(displayStart);
  d.setDate(d.getDate() - INDICATOR_PREFETCH_DAYS);
  return d.toISOString().slice(0, 10);
}

export default function HomePage() {
  const [navActive, setNavActive] = useNav();

  // K线图表 tab 状态（默认上证指数）
  const DEFAULT_INDEX: StockItem = { code: "idx_000001_SH", name: "上证指数", label: "上证指数 (000001.SH)", exchange: "SH" };
  const [chartStock, setChartStock] = useState<StockItem>(DEFAULT_INDEX);
  const [chartGranularity, setChartGranularity] = useState<Granularity>("day");
  const [chartRange, setChartRange] = useState<TimeRange>("6m");
  const [nWaveEnabled, setNWaveEnabled] = useState(true);
  const [customStart, setCustomStart] = useState(() => { const d = new Date(); d.setFullYear(d.getFullYear() - 2); return d.toISOString().slice(0, 10); });
  const [customEnd, setCustomEnd] = useState(() => new Date().toISOString().slice(0, 10));

  // 回测 tab 状态
  const [params, setParams] = useState<BacktestParams | null>(null);
  const [result, setResult] = useState<BacktestResponse | null>(null);

  // 切换股票 / 日期 / 策略 / 资金后清空旧回测结果，避免显示与新参数不匹配的统计、资金曲线和交易标注
  useEffect(() => {
    setResult(null);
  }, [params?.strategy, params?.code, params?.start, params?.end, params?.capital]);

  const { start: chartStart, end: chartEnd } = useMemo(() => {
    if (chartRange === "custom") return { start: customStart, end: customEnd };
    return getDateRange(chartRange);
  }, [chartRange, customStart, customEnd]);

  const today = new Date().toISOString().slice(0, 10);
  const twoYearsAgo = (() => { const d = new Date(); d.setFullYear(d.getFullYear() - 2); return d.toISOString().slice(0, 10); })();

  // K线图表用的 query（多拉前置数据供指标计算）
  const chartFetchStart = useMemo(() => getFetchStart(chartStart), [chartStart]);
  const chartKlineQuery = useQuery({
    queryKey: ["chart-kline", chartStock.code, chartFetchStart, chartEnd],
    queryFn: () => api.kline(chartStock.code, chartFetchStart, chartEnd),
    enabled: navActive === "chart",
  });

  // 回测用的 query（多拉前置数据供指标计算）
  const backtestFetchStart = useMemo(() => params?.start ? getFetchStart(params.start) : "", [params?.start]);
  const backtestKlineQuery = useQuery({
    queryKey: ["kline", params?.code, backtestFetchStart, params?.end],
    queryFn: () => api.kline(params!.code, backtestFetchStart, params!.end),
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
            <div className="grid grid-cols-[1fr_280px] gap-4 h-full">
              {/* 左列：工具栏 + K线 */}
              <div className="flex flex-col gap-4 min-h-0">
                {/* 顶部工具栏 */}
                <ChartToolbar
                  stock={chartStock}
                  bars={chartKlineQuery.data ?? []}
                  granularity={chartGranularity}
                  timeRange={chartRange}
                  customStart={customStart}
                  customEnd={customEnd}
                  nWaveEnabled={nWaveEnabled}
                  onSelectStock={setChartStock}
                  onGranularityChange={setChartGranularity}
                  onTimeRangeChange={setChartRange}
                  onCustomDateChange={(s, e) => { setCustomStart(s); setCustomEnd(e); }}
                  onNWaveToggle={() => setNWaveEnabled((v) => !v)}
                />

                <div className="bg-zinc-900/50 rounded-lg border border-zinc-800 p-4 flex-1 min-h-0 overflow-y-auto">
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
                    <KlineChart bars={chartGranularity === "week" ? aggregateToWeekly(chartKlineQuery.data) : chartKlineQuery.data} nWaveEnabled={nWaveEnabled} visibleFrom={chartStart} />
                  )}
                </div>
              </div>

              {/* 右列：个股信息 */}
              <div className="overflow-y-auto h-full">
                <StockInfoPanel code={chartStock.code} />
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

                {result && <StatsCards stats={result.stats} />}

                {result && result.equity_curve.length > 0 && (
                  <div className="bg-zinc-900/50 rounded-lg border border-zinc-800 p-4">
                    <h3 className="text-sm font-semibold text-zinc-200 mb-3">资金曲线</h3>
                    <EquityChart points={result.equity_curve} />
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
                    <KlineChart bars={backtestKlineQuery.data} trades={result?.trades ?? []} visibleFrom={params?.start} locked />
                  )}
                </div>

                {result && <TradesTable trades={result.trades} />}
              </div>

              {/* 右：个股信息 */}
              <div className="overflow-y-auto h-full">
                <StockInfoPanel code={params?.code ?? ""} />
              </div>
            </div>
          )}

          {/* 选股 */}
          {navActive === "screening" && (
            <ScreeningPage />
          )}

          {/* 实盘 */}
          {navActive === "live" && (
            <LiveTradingPage />
          )}

          {/* 策略回测 */}
          {navActive === "portfolio_backtest" && (
            <PortfolioBacktestPage />
          )}

          {/* ETF 定投计算器 */}
          {navActive === "etf" && (
            <EtfPage />
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
