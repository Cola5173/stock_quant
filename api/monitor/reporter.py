"""核心仓监控报告生成 + 邮件通知"""
import logging
from datetime import datetime
from typing import List

from .balance_checker import DeviationItem, check_balance, load_config
from .valuation import (
    ValuationInfo,
    get_csi300_valuation,
    get_nasdaq_valuation,
)
from api.notifier.email_sender import send_email

logger = logging.getLogger(__name__)


def generate_report(
    deviations: List[DeviationItem],
    valuations: List[ValuationInfo],
) -> dict:
    need_rebalance = any(d.need_rebalance for d in deviations)
    has_overvalued = any(v.is_overvalued for v in valuations)

    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "need_rebalance": need_rebalance,
        "has_overvalued": has_overvalued,
        "deviations": deviations,
        "valuations": valuations,
    }


def _render_html(report: dict) -> str:
    date = report["date"]
    deviations = report["deviations"]
    valuations = report["valuations"]

    rows = ""
    for d in deviations:
        flag = "!!!" if d.need_rebalance else "OK"
        rows += (
            f"<tr><td>{d.name}</td><td>{d.code}</td>"
            f"<td>{d.amount:.1f}W</td>"
            f"<td>{d.current_pct*100:.1f}%</td>"
            f"<td>{d.target_pct*100:.1f}%</td>"
            f"<td>{d.deviation*100:+.1f}%</td>"
            f"<td>{flag}</td></tr>"
        )
    val_rows = ""
    for v in valuations:
        if v.current_pe is not None:
            flag = "!!!" if v.is_overvalued else "OK"
            val_rows += (
                f"<tr><td>{v.index_name}</td>"
                f"<td>{v.current_pe}</td>"
                f"<td>{v.percentile:.1f}%</td>"
                f"<td>{flag}</td></tr>"
            )
        else:
            val_rows += (
                f"<tr><td>{v.index_name}</td>"
                f"<td colspan='3'>数据获取失败</td></tr>"
            )

    html = f"""<h2>核心仓监控报告 - {date}</h2>
<h3>持仓比例</h3>
<table border="1" cellpadding="5" cellspacing="0">
<tr><th>名称</th><th>代码</th><th>金额</th><th>当前比例</th><th>目标比例</th><th>偏离</th><th>状态</th></tr>
{rows}
</table>
<h3>估值分位</h3>
<table border="1" cellpadding="5" cellspacing="0">
<tr><th>指数</th><th>当前PE</th><th>历史分位</th><th>状态</th></tr>
{val_rows}
</table>
"""
    if report["need_rebalance"]:
        html += "<p><b>需要再平衡：部分 ETF 偏离目标超过阈值</b></p>"
    if report["has_overvalued"]:
        html += "<p><b>估值预警：部分指数 PE 处于历史高位，考虑减仓</b></p>"
    return html


def _render_plain(report: dict) -> str:
    date = report["date"]
    lines = [f"核心仓监控报告 - {date}", "", "【持仓比例】"]
    for d in report["deviations"]:
        flag = "!!!" if d.need_rebalance else "OK"
        lines.append(
            f"  {d.name}({d.code}): {d.amount:.1f}W | "
            f"当前 {d.current_pct*100:.1f}% | "
            f"目标 {d.target_pct*100:.1f}% | "
            f"偏离 {d.deviation*100:+.1f}% [{flag}]"
        )
    lines.append("")
    lines.append("【估值分位】")
    for v in report["valuations"]:
        if v.current_pe is not None:
            flag = "!!!" if v.is_overvalued else "OK"
            lines.append(
                f"  {v.index_name}: PE={v.current_pe} | "
                f"分位 {v.percentile:.1f}% [{flag}]"
            )
        else:
            lines.append(f"  {v.index_name}: 数据获取失败")
    return "\n".join(lines)


def run_monitor(notify: bool = True) -> dict:
    config = load_config()
    deviations = check_balance(config)
    if not deviations:
        logger.warning("持仓数据为空，请先更新 config.json 中的 holdings.amount")
        return {}

    alert_pct = config.get("pe_alert_percentile", 90)
    valuations = [
        get_csi300_valuation(alert_pct),
        get_nasdaq_valuation(alert_pct),
    ]

    report = generate_report(deviations, valuations)

    print(_render_plain(report))

    if notify and (report["need_rebalance"] or report["has_overvalued"]):
        subject = f"【核心仓监控】{report['date']}"
        if report["need_rebalance"]:
            subject += " - 需要再平衡"
        if report["has_overvalued"]:
            subject += " - 估值预警"
        try:
            send_email(
                subject=subject,
                html_body=_render_html(report),
                plain_body=_render_plain(report),
            )
            print("\n邮件通知已发送")
        except Exception as e:
            logger.error(f"邮件发送失败: {e}")
            print(f"\n邮件发送失败: {e}")

    return report

