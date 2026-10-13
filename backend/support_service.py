from __future__ import annotations

from typing import Any

from backend.conversation_store import (
    get_conversation,
    get_support_settings,
    is_blacklisted,
    list_quick_replies,
    match_quick_reply,
    record_message,
    support_started,
)


class SupportBlockedError(PermissionError):
    pass


def normalize_message(
    message_type: str,
    content: str,
    payload: dict[str, Any] | None,
) -> tuple[str, dict[str, Any]]:
    payload = dict(payload or {})
    content = str(content or "").strip()

    if message_type == "text":
        if not content:
            raise ValueError("文本消息不能为空")
        return content[:4000], {}

    if message_type == "image":
        url = str(payload.get("url") or "").strip()
        if not url:
            raise ValueError("图片消息缺少 url")
        allowed_url = (
            url.startswith("/uploads/")
            or url.startswith("https://")
            or url.startswith("http://")
            or url.startswith("data:image/")
        )
        if not allowed_url:
            raise ValueError("图片地址格式不正确")
        return content[:500], {
            "url": url[:8000],
            "alt": str(payload.get("alt") or "图片").strip()[:200],
            "name": str(payload.get("name") or "").strip()[:255],
        }

    if message_type == "mini_program":
        title = str(payload.get("title") or "").strip()
        if not title:
            raise ValueError("小程序卡片标题不能为空")
        return content[:500], {
            "title": title[:200],
            "description": str(payload.get("description") or "").strip()[:500],
            "app_id": str(payload.get("app_id") or "").strip()[:120],
            "path": str(payload.get("path") or "").strip()[:500],
            "image_url": str(payload.get("image_url") or "").strip()[:8000],
        }

    raise ValueError(f"不支持的消息类型：{message_type}")


def public_support_config() -> dict[str, Any]:
    settings = get_support_settings()
    return {
        "service_online": bool(settings["service_online"]),
        "agent_name": settings["agent_name"],
        "quick_questions": [
            {
                "id": item["id"],
                "question": item["question"],
                "category": item.get("category") or "",
            }
            for item in list_quick_replies(enabled_only=True)
        ],
    }


def send_customer_message(
    *,
    session_id: str,
    message_type: str,
    content: str,
    payload: dict[str, Any] | None,
    client_ip: str,
    user_agent: str,
) -> dict[str, Any]:
    blocked = is_blacklisted(session_id=session_id, client_ip=client_ip)
    if blocked:
        raise SupportBlockedError("当前会话已被限制发送消息")

    normalized_content, normalized_payload = normalize_message(
        message_type, content, payload
    )
    first_support_message = not support_started(session_id)
    customer_message = record_message(
        session_id,
        "user",
        normalized_content,
        client_ip=client_ip,
        user_agent=user_agent,
        sender_type="customer",
        sender_name="访客",
        message_type=message_type,
        payload=normalized_payload,
        support_message=True,
    )

    settings = get_support_settings()
    agent_name = settings["agent_name"]
    automated_messages = []
    sent_texts: set[str] = set()

    def send_automatic(text: str, source: str) -> None:
        text = str(text or "").strip()
        if not text or text in sent_texts:
            return
        sent_texts.add(text)
        automated_messages.append(
            record_message(
                session_id,
                "assistant",
                text,
                client_ip=client_ip,
                user_agent=user_agent,
                generation_source=source,
                sender_type="auto",
                sender_name=agent_name,
                metadata={"support_auto_reply": True, "source": source},
                support_message=True,
            )
        )

    if first_support_message and settings["welcome_enabled"]:
        send_automatic(settings["welcome_text"], "support_welcome")

    quick_reply = None
    if message_type == "text" and settings["auto_reply_enabled"]:
        quick_reply = match_quick_reply(normalized_content)

    if not settings["service_online"]:
        send_automatic(settings["offline_reply_text"], "support_offline")
    elif quick_reply:
        send_automatic(quick_reply["answer"], "support_quick_reply")
    elif settings["auto_reply_enabled"]:
        send_automatic(settings["auto_reply_text"], "support_auto_reply")

    return {
        "ok": True,
        "message": customer_message,
        "automated_messages": automated_messages,
        "service_online": bool(settings["service_online"]),
    }


def send_agent_message(
    *,
    session_id: str,
    message_type: str,
    content: str,
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    conversation = get_conversation(session_id)
    if conversation is None:
        raise LookupError("未找到该对话")
    if conversation["conversation"].get("is_blacklisted"):
        raise SupportBlockedError("该会话在黑名单中，请先移出黑名单")

    normalized_content, normalized_payload = normalize_message(
        message_type, content, payload
    )
    settings = get_support_settings()
    return record_message(
        session_id,
        "assistant",
        normalized_content,
        sender_type="agent",
        sender_name=settings["agent_name"],
        message_type=message_type,
        payload=normalized_payload,
        metadata={"human_agent": True},
        support_message=True,
    )
