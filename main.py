"""
主程序入口
支持子命令：data（数据管理）、backtest（回测）、optimize（参数优化）、scan（全市场扫描）
"""
import argparse
import os
from datetime import datetime


def cmd_data(args):
    """数据获取 + 导入 vnpy 数据库"""
    from adapter.vnpy_adapter import VnpyAdapter

    # 选择数据源
    if args.source == "akshare":
        from fetcher.akshare_fetcher import AkShareDataFetcher
        fetcher = AkShareDataFetcher()
    else:
        from fetcher.baostock_fetcher import BaoStockDataFetcher
        fetcher = BaoStockDataFetcher()

    print("=" * 60)
    print(f"STEP 1: 下载 K 线数据 [{args.start} ~ {args.end}] (数据源: {args.source})")
    print("=" * 60)
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


def cmd_portfolio(args):
    """组合回测"""
    from portfolio.portfolio_engine import PortfolioEngine
    from portfolio.reporter import PortfolioReporter
    from config import settings

    # 获取股票池
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
        print("未找到股票列表")
        return

    print("=" * 60)
    print(f"组合回测: {args.strategy} | {args.start} ~ {args.end}")
    print(f"股票池: {len(stock_codes)} 只 | 最大持仓: 10 只")
    print("=" * 60)

    engine = PortfolioEngine(
        initial_capital=100000,
        max_positions=10,
        slippage=0.001,
    )
    result = engine.run(args.start, args.end, stock_codes)

    if not result:
        print("回测失败，无结果")
        return

    # 打印摘要
    print()
    reporter = PortfolioReporter(result)
    reporter.summary()

    # 保存结果
    date_range = f"{args.start.replace('-', '')}_{args.end.replace('-', '')}"
    json_path = reporter.save_json(date_range)
    print(f"\n结果已保存到 {json_path}")

    # 生成图表
    chart_path = os.path.join(settings.PORTFOLIO_DIR, f"backtest_{date_range}.png")
    reporter.plot(save_path=chart_path)
    print(f"图表已保存到 {chart_path}")


def cmd_signal(args):
    """生成交易信号"""
    import json
    from scanner.scanner import Scanner
    from config import settings

    date_str = args.date.replace("-", "")

    # 读取 LLM 打分结果（如果有）
    scores_file = os.path.join(settings.SCORES_DIR, f"scores_{date_str}.json")
    candidates_file = os.path.join(settings.CANDIDATES_DIR, f"candidates_{date_str}.json")

    buy_signals = []
    if os.path.exists(scores_file):
        with open(scores_file, "r", encoding="utf-8") as f:
            scores = json.load(f)
            buy_signals = scores.get("final_top10", [])
        print(f"从 LLM 打分结果加载 {len(buy_signals)} 只买入候选")
    elif os.path.exists(candidates_file):
        with open(candidates_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            candidates = data.get("candidates", [])
            buy_signals = candidates[:10]
        print(f"从筛选结果加载 {len(buy_signals)} 只买入候选（未经 LLM 打分）")
    else:
        print(f"未找到 {args.date} 的筛选或打分结果")
        print("请先运行 scan 或 score 命令")
        return

    # 生成买入信号
    os.makedirs(settings.SIGNALS_DIR, exist_ok=True)
    buy_output = {
        "date": args.date,
        "execute_date": "T+1 开盘",
        "signals": buy_signals,
    }
    buy_path = os.path.join(settings.SIGNALS_DIR, f"buy_{date_str}.json")
    with open(buy_path, "w", encoding="utf-8") as f:
        json.dump(buy_output, f, ensure_ascii=False, indent=2)

    print(f"\n买入信号已保存到 {buy_path}")
    print(f"买入候选 ({len(buy_signals)} 只):")
    for s in buy_signals:
        symbol = s.get("symbol", "?")
        score = s.get("score", "-")
        print(f"  {symbol} - 评分: {score}")


def cmd_scheduler(args):
    """调度器管理"""
    from scheduler.scheduler import TradingScheduler

    if args.action == "start":
        scheduler = TradingScheduler(
            strategy=args.strategy,
            source=args.source,
        )
        scheduler.start()
    elif args.action == "stop":
        TradingScheduler.stop()
    elif args.action == "status":
        TradingScheduler.status()
    else:
        print(f"未知操作: {args.action}")


def cmd_names(args):
    """获取股票名称缓存"""
    import json
    from config import settings

    cache_path = os.path.join(settings.DATA_DIR, "stock_names.json")

    # 方法1: akshare
    print("尝试 AkShare 获取 A 股名称...")
    try:
        import akshare as ak
        df = ak.stock_zh_a_spot_em()
        names_map = dict(zip(df["代码"].astype(str), df["名称"]))
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(names_map, f, ensure_ascii=False, indent=2)
        print(f"已缓存 {len(names_map)} 只股票名称 -> {cache_path}")
        return
    except Exception as e:
        print(f"AkShare 失败: {e}")

    # 方法2: curl + 东方财富
    import subprocess
    print("尝试 curl + 东方财富...")
    all_names = {}
    for page in range(1, 13):
        url = (
            f"http://80.push2.eastmoney.com/api/qt/clist/get?"
            f"pn={page}&pz=500&po=1&np=1&fltt=2&invt=2"
            f"&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048"
            f"&fields=f12,f14"
        )
        try:
            result = subprocess.run(
                ["curl", "-s", "--max-time", "15", url],
                capture_output=True, text=True, timeout=20,
            )
            if result.returncode == 0 and result.stdout:
                data = json.loads(result.stdout)
                diff = data.get("data", {}).get("diff", {})
                for item in diff.values():
                    code = item.get("f12", "")
                    name = item.get("f14", "").strip()
                    if code and name:
                        all_names[code] = name
                print(f"  page {page}: +{len(diff)} (total: {len(all_names)})")
        except Exception:
            continue

    if all_names:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(all_names, f, ensure_ascii=False, indent=2)
        print(f"已缓存 {len(all_names)} 只股票名称 -> {cache_path}")
    else:
        print("所有方法均失败，请检查网络后重试")




def main():
    parser = argparse.ArgumentParser(description="A 股量化交易回测系统")
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # data 子命令
    p_data = subparsers.add_parser("data", help="下载数据并导入 vnpy")
    p_data.add_argument("--start", required=True, help="开始日期 YYYY-MM-DD")
    p_data.add_argument("--end", required=True, help="结束日期 YYYY-MM-DD")
    p_data.add_argument("--source", default="akshare", choices=["akshare", "baostock"],
                         help="数据源 (默认 akshare)")

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

    # portfolio 子命令
    p_pf = subparsers.add_parser("portfolio", help="组合回测")
    p_pf.add_argument("--strategy", required=True, help="策略名称 (如 b1)")
    p_pf.add_argument("--start", required=True, help="开始日期 YYYY-MM-DD")
    p_pf.add_argument("--end", required=True, help="结束日期 YYYY-MM-DD")

    # signal 子命令
    p_sig = subparsers.add_parser("signal", help="生成交易信号")
    p_sig.add_argument("--date", required=True, help="信号日期 YYYY-MM-DD")

    # scheduler 子命令
    p_sch = subparsers.add_parser("scheduler", help="调度器管理")
    p_sch.add_argument("action", choices=["start", "stop", "status"], help="操作 (start/stop/status)")
    p_sch.add_argument("--strategy", default="b1", help="策略名称 (默认 b1)")
    p_sch.add_argument("--source", default="akshare", choices=["akshare", "baostock"],
                        help="数据源 (默认 akshare)")

    # names 子命令
    subparsers.add_parser("names", help="获取股票名称缓存（用于 Web 界面显示）")

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
    elif args.command == "portfolio":
        cmd_portfolio(args)
    elif args.command == "signal":
        cmd_signal(args)
    elif args.command == "scheduler":
        cmd_scheduler(args)
    elif args.command == "names":
        cmd_names(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
