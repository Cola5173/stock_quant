"""B1 策略全市场回测：成功率 + 收益率统计

用法:
    # 默认近 2 年全市场
    python tests/test_b1_market.py

    # 自定义区间
    python tests/test_b1_market.py --start 2024-01-01 --end 2026-05-17

    # 限制股票数量（快速验证）
    python tests/test_b1_market.py --limit 200

    # 并发数（默认 4）
    python tests/test_b1_market.py --workers 8
"""
import sys
import os
import argparse
import logging
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from glob import glob

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.getLogger().setLevel(logging.WARNING)


def list_all_symbols() -> list:
    """从 data/*.csv 提取全市场代码"""
    from api.config import settings
    files = glob(os.path.join(settings.DATA_DIR, "*.csv"))
    symbols = []
    for f in files:
        name = os.path.basename(f).replace(".csv", "")
        if name.isdigit() and len(name) == 6:
            symbols.append(name)
    return sorted(symbols)


def run_one(args: tuple) -> dict:
    """子进程入口：跑单只回测，返回汇总指标"""
    symbol, start, end, capital = args
    from api.schemas.models import BacktestRequest
    from api.services.backtest_service import run_backtest
    try:
        req = BacktestRequest(
            strategy="b1", code=symbol,
            start=date.fromisoformat(start), end=date.fromisoformat(end),
            capital=capital,
        )
        resp = run_backtest(req)
        wins = 0
        losses = 0
        # 按笔配对计算胜率（1 buy + N sells 算一笔）
        cur_buy = None
        cur_sells = []
        for t in resp.trades:
            if t.direction == "buy":
                if cur_buy is not None:
                    cost = cur_buy.price * cur_buy.volume
                    rev = sum(s.price * s.volume for s in cur_sells)
                    if cur_sells and rev > cost:
                        wins += 1
                    elif cur_sells:
                        losses += 1
                cur_buy = t
                cur_sells = []
            else:
                cur_sells.append(t)
        if cur_buy is not None and cur_sells:
            cost = cur_buy.price * cur_buy.volume
            rev = sum(s.price * s.volume for s in cur_sells)
            if rev > cost:
                wins += 1
            else:
                losses += 1

        return {
            "symbol": symbol,
            "trades": resp.stats.total_trade_count,
            "return": resp.stats.total_return,
            "max_dd": resp.stats.max_drawdown,
            "sharpe": resp.stats.sharpe_ratio,
            "wins": wins,
            "losses": losses,
            "ok": True,
        }
    except Exception as e:
        return {"symbol": symbol, "ok": False, "error": str(e)}


def aggregate(results: list, capital: float) -> None:
    valid = [r for r in results if r["ok"]]
    failed = [r for r in results if not r["ok"]]
    print()
    print("=" * 90)
    print(f"全市场 B1 回测汇总")
    print("=" * 90)
    print(f"扫描股票: {len(results)} | 成功: {len(valid)} | 失败/跳过: {len(failed)}")
    if not valid:
        return

    traded = [r for r in valid if r["trades"] > 0]
    print(f"产生交易的股票: {len(traded)} ({len(traded)/len(valid)*100:.1f}%)")
    print(f"未触发买入信号: {len(valid) - len(traded)}")

    if not traded:
        return

    # 按股票统计
    profitable_stocks = [r for r in traded if r["return"] > 0]
    print(f"\n按股票（产生交易的）:")
    print(f"  盈利股票: {len(profitable_stocks)} / {len(traded)} = {len(profitable_stocks)/len(traded)*100:.1f}%")
    avg_ret = sum(r["return"] for r in traded) / len(traded)
    median_ret = sorted([r["return"] for r in traded])[len(traded) // 2]
    print(f"  平均收益: {avg_ret:+.2f}% | 中位数: {median_ret:+.2f}%")
    avg_dd = sum(r["max_dd"] for r in traded) / len(traded)
    print(f"  平均最大回撤: {avg_dd:.2f}%")

    # 按笔统计
    total_wins = sum(r["wins"] for r in valid)
    total_losses = sum(r["losses"] for r in valid)
    total_pairs = total_wins + total_losses
    if total_pairs > 0:
        print(f"\n按交易笔数（已平仓）:")
        print(f"  总笔数: {total_pairs} | 盈利笔: {total_wins} ({total_wins/total_pairs*100:.1f}%) | 亏损笔: {total_losses}")

    # 全市场加权（每只票等权 capital）
    total_pnl = sum(r["return"] * capital / 100 for r in valid)
    aggregate_capital = capital * len(valid)
    print(f"\n等权组合（每票 {capital:,.0f}，共 {aggregate_capital:,.0f}）:")
    print(f"  总盈亏: {total_pnl:+,.0f}")
    print(f"  组合收益率: {total_pnl / aggregate_capital * 100:+.2f}%")

    # Top / Bottom 10
    sorted_by_ret = sorted(traded, key=lambda x: -x["return"])
    print(f"\nTop 10 盈利:")
    for r in sorted_by_ret[:10]:
        print(f"  {r['symbol']}  +{r['return']:6.2f}%  trades={r['trades']}  dd={r['max_dd']:.1f}%")
    print(f"\nBottom 10 亏损:")
    for r in sorted_by_ret[-10:]:
        print(f"  {r['symbol']}  {r['return']:+7.2f}%  trades={r['trades']}  dd={r['max_dd']:.1f}%")


def parse_args():
    today = date.today()
    two_years_ago = (today - timedelta(days=730)).isoformat()
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default=two_years_ago, help="回测起始日 YYYY-MM-DD")
    parser.add_argument("--end", default=today.isoformat(), help="回测结束日 YYYY-MM-DD")
    parser.add_argument("--capital", type=float, default=100000)
    parser.add_argument("--limit", type=int, default=0, help="限制股票数量（0=全部）")
    parser.add_argument("--workers", type=int, default=4)
    return parser.parse_args()


def main():
    args = parse_args()
    symbols = list_all_symbols()
    if args.limit > 0:
        symbols = symbols[:args.limit]
    print(f"区间: {args.start} ~ {args.end} | 资金/股: {args.capital:,.0f} | "
          f"股票数: {len(symbols)} | 并发: {args.workers}")

    tasks = [(s, args.start, args.end, args.capital) for s in symbols]
    results = []
    t0 = datetime.now()

    with ProcessPoolExecutor(max_workers=args.workers) as exe:
        futures = {exe.submit(run_one, t): t[0] for t in tasks}
        done = 0
        for fut in as_completed(futures):
            results.append(fut.result())
            done += 1
            if done % 50 == 0 or done == len(tasks):
                elapsed = (datetime.now() - t0).total_seconds()
                rate = done / elapsed if elapsed > 0 else 0
                eta = (len(tasks) - done) / rate if rate > 0 else 0
                print(f"  进度 {done}/{len(tasks)}  {rate:.1f}/s  ETA {eta:.0f}s", flush=True)

    aggregate(results, args.capital)


if __name__ == "__main__":
    main()
