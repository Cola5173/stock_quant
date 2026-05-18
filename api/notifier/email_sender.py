"""QQ 邮箱 SMTP 发送"""
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from api.config import settings
from api.utils.retry import retry_call

logger = logging.getLogger(__name__)


def send_email(subject: str, html_body: str, plain_body: str,
               retry_interval: int = None):
    cfg = settings.EMAIL_CONFIG
    if not cfg["user"] or not cfg["password"]:
        raise RuntimeError("QQ_EMAIL_USER 或 QQ_EMAIL_PASS 未配置")

    interval = (retry_interval if retry_interval is not None
                else settings.ADVISOR_CONFIG["retry_interval_sec"])

    def _send():
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{cfg['sender_name']} <{cfg['user']}>"
        msg["To"] = cfg["to"] or cfg["user"]
        msg.attach(MIMEText(plain_body, "plain", "utf-8"))
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        with smtplib.SMTP_SSL(cfg["host"], cfg["port"]) as server:
            server.login(cfg["user"], cfg["password"])
            server.sendmail(cfg["user"], msg["To"], msg.as_string())

    retry_call(_send, times=settings.ADVISOR_CONFIG["retry_times"], interval=interval)
    logger.info(f"邮件已发送: {subject}")


def send_error_email(step: str, error_msg: str):
    subject = f"【量化日报-异常】{step}"
    body = f"步骤 {step} 执行失败:\n\n{error_msg[-3000:]}"
    try:
        send_email(subject=subject, html_body=f"<pre>{body}</pre>",
                   plain_body=body, retry_interval=10)
    except Exception as e:
        logger.error(f"错误邮件发送失败: {e}")
