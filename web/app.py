"""A 股量化回测 Web 界面"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, date, timedelta
from dateutil.relativedelta import relativedelta

from config import settings
from strategy.b1 import B1Strategy

STRATEGY_MAP = {
    "B1 (KDJ+知行趋势)": B1Strategy,
}

STOCK_NAMES_CSV = settings.STOCK_NAMES_FILE


def _fetch_latest_kline(source: str):
    """拉取最新 K 线数据到 data/ 目录（从本地最新日期到今天）"""
    from datetime import datetime

    today_str = datetime.now().strftime("%Y-%m-%d")

    with st.spinner(f"正在通过 {source} 拉取最新 K 线数据..."):
        try:
            if source == "akshare":
                from fetcher.akshare_fetcher import AkShareDataFetcher
                fetcher = AkShareDataFetcher()
            elif source == "tushare":
                from fetcher.tushare_fetcher import TushareDataFetcher
                fetcher = TushareDataFetcher()
            else:
                from fetcher.baostock_fetcher import BaoStockDataFetcher
                fetcher = BaoStockDataFetcher()

            fetcher.fetch(start_date=today_str, end_date=today_str)
            st.success(f"K 线数据已更新至 {today_str}")
        except Exception as e:
            st.error(f"拉取失败: {e}")
            import traceback
            st.code(traceback.format_exc())


@st.cache_data
def load_stock_list():
    """从 data/stock_names.csv 加载股票列表（symbol,name）"""
    if not os.path.exists(STOCK_NAMES_CSV):
        return []

    df = pd.read_csv(STOCK_NAMES_CSV, dtype=str, encoding="utf-8-sig")
    items = []
    for _, row in df.iterrows():
        code = str(row["symbol"]).strip()
        name = str(row.get("name", "")).strip()
        exchange = "SH" if code.startswith("6") else "SZ"
        label = f"{name} ({code}.{exchange})" if name else f"{code}.{exchange}"
        items.append({"code": code, "label": label})
    return items


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

    date_str = df["date"].dt.strftime("%Y-%m-%d")

    fig.add_trace(go.Candlestick(
        x=date_str, open=df["open"], high=df["high"],
        low=df["low"], close=df["close"], name="K线",
        increasing_line_color="#ef4444", decreasing_line_color="#22c55e",
        increasing_fillcolor="#ef4444", decreasing_fillcolor="#22c55e",
    ), row=1, col=1)

    if "volume" in df.columns:
        colors = ["#ef4444" if c >= o else "#22c55e"
                  for c, o in zip(df["close"], df["open"])]
        fig.add_trace(go.Bar(
            x=date_str, y=df["volume"], name="成交量",
            marker_color=colors, opacity=0.5,
        ), row=2, col=1)
    from vnpy.trader.constant import Direction
    buy_dates, buy_prices = [], []
    sell_dates, sell_prices = [], []
    for trade in trades:
        trade_date = trade.datetime.strftime("%Y-%m-%d") if trade.datetime else None
        if trade_date and trade_date in date_str.values:
            if trade.direction == Direction.LONG:
                buy_dates.append(trade_date)
                buy_prices.append(trade.price)
            else:
                sell_dates.append(trade_date)
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
    fig.update_xaxes(type="category", row=2, col=1, showticklabels=False)
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
    st.title("Cola 回测系统")

    with st.sidebar:
        st.markdown("**数据管理**")
        data_source = st.selectbox("数据源", ["tushare", "akshare", "baostock"], key="data_source")
        if st.button("拉取最新K线数据", use_container_width=True):
            _fetch_latest_kline(data_source)

        st.header("回测参数")
        strategy_name = st.selectbox("策略", list(STRATEGY_MAP.keys()))

        stock_list = load_stock_list()
        if not stock_list:
            st.warning("股票列表为空，请先点击「拉取最新K线数据」或确认 data/stock_names.csv 存在")
            return
        labels = [item["label"] for item in stock_list]
        selected_label = st.selectbox("股票", labels, index=0)
        stock_code = stock_list[labels.index(selected_label)]["code"]

        st.markdown("**回测区间**")
        today = date.today()
        period = st.radio(
            "快捷选择", ["近1年", "近2年", "近3年", "自定义"],
            horizontal=True, label_visibility="collapsed",
        )
        if period == "近1年":
            start_date = today - relativedelta(years=1)
            end_date = today
        elif period == "近2年":
            start_date = today - relativedelta(years=2)
            end_date = today
        elif period == "近3年":
            start_date = today - relativedelta(years=3)
            end_date = today
        else:
            col1, col2 = st.columns(2)
            with col1:
                start_date = st.date_input("开始", value=date(2024, 1, 1))
            with col2:
                end_date = st.date_input("结束", value=today)

        capital_w = st.number_input("初始资金 (万)", value=10, step=1, min_value=1)
        capital = capital_w * 10000
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
                import traceback
                st.code(traceback.format_exc())
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
        kline_df = load_kline_data(stock_code, str(start_date), str(end_date))
        if not kline_df.empty:
            st.subheader(f"K 线走势 — {selected_label}")
            fig_kline = build_kline_chart(kline_df, [])
            st.plotly_chart(fig_kline, use_container_width=True)
        else:
            st.warning(f"未找到 {stock_code} 的本地数据，请先点击「拉取最新K线数据」")


if __name__ == "__main__":
    main()
