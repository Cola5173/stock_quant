"""邮件 HTML/纯文本模板渲染"""
from api.advisor.decision_schema import Decision


def render_subject(decision: Decision) -> str:
    market = decision.market
    status = "允许买入" if market.get("allow_buy") else "禁止买入"
    strength = "强势" if market.get("is_strong") else "弱势"
    return f"【量化日报】{decision.date} · 大盘:{status}/{strength}"


def render_html(decision: Decision) -> str:
    """全 inline style、table 布局、字号 ≥ 14px"""
    parts = []
    parts.append('<div style="font-family:Arial,sans-serif;font-size:14px;color:#333;">')

    # 标题
    parts.append(f'<h2 style="font-size:18px;margin:0 0 12px 0;">{render_subject(decision)}</h2>')

    # 冷却提示
    if decision.cooldown.get("active"):
        parts.append(
            f'<p style="color:#e65100;font-weight:bold;">连续亏损冷却中，'
            f'剩余 {decision.cooldown["remaining_days"]} 个交易日</p>'
        )

    # 持仓表
    if decision.holdings:
        parts.append('<h3 style="font-size:16px;margin:16px 0 8px 0;">持仓概览</h3>')
        parts.append(
            '<table style="border-collapse:collapse;width:100%;font-size:14px;">'
            '<tr style="background:#f5f5f5;">'
            '<th style="padding:6px;border:1px solid #ddd;text-align:left;">代码</th>'
            '<th style="padding:6px;border:1px solid #ddd;text-align:left;">名称</th>'
            '<th style="padding:6px;border:1px solid #ddd;text-align:right;">持有天数</th>'
            '<th style="padding:6px;border:1px solid #ddd;text-align:right;">成本</th>'
            '<th style="padding:6px;border:1px solid #ddd;text-align:right;">现价</th>'
            '<th style="padding:6px;border:1px solid #ddd;text-align:right;">浮盈%</th>'
            '<th style="padding:6px;border:1px solid #ddd;text-align:right;">止盈档</th>'
            '</tr>'
        )
        for h in decision.holdings:
            h_dict = vars(h) if hasattr(h, '__dict__') else h
            color = "#c62828" if h_dict.get("profit_pct", 0) < 0 else "#2e7d32"
            parts.append(
                f'<tr>'
                f'<td style="padding:6px;border:1px solid #ddd;">{h_dict["symbol"]}</td>'
                f'<td style="padding:6px;border:1px solid #ddd;">{h_dict["name"]}</td>'
                f'<td style="padding:6px;border:1px solid #ddd;text-align:right;">{h_dict["hold_days"]}</td>'
                f'<td style="padding:6px;border:1px solid #ddd;text-align:right;">{h_dict["cost_price"]:.2f}</td>'
                f'<td style="padding:6px;border:1px solid #ddd;text-align:right;">{h_dict["current_close"]:.2f}</td>'
                f'<td style="padding:6px;border:1px solid #ddd;text-align:right;color:{color};">'
                f'{h_dict["profit_pct"]:+.2f}%</td>'
                f'<td style="padding:6px;border:1px solid #ddd;text-align:right;">{h_dict["tp_level_done"]}</td>'
                f'</tr>'
            )
        parts.append('</table>')

    # 动作表
    parts.append('<h3 style="font-size:16px;margin:16px 0 8px 0;">明日动作</h3>')
    parts.append(
        '<table style="border-collapse:collapse;width:100%;font-size:14px;">'
        '<tr style="background:#f5f5f5;">'
        '<th style="padding:6px;border:1px solid #ddd;text-align:left;">动作</th>'
        '<th style="padding:6px;border:1px solid #ddd;text-align:left;">代码</th>'
        '<th style="padding:6px;border:1px solid #ddd;text-align:left;">详情</th>'
        '<th style="padding:6px;border:1px solid #ddd;text-align:left;">原因</th>'
        '</tr>'
    )
    COLOR_MAP = {"sell": "#ffcccc", "buy": "#ccffcc", "hold": "#f0f0f0", "wait": "#f0f0f0"}
    for a in decision.actions:
        a_dict = vars(a) if hasattr(a, '__dict__') else a
        bg = COLOR_MAP.get(a_dict["kind"], "#fff")
        if a_dict["kind"] == "sell":
            detail = f'{a_dict.get("shares", "")} 股 · {a_dict.get("exec_desc", "")}'
        elif a_dict["kind"] == "buy":
            detail = (f'≈{a_dict.get("estimated_shares", "")} 股 · '
                      f'金额 {a_dict.get("amount", 0):,.0f} · {a_dict.get("exec_desc", "")}')
        else:
            detail = ""
        parts.append(
            f'<tr style="background-color:{bg};">'
            f'<td style="padding:6px;border:1px solid #ddd;font-weight:bold;">'
            f'{a_dict["kind"].upper()}</td>'
            f'<td style="padding:6px;border:1px solid #ddd;">'
            f'{a_dict.get("symbol", "")}{" " + a_dict.get("name", "") if a_dict.get("name") else ""}</td>'
            f'<td style="padding:6px;border:1px solid #ddd;">{detail}</td>'
            f'<td style="padding:6px;border:1px solid #ddd;">{a_dict.get("reason", "")}</td>'
            f'</tr>'
        )
    parts.append('</table>')

    # warnings
    if decision.warnings:
        parts.append('<h3 style="font-size:16px;margin:16px 0 8px 0;color:#e65100;">警告</h3>')
        parts.append('<ul style="margin:0;padding-left:20px;">')
        for w in decision.warnings:
            parts.append(f'<li style="margin:4px 0;">{w}</li>')
        parts.append('</ul>')

    # 脚注
    parts.append(
        '<hr style="margin:16px 0;border:none;border-top:1px solid #ddd;">'
        '<p style="font-size:12px;color:#888;">卖出规则：'
        '0.硬止损(弱-4%/强-7%) | 1.跌破大哥黄 | 2.阴线放量 | '
        '3.破趋势白(曾上穿) | 4.T+3不涨 | 5.9级分批止盈</p>'
        '<p style="font-size:12px;color:#888;">维护提示：卖出成交后请在 '
        'data/closed_trades.json 追加记录（pnl_pct/ratio），并更新 positions.json</p>'
    )

    parts.append('</div>')
    return "\n".join(parts)


def render_plain_text(decision: Decision) -> str:
    """纯文本 fallback"""
    lines = [render_subject(decision), ""]

    if decision.cooldown.get("active"):
        lines.append(f"!! 连续亏损冷却中，剩余 {decision.cooldown['remaining_days']} 个交易日")
        lines.append("")

    if decision.holdings:
        lines.append("== 持仓 ==")
        for h in decision.holdings:
            h_dict = vars(h) if hasattr(h, '__dict__') else h
            lines.append(
                f"  {h_dict['symbol']} {h_dict['name']} | "
                f"持{h_dict['hold_days']}天 | 成本{h_dict['cost_price']:.2f} | "
                f"现价{h_dict['current_close']:.2f} | "
                f"浮盈{h_dict['profit_pct']:+.2f}%"
            )
        lines.append("")

    lines.append("== 明日动作 ==")
    for a in decision.actions:
        a_dict = vars(a) if hasattr(a, '__dict__') else a
        sym_name = f"{a_dict.get('symbol', '')} {a_dict.get('name', '')}".strip()
        lines.append(f"  [{a_dict['kind'].upper()}] {sym_name} - {a_dict.get('reason', '')}")
    lines.append("")

    if decision.warnings:
        lines.append("== 警告 ==")
        for w in decision.warnings:
            lines.append(f"  ! {w}")

    lines.append("")
    lines.append("维护提示：卖出成交后请在 closed_trades.json 追加记录")
    return "\n".join(lines)
