"""
每日任务定义
串联数据拉取 → 筛选 → K线图 → LLM打分 → 信号生成的完整流程
"""
import json
import logging
import os
from datetime import datetime

from api.config import settings

logger = logging.getLogger(__name__)


def is_trading_day(date_str: str) -> bool:
    """
    判断是否为交易日（排除周末和法定节假日）
    :param date_str: YYYY-MM-DD
    """
    try:
        import chinese_calendar as calendar
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        return calendar.is_workday(date_obj)
    except ImportError:
        # chinese_calendar 未安装时，仅排除周末
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        return date_obj.weekday() < 5


def daily_job(strategy: str = "b1", source: str = "akshare"):
    """
    每日任务：收盘后执行完整流程
    :param strategy: 策略名称
    :param source: 数据源
    """
    today = datetime.now().strftime("%Y-%m-%d")

    if not is_trading_day(today):
        logger.info(f"非交易日，跳过: {today}")
        return

    logger.info(f"========== 开始每日任务: {today} ==========")

    try:
        # Step 1: 拉取数据
        logger.info("Step 1: 拉取最新数据...")
        _step_fetch_data(today, source)

        # Step 2: 全市场扫描筛选
        logger.info("Step 2: 全市场扫描筛选...")
        candidates = _step_scan(today, strategy)
        if not candidates:
            logger.warning("未找到候选股票，流程终止")
            return

        # Step 3: 生成K线图
        logger.info("Step 3: 生成K线图...")
        _step_generate_charts(candidates, today)

        # Step 4: LLM 打分
        logger.info("Step 4: LLM 两阶段打分...")
        _step_llm_score(candidates, today)

        # Step 5: 生成交易信号
        logger.info("Step 5: 生成交易信号...")
        _step_generate_signals(today)

        # Step 6: 决策
        logger.info("Step 6: 生成决策...")
        decision = _step_decide(today)

        # Step 7: 邮件通知
        logger.info("Step 7: 发送邮件通知...")
        _step_notify(decision)

        logger.info(f"========== 每日任务完成: {today} ==========")

    except Exception as e:
        logger.error(f"每日任务失败: {e}", exc_info=True)
        _try_send_error_mail("daily_job", e)


def _step_fetch_data(date: str, source: str):
    """拉取最新数据"""
    if source == "akshare":
        from api.fetcher.akshare_fetcher import AkShareDataFetcher
        fetcher = AkShareDataFetcher()
    elif source == "tushare":
        from api.fetcher.tushare_fetcher import TushareDataFetcher
        fetcher = TushareDataFetcher()
    else:
        logger.warning(
            "⚠️ BaoStock 已弃用（服务器长期不稳定），调度器强烈建议使用 akshare"
        )
        from api.fetcher.baostock_fetcher import BaoStockDataFetcher
        fetcher = BaoStockDataFetcher()

    fetcher.fetch(start_date=date, end_date=date)
    logger.info("数据拉取完成")


def _step_scan(date: str, strategy: str) -> list:
    """全市场扫描"""
    from api.scanner.scanner import Scanner

    # 读取股票列表
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
        logger.error("未找到股票列表")
        return []

    scanner = Scanner(strategy, stock_codes)
    candidates = scanner.scan(date)
    scanner.save_candidates(candidates, date)

    logger.info(f"扫描完成: {len(candidates)} 只候选股票")
    return candidates


def _step_generate_charts(candidates: list, date: str):
    """生成K线图"""
    from api.visualizer.chart_generator import ChartGenerator

    generator = ChartGenerator()
    chart_paths = generator.generate_batch(candidates, date)
    logger.info(f"K线图生成完成: {len(chart_paths)} 张")


def _step_llm_score(candidates: list, date: str):
    """LLM 两阶段打分"""
    api_key = os.getenv("CLAUDE_API_KEY")
    if not api_key:
        logger.warning("未设置 CLAUDE_API_KEY，跳过 LLM 打分")
        return

    from api.llm_scorer.scorer import TwoStageScorer
    from api.llm_scorer.clients.claude_client import ClaudeClient

    client = ClaudeClient(api_key=api_key)
    scorer = TwoStageScorer(client)
    result = scorer.score(candidates, date)
    scorer.save_result(result, date)

    logger.info(f"LLM 打分完成: TOP 10 = {[r['symbol'] for r in result['final_top10']]}")


def _step_generate_signals(date: str):
    """生成交易信号"""
    date_str = date.replace("-", "")

    # 优先使用 LLM 打分结果
    scores_file = os.path.join(settings.SCORES_DIR, f"scores_{date_str}.json")
    candidates_file = os.path.join(settings.CANDIDATES_DIR, f"candidates_{date_str}.json")

    buy_signals = []
    if os.path.exists(scores_file):
        with open(scores_file, "r", encoding="utf-8") as f:
            scores = json.load(f)
            buy_signals = scores.get("final_top10", [])
    elif os.path.exists(candidates_file):
        with open(candidates_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            buy_signals = data.get("candidates", [])[:10]

    # 保存买入信号
    os.makedirs(settings.SIGNALS_DIR, exist_ok=True)
    buy_output = {
        "date": date,
        "execute_date": "T+1 开盘",
        "signals": buy_signals,
    }
    buy_path = os.path.join(settings.SIGNALS_DIR, f"buy_{date_str}.json")
    with open(buy_path, "w", encoding="utf-8") as f:
        json.dump(buy_output, f, ensure_ascii=False, indent=2)

    logger.info(f"交易信号已生成: {len(buy_signals)} 只买入候选 -> {buy_path}")


def _step_decide(date: str):
    """Step 6: 生成决策"""
    from api.advisor.decision_engine import run_decision
    from api.utils.retry import retry_call
    return retry_call(
        lambda: run_decision(date),
        times=settings.ADVISOR_CONFIG["retry_times"],
        interval=settings.ADVISOR_CONFIG["retry_interval_sec"],
    )


def _step_notify(decision):
    """Step 7: 发送邮件通知"""
    from api.notifier.email_sender import send_email
    from api.notifier.templates import render_html, render_plain_text, render_subject
    subject = render_subject(decision)
    html = render_html(decision)
    plain = render_plain_text(decision)
    send_email(subject=subject, html_body=html, plain_body=plain)


def _try_send_error_mail(step: str, exc: Exception):
    """尝试发送错误邮件，失败只 log"""
    import traceback
    try:
        from api.notifier.email_sender import send_error_email
        tb = traceback.format_exc()
        send_error_email(step=step, error_msg=tb[-3000:])
    except Exception as e2:
        logger.error(f"错误邮件发送失败: {e2}")
