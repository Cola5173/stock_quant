"""量化交易平台 CLI 入口"""
import argparse
import sys
from datetime import datetime


def cmd_advisor(args):
    from api.advisor.decision_engine import run_decision
    from api.notifier.email_sender import send_email
    from api.notifier.templates import render_html, render_plain_text, render_subject

    date = args.date or datetime.now().strftime("%Y-%m-%d")

    if args.email_only:
        import json
        import os
        from api.config import settings
        path = os.path.join(settings.DECISIONS_DIR,
                            f"decision_{date.replace('-', '')}.json")
        if not os.path.exists(path):
            print(f"决策文件不存在: {path}")
            sys.exit(1)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        from api.advisor.decision_schema import Decision
        decision = Decision(
            date=data["date"],
            next_trading_date=data["next_trading_date"],
            market=data["market"],
            cooldown=data.get("cooldown", {}),
            holdings=data.get("holdings", []),
            actions=data.get("actions", []),
            warnings=data.get("warnings", []),
        )
    else:
        decision = run_decision(date)

    if args.no_email:
        print(f"决策已生成，跳过邮件发送")
    else:
        send_email(
            subject=render_subject(decision),
            html_body=render_html(decision),
            plain_body=render_plain_text(decision),
        )
        print("邮件已发送")


def main():
    parser = argparse.ArgumentParser(description="A 股量化交易平台")
    sub = parser.add_subparsers(dest="command")

    p_adv = sub.add_parser("advisor", help="生成决策 + 邮件通知")
    p_adv.add_argument("--date", default=None, help="日期 YYYY-MM-DD，默认今日")
    p_adv.add_argument("--no-email", action="store_true", help="仅生成决策不发邮件")
    p_adv.add_argument("--email-only", action="store_true", help="用已有决策文件仅发邮件")

    args = parser.parse_args()
    if args.command == "advisor":
        cmd_advisor(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
