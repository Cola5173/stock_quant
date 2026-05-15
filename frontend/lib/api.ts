import type {
  StockItem, KlineBar, StrategyItem,
  BacktestRequest, BacktestResponse, HomeStats,
  FetchStatus, FetchTriggerResponse,
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
};
