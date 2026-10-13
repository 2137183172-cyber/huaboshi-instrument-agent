import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr
from typing import Any

from dotenv import load_dotenv

load_dotenv()


def email_config() -> dict[str, Any]:
    use_ssl = os.getenv("SMTP_USE_SSL", "true").strip().lower() not in {"0", "false", "no"}
    default_port = "465" if use_ssl else "587"
    return {
        "recipient": os.getenv("LEAD_NOTIFY_EMAIL", "contact@example.org").strip(),
        "host": os.getenv("SMTP_HOST", "").strip(),
        "port": int(os.getenv("SMTP_PORT", default_port)),
        "user": os.getenv("SMTP_USER", "").strip(),
        "password": os.getenv("SMTP_PASSWORD", "").strip(),
        "sender": os.getenv("SMTP_FROM", os.getenv("SMTP_USER", "")).strip(),
        "sender_name": os.getenv("SMTP_FROM_NAME", "华博士").strip(),
        "use_ssl": use_ssl,
    }


def build_lead_email(record: dict[str, Any]) -> EmailMessage:
    config = email_config()
    product_name = record.get("product_name") or "未填写产品"
    subject = f"新的产品报价需求：{product_name}"
    body = "\n".join([
        "收到新的产品报价需求，请及时联系客户。",
        "",
        f"产品：{product_name}",
        f"姓名：{record.get('name', '')}",
        f"联系方式：{record.get('phone', '')}",
        f"单位/机构：{record.get('organization', '') or '未填写'}",
        f"需求备注：{record.get('requirement', '') or '未填写'}",
        f"来源：{record.get('source', '') or 'chat'}",
        f"提交时间：{record.get('created_at', '')}",
    ])

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((config["sender_name"], config["sender"]))
    msg["To"] = config["recipient"]
    msg.set_content(body)
    return msg


def send_lead_email(record: dict[str, Any]) -> tuple[bool, str | None]:
    config = email_config()
    missing = [
        key
        for key in ["recipient", "host", "user", "password", "sender"]
        if not config.get(key)
    ]
    if missing:
        return False, "SMTP 配置不完整，请检查 " + ", ".join(missing)

    msg = build_lead_email(record)

    try:
        if config["use_ssl"]:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(config["host"], config["port"], context=context, timeout=20) as smtp:
                smtp.login(config["user"], config["password"])
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(config["host"], config["port"], timeout=20) as smtp:
                smtp.starttls(context=ssl.create_default_context())
                smtp.login(config["user"], config["password"])
                smtp.send_message(msg)
    except Exception as exc:
        return False, str(exc)

    return True, None
