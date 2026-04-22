"""
主程序入口
支持子命令：data（数据管理）、backtest（回测）、optimize（参数优化）
"""
import argparse
from datetime import datetime


def cmd_data(args):
    """数据获取 + 导入 vnpy 数据库"""
    from fetcher.baostock_fetcher import BaoStockDataFetcher
    from adapter.vnpy_adapter import VnpyAdapter

    print("=" * 60)
    print(f"STEP 1: 下载 K 线数据 [{args.start} ~ {args.end}]")
    print("=" * 60)
    fetcher = BaoStockDataFetcher()
    fetcher.fetch(args.start, args.end)

    print()
    print("=" * 60)
    print("STEP 2: 导入数据到 vnpy 数据库")
    print("=" * 60)
    adapter = VnpyAdapter()
    results = adapter.import_all_stocks(args.start, args.end)
    print(f"导入完成: 成功 {results['success']}, 失败 {results['failed']}, 共 {results['total_bars']} 条")


def cmd_backtest(args):
    """单股回测"""
    from backtest.engine import BacktestRunner
    from backtest.reporter import BacktestReporter
    from strategy.b1 import B1Strategy

    strategy_map = {
        "b1": B1Strategy,
    }

    strategy_cls = strategy_map.get(args.strategy)
    if not strategy_cls:
        print(f"未知策略: {args.strategy}，可用: {list(strategy_map.keys())}")
        return

    symbol = args.symbol
    if symbol.startswith("6"):
        vt_symbol = f"{symbol}.SSE"
    else:
        vt_symbol = f"{symbol}.SZSE"

    start = datetime.strptime(args.start, "%Y-%m-%d")
    end = datetime.strptime(args.end, "%Y-%m-%d")

    print("=" * 60)
    print(f"回测: {args.strategy} | {vt_symbol} | {args.start} ~ {args.end}")
    print("=" * 60)

    runner = BacktestRunner(
        strategy_class=strategy_cls,
        vt_symbol=vt_symbol,
        start=start,
        end=end,
    )
    stats = runner.run()

    print()
    reporter = BacktestReporter(runner.engine)
    reporter.summary()

    save_path = f"reports/{args.strategy}_{symbol}.png"
    reporter.plot(save_path=save_path)


def cmd_optimize(args):
    """参数优化"""
    from vnpy_ctastrategy.backtesting import OptimizationSetting
    from backtest.engine import BacktestRunner
    from strategy.b1 import B1Strategy

    strategy_map = {
        "b1": B1Strategy,
    }

    strategy_cls = strategy_map.get(args.strategy)
    if not strategy_cls:
        print(f"未知策略: {args.strategy}，可用: {list(strategy_map.keys())}")
        return

    symbol = args.symbol
    if symbol.startswith("6"):
        vt_symbol = f"{symbol}.SSE"
    else:
        vt_symbol = f"{symbol}.SZSE"

    start = datetime.strptime(args.start, "%Y-%m-%d")
    end = datetime.strptime(args.end, "%Y-%m-%d")

    print("=" * 60)
    print(f"参数优化: {args.strategy} | {vt_symbol} | {args.start} ~ {args.end}")
    print("=" * 60)

    runner = BacktestRunner(
        strategy_class=strategy_cls,
        vt_symbol=vt_symbol,
        start=start,
        end=end,
    )

    opt_setting = OptimizationSetting()
    opt_setting.set_target("sharpe_ratio")
    opt_setting.add_parameter("kdj_j_buy", 5, 20, 5)
    opt_setting.add_parameter("kdj_j_sell", 70, 90, 5)

    results = runner.optimize(opt_setting)

    print()
    print("优化结果 (按夏普比率排序):")
    print("-" * 60)
    for i, (params, target, stats) in enumerate(results[:10]):
        print(f"  #{i+1}: {params} -> 夏普比率: {target:.4f}")


def main():
    parser = argparse.ArgumentParser(description="A 股量化交易回测系统")
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # data 子命令
    p_data = subparsers.add_parser("data", help="下载数据并导入 vnpy")
    p_data.add_argument("--start", required=True, help="开始日期 YYYY-MM-DD")
    p_data.add_argument("--end", required=True, help="结束日期 YYYY-MM-DD")

    # backtest 子命令
    p_bt = subparsers.add_parser("backtest", help="单股回测")
    p_bt.add_argument("--strategy", required=True, help="策略名称 (如 b1)")
    p_bt.add_argument("--symbol", required=True, help="股票代码 (如 600000)")
    p_bt.add_argument("--start", required=True, help="开始日期 YYYY-MM-DD")
    p_bt.add_argument("--end", required=True, help="结束日期 YYYY-MM-DD")

    # optimize 子命令
    p_opt = subparsers.add_parser("optimize", help="参数优化")
    p_opt.add_argument("--strategy", required=True, help="策略名称 (如 b1)")
    p_opt.add_argument("--symbol", required=True, help="股票代码 (如 600000)")
    p_opt.add_argument("--start", required=True, help="开始日期 YYYY-MM-DD")
    p_opt.add_argument("--end", required=True, help="结束日期 YYYY-MM-DD")

    args = parser.parse_args()

    if args.command == "data":
        cmd_data(args)
    elif args.command == "backtest":
        cmd_backtest(args)
    elif args.command == "optimize":
        cmd_optimize(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
