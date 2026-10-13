import json
import os
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen


def wecom_config() -> dict[str, Any]:
    return {
        "webhook_url": os.getenv("WECOM_LEAD_WEBHOOK_URL", "").strip(),
        "timeout": float(os.getenv("WECOM_WEBHOOK_TIMEOUT_SECONDS", "10")),
    }


def send_wecom_lead(record: dict[str, Any]) -> tuple[bool, str | None]:
    config = wecom_config()
    webhook_url = config["webhook_url"]
    if not webhook_url:
        return False, "WECOM_LEAD_WEBHOOK_URL is not configured"

    content = "\n".join([
        "[华博士] 新报价需求",
        f"咨询产品：{record.get('product_name') or '未填写'}",
        f"姓名：{record.get('name') or '未填写'}",
        f"联系方式：{record.get('phone') or '未填写'}",
        f"单位/机构：{record.get('organization') or '未填写'}",
        f"需求备注：{record.get('requirement') or '未填写'}",
        f"提交时间：{record.get('created_at') or '未填写'}",
    ])
    payload = json.dumps(
        {"msgtype": "text", "text": {"content": content}},
        ensure_ascii=False,
    ).encode("utf-8")
    request = Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=config["timeout"]) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (URLError, OSError, ValueError) as exc:
        return False, str(exc)

    if result.get("errcode") != 0:
        return False, result.get("errmsg", "WeCom webhook request failed")
    return True, None
