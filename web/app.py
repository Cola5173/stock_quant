"""A 股量化回测 Web 界面"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, date

from config import settings
from strategy.b1 import B1Strategy

STRATEGY_MAP = {
    "B1 (KDJ+知行趋势)": B1Strategy,
}


def load_stock_codes():
    """加载股票代码列表"""
    path = settings.STOCK_CODE_FILE
    codes = []
    with open(path, "r", encoding="utf-8-sig") as f:
        for line in f:
            code = line.strip()
            if code:
                pure = code.split(".")[-1] if "." in code else code
                codes.append(pure)
    return codes


def load_kline_data(stock_code: str, start: str, end: str) -> pd.DataFrame:
    """加载 K 线数据"""
    csv_path = os.path.join(settings.DATA_DIR, f"{stock_code}.csv")
    if not os.path.exists(csv_path):
        return pd.DataFrame()
    df = pd.read_csv(csv_path, parse_dates=["date"])
    df = df[(df["date"] >= start) & (df["date"] <= end)]
    return df.sort_values("date").reset_index(drop=True)


def run_backtest(strategy_cls, stock_code: str, start: datetime, end: datetime, capital: float):
    """执行回测"""
    from backtest.engine import BacktestRunner
    vt_symbol = f"{stock_code}.SSE" if stock_code.startswith("6") else f"{stock_code}.SZSE"
    from config.settings import BACKTEST_CONFIG
    cfg = BACKTEST_CONFIG.copy()
    cfg["capital"] = capital

    runner = BacktestRunner(
        strategy_class=strategy_cls,
        vt_symbol=vt_symbol,
        start=start,
        end=end,
        setting={},
    )
    runner.engine.capital = capital
    stats = runner.run()
    daily_df = runner.engine.daily_df
    trades = runner.engine.get_all_trades()
    return stats, daily_df, trades


def build_kline_chart(df: pd.DataFrame, trades: list) -> go.Figure:
    """构建 K 线图 + 买卖点标记"""
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.75, 0.25],
    )

    fig.add_trace(go.Candlestick(
        x=df["date"], open=df["open"], high=df["high"],
        low=df["low"], close=df["close"], name="K线",
        increasing_line_color="#ef4444", decreasing_line_color="#22c55e",
        increasing_fillcolor="#ef4444", decreasing_fillcolor="#22c55e",
    ), row=1, col=1)

    if "volume" in df.columns:
        colors = ["#ef4444" if c >= o else "#22c55e"
                  for c, o in zip(df["close"], df["open"])]
        fig.add_trace(go.Bar(
            x=df["date"], y=df["volume"], name="成交量",
            marker_color=colors, opacity=0.5,
        ), row=2, col=1)
    from vnpy.trader.constant import Direction
    buy_dates, buy_prices = [], []
    sell_dates, sell_prices = [], []
    for trade in trades:
        trade_date = trade.datetime.strftime("%Y-%m-%d") if trade.datetime else None
        if trade_date and trade_date in df["date"].dt.strftime("%Y-%m-%d").values:
            if trade.direction == Direction.LONG:
                buy_dates.append(trade.datetime)
                buy_prices.append(trade.price)
            else:
                sell_dates.append(trade.datetime)
                sell_prices.append(trade.price)

    if buy_dates:
        fig.add_trace(go.Scatter(
            x=buy_dates, y=buy_prices, mode="markers", name="买入",
            marker=dict(symbol="triangle-up", size=12, color="#22c55e"),
        ), row=1, col=1)
    if sell_dates:
        fig.add_trace(go.Scatter(
            x=sell_dates, y=sell_prices, mode="markers", name="卖出",
            marker=dict(symbol="triangle-down", size=12, color="#ef4444"),
        ), row=1, col=1)

    fig.update_layout(
        height=500, xaxis_rangeslider_visible=False,
        template="plotly_dark", showlegend=True,
        margin=dict(l=50, r=20, t=30, b=30),
    )
    fig.update_xaxes(type="category", row=2, col=1)
    fig.update_xaxes(type="category", row=1, col=1)
    return fig


def build_equity_chart(daily_df: pd.DataFrame, capital: float) -> go.Figure:
    """构建资金曲线图"""
    fig = go.Figure()
    if daily_df is not None and "balance" in daily_df.columns:
        fig.add_trace(go.Scatter(
            x=daily_df.index, y=daily_df["balance"],
            mode="lines", name="账户净值",
            line=dict(color="#3b82f6", width=2),
            fill="tozeroy", fillcolor="rgba(59,130,246,0.1)",
        ))
        fig.add_hline(y=capital, line_dash="dash",
                      line_color="#6b7280", annotation_text="初始资金")
    fig.update_layout(
        height=300, template="plotly_dark",
        margin=dict(l=50, r=20, t=30, b=30),
        yaxis_title="资金 (元)",
    )
    return fig
def main():
    st.set_page_config(page_title="A 股量化回测", layout="wide", page_icon="📈")
    st.title("A 股量化回测系统")

    with st.sidebar:
        st.header("回测参数")
        strategy_name = st.selectbox("策略", list(STRATEGY_MAP.keys()))
        stock_codes = load_stock_codes()
        stock_code = st.selectbox("股票代码", stock_codes, index=0)
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input("开始日期", value=date(2024, 1, 1))
        with col2:
            end_date = st.date_input("结束日期", value=date(2025, 6, 30))
        capital = st.number_input("初始资金", value=100000, step=10000, min_value=10000)
        run_btn = st.button("开始回测", type="primary", use_container_width=True)

    if run_btn:
        strategy_cls = STRATEGY_MAP[strategy_name]
        start_dt = datetime.combine(start_date, datetime.min.time())
        end_dt = datetime.combine(end_date, datetime.min.time())

        with st.spinner("回测运行中..."):
            try:
                stats, daily_df, trades = run_backtest(
                    strategy_cls, stock_code, start_dt, end_dt, capital)
            except Exception as e:
                st.error(f"回测失败: {e}")
                return
        if stats:
            m1, m2, m3, m4 = st.columns(4)
            total_return = stats.get("total_return", 0) or 0
            max_dd = stats.get("max_drawdown", 0) or 0
            sharpe = stats.get("sharpe_ratio", 0) or 0
            total_trades = stats.get("total_trade_count", 0) or 0

            m1.metric("总收益率", f"{total_return:.2f}%",
                      delta_color="normal" if total_return >= 0 else "inverse")
            m2.metric("最大回撤", f"{max_dd:.2f}%")
            m3.metric("夏普比率", f"{sharpe:.2f}")
            m4.metric("交易次数", f"{int(total_trades)}")

            kline_df = load_kline_data(stock_code, str(start_date), str(end_date))
            if not kline_df.empty:
                st.subheader("K 线走势")
                fig_kline = build_kline_chart(kline_df, trades)
                st.plotly_chart(fig_kline, use_container_width=True)

            st.subheader("资金曲线")
            fig_equity = build_equity_chart(daily_df, capital)
            st.plotly_chart(fig_equity, use_container_width=True)

            if trades:
                st.subheader("交易明细")
                from vnpy.trader.constant import Direction
                trade_data = []
                for t in trades:
                    trade_data.append({
                        "日期": t.datetime.strftime("%Y-%m-%d") if t.datetime else "",
                        "方向": "买入" if t.direction == Direction.LONG else "卖出",
                        "价格": f"{t.price:.2f}",
                        "数量": int(t.volume),
                    })
                st.dataframe(pd.DataFrame(trade_data), use_container_width=True)
        else:
            st.warning("回测无结果，请检查数据是否已下载")
    else:
        st.info("请在左侧设置参数后点击「开始回测」")


if __name__ == "__main__":
    main()
