export interface StockItem {
  code: string;
  name: string;
  label: string;
  exchange: string;
}

export interface KlineBar {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface StrategyItem {
  key: string;
  name: string;
  description?: string;
}

export interface BacktestRequest {
  strategy: string;
  code: string;
  start: string; // YYYY-MM-DD
  end: string;
  capital: number;
}

export interface TradeRecord {
  date: string;
  direction: "buy" | "sell";
  price: number;
  volume: number;
  reason?: string;
}

export interface EquityPoint {
  date: string;
  balance: number;
}

export interface BacktestStats {
  total_return: number;
  max_drawdown: number;
  sharpe_ratio: number;
  total_trade_count: number;
}

export interface BacktestResponse {
  stats: BacktestStats;
  trades: TradeRecord[];
  equity_curve: EquityPoint[];
}

export interface HomeStats {
  stock_count: number;
  strategy_count: number;
  data_source_count: number;
}

export interface FetchStatus {
  running: boolean;
  source?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  error?: string | null;
}

export interface FetchTriggerResponse {
  started: boolean;
  message: string;
}

export interface SelectedStrategy {
  key: string;
  name: string;
}

export interface SelectedRecord {
  date: string;
  count: number;
}

export interface SelectedCandidate {
  symbol: string;
  name: string;
  match_date: string;
  close: number;
  industry?: string;
  score?: number;
  indicators: {
    kdj_j: number;
    kdj_k: number;
    kdj_d: number;
    zx_white: number;
    zx_yellow: number;
    amplitude: number;
  };
}

export interface SelectedDetail {
  scan_date: string;
  strategy: string;
  candidates_count: number;
  candidates: SelectedCandidate[];
}
