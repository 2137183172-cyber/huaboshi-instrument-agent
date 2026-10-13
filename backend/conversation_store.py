from __future__ import annotations

import json
import os
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_DIR / "data" / "conversations.db"
DB_LOCK = Lock()

DEFAULT_SUPPORT_SETTINGS: dict[str, Any] = {
    "service_online": True,
    "welcome_enabled": True,
    "welcome_text": "您好，已为您接入华博士客服，请描述您的产品或实验需求。",
    "auto_reply_enabled": True,
    "auto_reply_text": "已收到您的消息，客服会尽快回复。您也可以补充样本类型、通量、预算和采购时间。",
    "offline_reply_text": "当前为离线时段，我们已经记录您的消息，客服上线后会尽快联系您。",
    "agent_name": "华博士客服",
}

VALID_STATUSES = {"open", "pending", "closed", "blocked"}
VALID_MESSAGE_TYPES = {"text", "image", "mini_program"}
VALID_SENDER_TYPES = {"customer", "assistant", "agent", "auto", "system"}
VALID_BLACKLIST_KINDS = {"session_id", "client_ip"}
CHINA_TIMEZONE = timezone(timedelta(hours=8))


def database_path() -> Path:
    configured = os.getenv("CONVERSATION_DB_PATH", "").strip()
    return Path(configured) if configured else DEFAULT_DB_PATH


def connect() -> sqlite3.Connection:
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def _ensure_column(
    connection: sqlite3.Connection,
    table: str,
    column: str,
    definition: str,
) -> None:
    columns = {
        row["name"]
        for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_database() -> None:
    with DB_LOCK, closing(connect()) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                session_id TEXT PRIMARY KEY,
                started_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                client_ip TEXT,
                user_agent TEXT,
                message_count INTEGER NOT NULL DEFAULT 0,
                last_user_message TEXT,
                last_answer TEXT,
                status TEXT NOT NULL DEFAULT 'open',
                support_started INTEGER NOT NULL DEFAULT 0,
                unread_for_agent INTEGER NOT NULL DEFAULT 0,
                unread_for_customer INTEGER NOT NULL DEFAULT 0,
                last_sender_type TEXT,
                last_message_type TEXT,
                last_agent_message TEXT
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                intent TEXT,
                generation_source TEXT,
                model_name TEXT,
                latency_ms REAL,
                metadata_json TEXT,
                sender_type TEXT,
                sender_name TEXT,
                message_type TEXT NOT NULL DEFAULT 'text',
                payload_json TEXT,
                FOREIGN KEY(session_id) REFERENCES conversations(session_id)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS support_settings (
                key TEXT PRIMARY KEY,
                value_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS quick_replies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                category TEXT,
                enabled INTEGER NOT NULL DEFAULT 1,
                auto_match INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS blacklist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                value TEXT NOT NULL,
                reason TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(kind, value)
            );

            CREATE INDEX IF NOT EXISTS idx_messages_session_created
            ON messages(session_id, created_at, id);

            CREATE INDEX IF NOT EXISTS idx_messages_session_id
            ON messages(session_id, id);

            CREATE INDEX IF NOT EXISTS idx_conversations_updated
            ON conversations(updated_at DESC);

            CREATE INDEX IF NOT EXISTS idx_quick_replies_enabled_order
            ON quick_replies(enabled, sort_order, id);
            """
        )

        # 兼容旧版 conversations.db，按列增量迁移，不要求用户删除数据库。
        conversation_columns = {
            "status": "TEXT NOT NULL DEFAULT 'open'",
            "support_started": "INTEGER NOT NULL DEFAULT 0",
            "unread_for_agent": "INTEGER NOT NULL DEFAULT 0",
            "unread_for_customer": "INTEGER NOT NULL DEFAULT 0",
            "last_sender_type": "TEXT",
            "last_message_type": "TEXT",
            "last_agent_message": "TEXT",
        }
        for column, definition in conversation_columns.items():
            _ensure_column(connection, "conversations", column, definition)

        message_columns = {
            "sender_type": "TEXT",
            "sender_name": "TEXT",
            "message_type": "TEXT NOT NULL DEFAULT 'text'",
            "payload_json": "TEXT",
        }
        for column, definition in message_columns.items():
            _ensure_column(connection, "messages", column, definition)

        # This index depends on a column introduced by the migration above.
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_conversations_status_updated "
            "ON conversations(status, updated_at DESC)"
        )

        created_at = now_text()
        for key, value in DEFAULT_SUPPORT_SETTINGS.items():
            connection.execute(
                """
                INSERT OR IGNORE INTO support_settings (key, value_json, updated_at)
                VALUES (?, ?, ?)
                """,
                (key, json.dumps(value, ensure_ascii=False), created_at),
            )
        connection.commit()


def now_text() -> str:
    # Store China local time without an offset to preserve the existing SQLite format.
    return china_now().replace(tzinfo=None).isoformat(timespec="seconds")


def china_now() -> datetime:
    return datetime.now(CHINA_TIMEZONE)


def _load_json(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _message_summary(message_type: str, content: str, payload: dict[str, Any]) -> str:
    text = " ".join(str(content or "").split())
    if text:
        return text[:500]
    if message_type == "image":
        return "[图片]"
    if message_type == "mini_program":
        title = " ".join(str(payload.get("title") or "").split())
        return f"[小程序卡片] {title}".strip()
    return "[消息]"


def _serialize_message(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    item = dict(row)
    item["metadata"] = _load_json(item.pop("metadata_json", None), {})
    item["payload"] = _load_json(item.pop("payload_json", None), {})
    item["message_type"] = item.get("message_type") or "text"
    item["sender_type"] = item.get("sender_type") or (
        "customer" if item.get("role") == "user" else "assistant"
    )
    item["sender_name"] = item.get("sender_name") or ""
    return item


def record_message(
    session_id: str,
    role: str,
    content: str,
    *,
    client_ip: str = "",
    user_agent: str = "",
    intent: str = "",
    generation_source: str = "",
    model_name: str = "",
    latency_ms: float | None = None,
    metadata: dict[str, Any] | None = None,
    sender_type: str = "",
    sender_name: str = "",
    message_type: str = "text",
    payload: dict[str, Any] | None = None,
    support_message: bool = False,
) -> dict[str, Any]:
    init_database()
    session_id = session_id.strip()
    if not session_id:
        raise ValueError("session_id 不能为空")

    storage_role = role if role in {"user", "assistant"} else "assistant"
    resolved_sender = sender_type or (
        "customer" if storage_role == "user" else "assistant"
    )
    if resolved_sender not in VALID_SENDER_TYPES:
        raise ValueError(f"不支持的发送方类型：{resolved_sender}")
    if message_type not in VALID_MESSAGE_TYPES:
        raise ValueError(f"不支持的消息类型：{message_type}")

    created_at = now_text()
    payload = payload or {}
    summary = _message_summary(message_type, content, payload)
    stored_content = str(content or "").strip() or summary
    metadata_payload = dict(metadata or {})
    if support_message:
        metadata_payload["support_message"] = True
    metadata_json = json.dumps(metadata_payload, ensure_ascii=False)
    payload_json = json.dumps(payload, ensure_ascii=False)

    customer_message = resolved_sender == "customer"
    agent_message = resolved_sender == "agent"
    notify_customer = resolved_sender in {"agent", "auto", "system"}

    with DB_LOCK, closing(connect()) as connection:
        connection.execute(
            """
            INSERT INTO conversations (
                session_id, started_at, updated_at, client_ip, user_agent,
                message_count, last_user_message, last_answer, status,
                support_started, unread_for_agent, unread_for_customer
            ) VALUES (?, ?, ?, ?, ?, 0, NULL, NULL, 'open', ?, 0, 0)
            ON CONFLICT(session_id) DO UPDATE SET
                updated_at = excluded.updated_at,
                client_ip = CASE
                    WHEN excluded.client_ip <> '' THEN excluded.client_ip
                    ELSE conversations.client_ip
                END,
                user_agent = CASE
                    WHEN excluded.user_agent <> '' THEN excluded.user_agent
                    ELSE conversations.user_agent
                END,
                support_started = CASE
                    WHEN excluded.support_started = 1 THEN 1
                    ELSE conversations.support_started
                END,
                status = CASE
                    WHEN conversations.status = 'closed' AND excluded.support_started = 1 THEN 'open'
                    ELSE conversations.status
                END
            """,
            (
                session_id,
                created_at,
                created_at,
                client_ip,
                user_agent,
                1 if support_message else 0,
            ),
        )
        cursor = connection.execute(
            """
            INSERT INTO messages (
                session_id, role, content, created_at, intent,
                generation_source, model_name, latency_ms, metadata_json,
                sender_type, sender_name, message_type, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                storage_role,
                stored_content,
                created_at,
                intent or None,
                generation_source or None,
                model_name or None,
                latency_ms,
                metadata_json,
                resolved_sender,
                sender_name or None,
                message_type,
                payload_json,
            ),
        )
        connection.execute(
            """
            UPDATE conversations
            SET updated_at = ?,
                message_count = message_count + 1,
                support_started = CASE WHEN ? = 1 THEN 1 ELSE support_started END,
                last_sender_type = ?,
                last_message_type = ?,
                last_user_message = CASE WHEN ? = 1 THEN ? ELSE last_user_message END,
                last_answer = CASE WHEN ? = 0 THEN ? ELSE last_answer END,
                last_agent_message = CASE WHEN ? = 1 THEN ? ELSE last_agent_message END,
                unread_for_agent = unread_for_agent + ?,
                unread_for_customer = unread_for_customer + ?
            WHERE session_id = ?
            """,
            (
                created_at,
                1 if support_message else 0,
                resolved_sender,
                message_type,
                1 if customer_message else 0,
                summary,
                1 if customer_message else 0,
                summary,
                1 if agent_message else 0,
                summary,
                1 if customer_message and support_message else 0,
                1 if notify_customer else 0,
                session_id,
            ),
        )
        message_id = int(cursor.lastrowid)
        row = connection.execute(
            "SELECT * FROM messages WHERE id = ?",
            (message_id,),
        ).fetchone()
        connection.commit()
    return _serialize_message(row)


def list_conversations(
    limit: int = 50,
    offset: int = 0,
    query: str = "",
    status: str = "",
) -> dict[str, Any]:
    init_database()
    safe_limit = max(1, min(limit, 200))
    safe_offset = max(0, offset)
    clauses: list[str] = []
    params: list[Any] = []

    search = query.strip()
    if search:
        clauses.append(
            """
            (c.session_id LIKE ?
             OR COALESCE(c.last_user_message, '') LIKE ?
             OR COALESCE(c.last_answer, '') LIKE ?
             OR COALESCE(c.client_ip, '') LIKE ?)
            """
        )
        pattern = f"%{search}%"
        params.extend([pattern, pattern, pattern, pattern])
    if status and status in VALID_STATUSES:
        clauses.append("c.status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    blacklist_expression = """
        EXISTS (
            SELECT 1 FROM blacklist b
            WHERE (b.kind = 'session_id' AND b.value = c.session_id)
               OR (b.kind = 'client_ip' AND b.value = COALESCE(c.client_ip, ''))
        )
    """
    with closing(connect()) as connection:
        total = connection.execute(
            f"SELECT COUNT(*) AS total FROM conversations c {where}",
            params,
        ).fetchone()["total"]
        rows = connection.execute(
            f"""
            SELECT c.session_id, c.started_at, c.updated_at, c.client_ip,
                   c.user_agent, c.message_count, c.last_user_message,
                   c.last_answer, c.last_agent_message, c.status,
                   c.support_started, c.unread_for_agent,
                   c.unread_for_customer, c.last_sender_type,
                   c.last_message_type, {blacklist_expression} AS is_blacklisted
            FROM conversations c
            {where}
            ORDER BY c.updated_at DESC
            LIMIT ? OFFSET ?
            """,
            [*params, safe_limit, safe_offset],
        ).fetchall()
    items = [dict(row) for row in rows]
    for item in items:
        item["is_blacklisted"] = bool(item.get("is_blacklisted"))
        item["support_started"] = bool(item.get("support_started"))
    return {"total": int(total), "items": items}


def get_conversation(session_id: str) -> dict[str, Any] | None:
    init_database()
    with closing(connect()) as connection:
        conversation = connection.execute(
            "SELECT * FROM conversations WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if conversation is None:
            return None
        messages = connection.execute(
            """
            SELECT * FROM messages
            WHERE session_id = ?
            ORDER BY created_at, id
            """,
            (session_id,),
        ).fetchall()

    conversation_item = dict(conversation)
    conversation_item["support_started"] = bool(
        conversation_item.get("support_started")
    )
    blocked = is_blacklisted(
        session_id=session_id,
        client_ip=conversation_item.get("client_ip") or "",
    )
    conversation_item["is_blacklisted"] = bool(blocked)
    conversation_item["blacklist"] = blocked
    return {
        "conversation": conversation_item,
        "messages": [_serialize_message(row) for row in messages],
    }


def get_messages_since(session_id: str, after_id: int = 0) -> list[dict[str, Any]]:
    init_database()
    with closing(connect()) as connection:
        rows = connection.execute(
            """
            SELECT * FROM messages
            WHERE session_id = ? AND id > ?
            ORDER BY id
            LIMIT 300
            """,
            (session_id, max(0, after_id)),
        ).fetchall()
    return [_serialize_message(row) for row in rows]


def latest_message_id(session_id: str) -> int:
    init_database()
    with closing(connect()) as connection:
        row = connection.execute(
            "SELECT COALESCE(MAX(id), 0) AS latest FROM messages WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    return int(row["latest"] or 0)


def support_started(session_id: str) -> bool:
    init_database()
    with closing(connect()) as connection:
        row = connection.execute(
            "SELECT support_started FROM conversations WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    return bool(row and row["support_started"])


def mark_conversation_read(session_id: str, reader: str) -> bool:
    init_database()
    if reader not in {"agent", "customer"}:
        raise ValueError("reader 只能是 agent 或 customer")
    column = "unread_for_agent" if reader == "agent" else "unread_for_customer"
    with DB_LOCK, closing(connect()) as connection:
        cursor = connection.execute(
            f"UPDATE conversations SET {column} = 0 WHERE session_id = ?",
            (session_id,),
        )
        connection.commit()
    return cursor.rowcount > 0


def update_conversation_status(session_id: str, status: str) -> bool:
    init_database()
    if status not in VALID_STATUSES:
        raise ValueError(f"不支持的会话状态：{status}")
    with DB_LOCK, closing(connect()) as connection:
        cursor = connection.execute(
            "UPDATE conversations SET status = ?, updated_at = ? WHERE session_id = ?",
            (status, now_text(), session_id),
        )
        connection.commit()
    return cursor.rowcount > 0


def conversation_stats() -> dict[str, int]:
    init_database()
    today = china_now().date().isoformat()
    with closing(connect()) as connection:
        row = connection.execute(
            """
            SELECT
                COUNT(*) AS conversations,
                COALESCE(SUM(message_count), 0) AS messages,
                SUM(CASE WHEN date(started_at) = ? THEN 1 ELSE 0 END)
                    AS conversations_today,
                SUM(CASE WHEN date(updated_at) = ? THEN 1 ELSE 0 END)
                    AS active_today,
                SUM(CASE WHEN status = 'open' THEN 1 ELSE 0 END) AS open_conversations,
                COALESCE(SUM(unread_for_agent), 0) AS unread_for_agent
            FROM conversations
            """,
            (today, today),
        ).fetchone()
        blacklist_count = connection.execute(
            "SELECT COUNT(*) AS total FROM blacklist"
        ).fetchone()["total"]
    result = {key: int(row[key] or 0) for key in row.keys()}
    result["blacklist_count"] = int(blacklist_count or 0)
    return result


def delete_conversation(session_id: str) -> bool:
    init_database()
    with DB_LOCK, closing(connect()) as connection:
        cursor = connection.execute(
            "DELETE FROM conversations WHERE session_id = ?",
            (session_id,),
        )
        connection.commit()
    return cursor.rowcount > 0


def get_support_settings() -> dict[str, Any]:
    init_database()
    settings = dict(DEFAULT_SUPPORT_SETTINGS)
    with closing(connect()) as connection:
        rows = connection.execute(
            "SELECT key, value_json FROM support_settings"
        ).fetchall()
    for row in rows:
        if row["key"] in settings:
            settings[row["key"]] = _load_json(
                row["value_json"], settings[row["key"]]
            )
    return settings


def update_support_settings(values: dict[str, Any]) -> dict[str, Any]:
    init_database()
    cleaned: dict[str, Any] = {}
    for key, value in values.items():
        if key not in DEFAULT_SUPPORT_SETTINGS:
            continue
        default = DEFAULT_SUPPORT_SETTINGS[key]
        if isinstance(default, bool):
            cleaned[key] = bool(value)
            continue
        text = str(value or "").strip()
        max_length = 80 if key == "agent_name" else 2000
        cleaned[key] = text[:max_length]

    updated_at = now_text()
    with DB_LOCK, closing(connect()) as connection:
        for key, value in cleaned.items():
            connection.execute(
                """
                INSERT INTO support_settings (key, value_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value_json = excluded.value_json,
                    updated_at = excluded.updated_at
                """,
                (key, json.dumps(value, ensure_ascii=False), updated_at),
            )
        connection.commit()
    return get_support_settings()


def list_quick_replies(enabled_only: bool = False) -> list[dict[str, Any]]:
    init_database()
    where = "WHERE enabled = 1" if enabled_only else ""
    with closing(connect()) as connection:
        rows = connection.execute(
            f"""
            SELECT id, question, answer, category, enabled, auto_match,
                   sort_order, created_at, updated_at
            FROM quick_replies
            {where}
            ORDER BY sort_order, id
            """
        ).fetchall()
    items = [dict(row) for row in rows]
    for item in items:
        item["enabled"] = bool(item["enabled"])
        item["auto_match"] = bool(item["auto_match"])
    return items


def create_quick_reply(
    question: str,
    answer: str,
    *,
    category: str = "",
    enabled: bool = True,
    auto_match: bool = True,
    sort_order: int = 0,
) -> dict[str, Any]:
    init_database()
    question = question.strip()
    answer = answer.strip()
    if not question or not answer:
        raise ValueError("快捷回复的问题和答案不能为空")
    created_at = now_text()
    with DB_LOCK, closing(connect()) as connection:
        cursor = connection.execute(
            """
            INSERT INTO quick_replies (
                question, answer, category, enabled, auto_match,
                sort_order, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                question[:500],
                answer[:4000],
                category.strip()[:100] or None,
                1 if enabled else 0,
                1 if auto_match else 0,
                int(sort_order),
                created_at,
                created_at,
            ),
        )
        item_id = int(cursor.lastrowid)
        connection.commit()
    return get_quick_reply(item_id) or {}


def get_quick_reply(item_id: int) -> dict[str, Any] | None:
    init_database()
    with closing(connect()) as connection:
        row = connection.execute(
            "SELECT * FROM quick_replies WHERE id = ?",
            (item_id,),
        ).fetchone()
    if row is None:
        return None
    item = dict(row)
    item["enabled"] = bool(item["enabled"])
    item["auto_match"] = bool(item["auto_match"])
    return item


def update_quick_reply(item_id: int, values: dict[str, Any]) -> dict[str, Any] | None:
    init_database()
    allowed = {
        "question": lambda value: str(value or "").strip()[:500],
        "answer": lambda value: str(value or "").strip()[:4000],
        "category": lambda value: str(value or "").strip()[:100],
        "enabled": lambda value: 1 if bool(value) else 0,
        "auto_match": lambda value: 1 if bool(value) else 0,
        "sort_order": lambda value: int(value or 0),
    }
    cleaned = {
        key: converter(values[key])
        for key, converter in allowed.items()
        if key in values
    }
    if "question" in cleaned and not cleaned["question"]:
        raise ValueError("快捷回复问题不能为空")
    if "answer" in cleaned and not cleaned["answer"]:
        raise ValueError("快捷回复答案不能为空")
    if not cleaned:
        return get_quick_reply(item_id)

    assignments = ", ".join(f"{key} = ?" for key in cleaned)
    params = [*cleaned.values(), now_text(), item_id]
    with DB_LOCK, closing(connect()) as connection:
        cursor = connection.execute(
            f"UPDATE quick_replies SET {assignments}, updated_at = ? WHERE id = ?",
            params,
        )
        connection.commit()
    return get_quick_reply(item_id) if cursor.rowcount else None


def delete_quick_reply(item_id: int) -> bool:
    init_database()
    with DB_LOCK, closing(connect()) as connection:
        cursor = connection.execute(
            "DELETE FROM quick_replies WHERE id = ?",
            (item_id,),
        )
        connection.commit()
    return cursor.rowcount > 0


def _normalize_question(value: str) -> str:
    return re.sub(r"[\s？?。！!，,；;：:]+", "", value or "").casefold()


def match_quick_reply(message: str) -> dict[str, Any] | None:
    query = _normalize_question(message)
    if not query:
        return None
    for item in list_quick_replies(enabled_only=True):
        if not item.get("auto_match"):
            continue
        question = _normalize_question(item.get("question", ""))
        if question and question == query:
            return item
    return None


def list_blacklist() -> list[dict[str, Any]]:
    init_database()
    with closing(connect()) as connection:
        rows = connection.execute(
            """
            SELECT id, kind, value, reason, created_at
            FROM blacklist
            ORDER BY created_at DESC, id DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def add_blacklist(kind: str, value: str, reason: str = "") -> dict[str, Any]:
    init_database()
    if kind not in VALID_BLACKLIST_KINDS:
        raise ValueError("黑名单类型只能是 session_id 或 client_ip")
    value = value.strip()
    if not value:
        raise ValueError("黑名单值不能为空")
    created_at = now_text()
    with DB_LOCK, closing(connect()) as connection:
        connection.execute(
            """
            INSERT INTO blacklist (kind, value, reason, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(kind, value) DO UPDATE SET
                reason = excluded.reason,
                created_at = excluded.created_at
            """,
            (kind, value[:255], reason.strip()[:500] or None, created_at),
        )
        if kind == "session_id":
            connection.execute(
                "UPDATE conversations SET status = 'blocked' WHERE session_id = ?",
                (value,),
            )
        else:
            connection.execute(
                "UPDATE conversations SET status = 'blocked' WHERE client_ip = ?",
                (value,),
            )
        row = connection.execute(
            "SELECT * FROM blacklist WHERE kind = ? AND value = ?",
            (kind, value),
        ).fetchone()
        connection.commit()
    return dict(row)


def remove_blacklist(item_id: int) -> bool:
    init_database()
    with DB_LOCK, closing(connect()) as connection:
        cursor = connection.execute("DELETE FROM blacklist WHERE id = ?", (item_id,))
        connection.commit()
    return cursor.rowcount > 0


def is_blacklisted(session_id: str = "", client_ip: str = "") -> dict[str, Any] | None:
    init_database()
    clauses = []
    params: list[Any] = []
    if session_id:
        clauses.append("(kind = 'session_id' AND value = ?)")
        params.append(session_id)
    if client_ip:
        clauses.append("(kind = 'client_ip' AND value = ?)")
        params.append(client_ip)
    if not clauses:
        return None
    with closing(connect()) as connection:
        row = connection.execute(
            f"SELECT * FROM blacklist WHERE {' OR '.join(clauses)} ORDER BY id LIMIT 1",
            params,
        ).fetchone()
    return dict(row) if row else None
