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
