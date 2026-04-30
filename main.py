"""
主程序入口
支持子命令：data（数据管理）、backtest（回测）、optimize（参数优化）、scan（全市场扫描）
"""
import argparse
import os
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


def cmd_scan(args):
    """全市场扫描筛选 + K线图生成"""
    from scanner.scanner import Scanner
    from visualizer.chart_generator import ChartGenerator
    from config import settings

    # 获取股票列表
    stock_list_file = settings.STOCK_LIST_CACHE
    if not os.path.exists(stock_list_file):
        stock_list_file = settings.STOCK_CODE_FILE

    stock_codes = []
    with open(stock_list_file, "r", encoding="utf-8-sig") as f:
        for line in f:
            code = line.strip()
            if code:
                stock_codes.append(code)

    if not stock_codes:
        print("未找到股票列表，请先运行 data 命令下载数据")
        return

    print("=" * 60)
    print(f"全市场扫描: {args.strategy} | {args.date} | {len(stock_codes)} 只股票")
    print("=" * 60)

    # 扫描
    scanner = Scanner(args.strategy, stock_codes)
    candidates = scanner.scan(args.date)

    if not candidates:
        print("未找到符合条件的候选股票")
        return

    # 保存候选结果
    output_path = scanner.save_candidates(candidates, args.date)
    print(f"筛选完成: {len(candidates)} 只候选股票 -> {output_path}")

    # 生成K线图
    print()
    print("=" * 60)
    print(f"生成K线图: {len(candidates)} 只候选股票")
    print("=" * 60)

    generator = ChartGenerator()
    chart_paths = generator.generate_batch(candidates, args.date)
    print(f"K线图生成完成: {len(chart_paths)} 张")


def cmd_score(args):
    """LLM 两阶段打分"""
    import json
    from llm_scorer.scorer import TwoStageScorer
    from llm_scorer.clients.claude_client import ClaudeClient
    from config import settings

    # 读取候选股票
    date_str = args.date.replace("-", "")
    candidates_file = os.path.join(settings.CANDIDATES_DIR, f"candidates_{date_str}.json")

    if not os.path.exists(candidates_file):
        print(f"候选股票文件不存在: {candidates_file}")
        print("请先运行 scan 命令生成候选股票")
        return

    with open(candidates_file, "r", encoding="utf-8") as f:
        data = json.load(f)
        candidates = data.get("candidates", [])

    if not candidates:
        print("候选股票列表为空")
        return

    # 获取 API Key
    api_key = os.getenv("CLAUDE_API_KEY")
    if not api_key:
        print("错误: 未设置 CLAUDE_API_KEY 环境变量")
        print("请运行: export CLAUDE_API_KEY=your_api_key")
        return

    print("=" * 60)
    print(f"LLM 两阶段打分: {args.date} | {len(candidates)} 只候选")
    print(f"模型: {args.model}")
    print("=" * 60)

    # 初始化客户端
    client = ClaudeClient(api_key=api_key, model=args.model)
    scorer = TwoStageScorer(client)

    # 执行打分
    result = scorer.score(candidates, args.date)

    # 保存结果
    output_path = scorer.save_result(result, args.date)
    print()
    print(f"打分完成: TOP 10 已保存到 {output_path}")

    # 显示 TOP 10
    print()
    print("TOP 10 股票:")
    print("-" * 60)
    for item in result["final_top10"]:
        print(f"  #{item['rank']}: {item['symbol']} - 评分: {item['score']} - {item['recommendation']}")



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

    # scan 子命令
    p_scan = subparsers.add_parser("scan", help="全市场扫描筛选")
    p_scan.add_argument("--strategy", required=True, help="策略名称 (如 b1)")
    p_scan.add_argument("--date", required=True, help="扫描日期 YYYY-MM-DD")

    # score 子命令
    p_score = subparsers.add_parser("score", help="LLM 两阶段打分")
    p_score.add_argument("--date", required=True, help="打分日期 YYYY-MM-DD")
    p_score.add_argument("--model", default="claude-opus-4-20250514", help="LLM 模型名称")

    args = parser.parse_args()

    if args.command == "data":
        cmd_data(args)
    elif args.command == "backtest":
        cmd_backtest(args)
    elif args.command == "optimize":
        cmd_optimize(args)
    elif args.command == "scan":
        cmd_scan(args)
    elif args.command == "score":
        cmd_score(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
