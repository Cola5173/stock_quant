import type {
  StockItem, KlineBar, StrategyItem,
  BacktestRequest, BacktestResponse, HomeStats,
  FetchStatus, FetchTriggerResponse,
  SelectedStrategy, SelectedRecord, SelectedDetail,
} from "./types";
import { API_BASE } from "./config";

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(detail.detail || `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => http<{ status: string }>("/api/health"),
  stats: () => http<HomeStats>("/api/stats"),
  stocks: () => http<StockItem[]>("/api/stocks"),
  kline: (code: string, start: string, end: string) =>
    http<KlineBar[]>(`/api/stocks/${code}/kline?start=${start}&end=${end}`),
  stockInfo: (code: string) =>
    http<Record<string, string | number | null>>(`/api/stocks/${code}/info`),
  strategies: () => http<StrategyItem[]>("/api/strategies"),
  backtest: (req: BacktestRequest) =>
    http<BacktestResponse>("/api/backtest", {
      method: "POST",
      body: JSON.stringify(req),
    }),
  fetchLatest: (source = "akshare") =>
    http<FetchTriggerResponse>(`/api/fetch/latest?source=${source}`, { method: "POST" }),
  fetchStatus: () => http<FetchStatus>("/api/fetch/status"),
  selectedStrategies: () => http<SelectedStrategy[]>("/api/selected/strategies"),
  selectedRecords: (strategy: string) =>
    http<SelectedRecord[]>(`/api/selected/${strategy}/records`),
  selectedDetail: (strategy: string, date: string) =>
    http<SelectedDetail>(`/api/selected/${strategy}/${date}`),
  runScan: (strategy: string, date?: string) =>
    http<{ status: string; date: string; strategy: string; candidates_count: number }>(
      `/api/selected/${strategy}/run${date ? `?date=${date}` : ""}`,
      { method: "POST" }
    ),
  advisorLatest: () =>
    http<{ positions: Record<string, unknown>; decision: Record<string, unknown> | null }>("/api/advisor/latest"),
  updatePositions: (data: Record<string, unknown>) =>
    http<{ status: string }>("/api/advisor/positions", {
      method: "PUT",
      body: JSON.stringify(data),
    }),
  runDecision: (date?: string) =>
    http<Record<string, unknown>>(`/api/advisor/run-decision${date ? `?date=${date}` : ""}`, {
      method: "POST",
    }),
  // 策略回测
  portfolioStrategies: () =>
    http<Array<{ key: string; label: string; description: string[] }>>("/api/portfolio-backtest/strategies"),
  portfolioRuns: () =>
    http<Array<Record<string, unknown>>>("/api/portfolio-backtest/runs"),
  portfolioRunDetail: (id: string) =>
    http<Record<string, unknown>>(`/api/portfolio-backtest/runs/${encodeURIComponent(id)}`),
  portfolioRunStart: (req: { strategy: string; start: string; end: string; capital: number }) =>
    http<{ status: string; out_path: string }>("/api/portfolio-backtest/run", {
      method: "POST",
      body: JSON.stringify(req),
    }),
  portfolioRunning: () =>
    http<Array<{ strategy_key: string; start: string; end: string }>>("/api/portfolio-backtest/running"),
};
