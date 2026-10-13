import os
import secrets
from html import escape
from time import perf_counter
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from backend.config import app_config
from backend.channel_service import router as channel_router
from backend.growth_service import router as growth_router
from backend.precision_service import router as precision_router
from backend.product_publication import public_payload, public_chat_payload
from backend.product_brochure import router as product_brochure_router
from backend.scenario_continuity import build_scenario_equipment_result, build_scenario_scope_result
from backend.document_export import router as document_export_router
from backend.scenario_catalog import router as scenario_catalog_router
from backend.scenario_catalog import catalog_chat_result
from backend.scenario_selection import selection_result
from backend.published_scenarios import stage_result
from backend.email_service import send_lead_email
from backend.graph_tools import check_neo4j_connection
from backend.graph_workflow import run_graph_workflow
from backend.interaction_service import (
    apply_conversation_guidance,
    build_acknowledgement_result,
)
from backend.topic_service import normalize_customer_followups
from backend.lead_store import get_lead_by_id, save_lead
from backend.llm_service import check_llm_connection, model_config
from backend import speech_service
from backend.local_catalog import get_local_device_detail, search_local_devices
from backend.middleware import SimpleRateLimitMiddleware
from backend.session_memory import (
    build_model_context,
    clear_session_context,
    get_session_context,
    is_acknowledgement_query,
    is_context_switch_query,
    resolve_query_with_context,
    reset_active_context,
    restore_session_context,
    update_session_context,
)
from backend.wecom_service import send_wecom_lead
from backend.conversation_store import (
    china_now,
    conversation_stats,
    get_conversation,
    list_conversations,
    mark_conversation_read,
    record_message,
)

CONFIG = app_config()

app = FastAPI(
    title="华博士",
    debug=CONFIG["debug"],
    docs_url="/docs" if CONFIG["app_env"] != "production" else None,
    redoc_url="/redoc" if CONFIG["app_env"] != "production" else None,
)

if CONFIG["allowed_hosts"]:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=CONFIG["allowed_hosts"])

if CONFIG["rate_limit_enabled"]:
    app.add_middleware(
        SimpleRateLimitMiddleware,
        limit_per_minute=CONFIG["rate_limit_per_minute"],
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=CONFIG["cors_origins"],
    allow_credentials="*" not in CONFIG["cors_origins"],
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND = Path(__file__).resolve().parent.parent / "frontend" / "index.html"
ADMIN_FRONTEND = Path(__file__).resolve().parent.parent / "frontend" / "admin.html"
ASSETS = Path(__file__).resolve().parent.parent / "frontend" / "assets"

app.mount("/assets", StaticFiles(directory=ASSETS), name="assets")
app.include_router(document_export_router)
app.include_router(channel_router)
app.include_router(growth_router)
app.include_router(precision_router)
app.include_router(product_brochure_router)
app.include_router(scenario_catalog_router)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    session_id: str = Field(min_length=1, max_length=120)
    action: str | None = Field(default=None, max_length=60)
    action_value: str | None = Field(default=None, max_length=240)


def resolve_action_message(
    message: str,
    session_id: str,
    action: str | None,
    action_value: str | None,
) -> str:
    """Turn UI actions into explicit queries while keeping text requests compatible."""
    action = (action or "").strip()
    value = (action_value or "").strip()
    text = (message or "").strip()
    context = get_session_context(session_id)
    topic = str(context.get("topic_title") or "").strip()
    scenario = str(context.get("scenario_title") or "").strip()
    candidates = context.get("candidate_devices") or context.get("last_devices") or []

    if action == "select_product" and value:
        # Keep the user-facing question, but anchor it to the clicked product.
        if value in text:
            return text
        if any(term in text for term in ("样本", "应用", "流程", "参数", "优势", "原理", "兼容", "报价")):
            return f"{value}{text}"
        return f"介绍一下{value}"
    if action == "select_stage" and value:
        if scenario:
            return f"{scenario}：{value}环节需要哪些设备"
        if topic:
            return f"{topic}：我想先看{value}"
    if action == "compare_candidates":
        names = value or "、".join(str(item) for item in candidates[:3] if item)
        if names:
            parts = [item.strip() for item in names.replace("，", "、").split("、") if item.strip()]
            if len(parts) >= 2:
                return f"对比：{parts[0]} 和 {parts[1]} 有什么区别？"
        return "这几个设备有什么区别？"
    if action == "more_candidates":
        return text or "再推荐几个不同的替代产品"
    if action == "adjust_scenario" and scenario:
        return f"{scenario}：{text or '按我的样本类型和通量调整这个方案'}"
    if action == "open_scenario":
        if scenario:
            return f"{scenario}完整实施路径"
        if topic:
            return f"{topic}完整方案"
    return resolve_query_with_context(text, session_id)


class LeadRequest(BaseModel):
    product_name: str = Field(default="", max_length=160)
    name: str = Field(default="", max_length=60)
    phone: str = Field(default="", max_length=80)
    organization: str = Field(default="", max_length=120)
    requirement: str = Field(default="", max_length=1000)
    source: str = Field(default="chat", max_length=80)


ADMIN_DEFAULT_PASSWORD = secrets.token_urlsafe(32)


def require_admin(authorization: str | None = Header(default=None)) -> None:
    expected = os.getenv("ADMIN_PASSWORD", "").strip() or ADMIN_DEFAULT_PASSWORD
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token or not secrets.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="后台密码错误")


def request_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else ""


@app.get("/")
def home():
    return FileResponse(FRONTEND)


@app.get("/admin")
@app.get("/admin.html")
def admin_home():
    return FileResponse(ADMIN_FRONTEND)


def lead_detail_html(record: dict[str, object]) -> str:
    fields = [
        ("咨询产品", record.get("product_name") or "未填写"),
        ("客户姓名", record.get("name") or "未填写"),
        ("联系方式", record.get("phone") or "未填写"),
        ("单位/机构", record.get("organization") or "未填写"),
        ("需求备注", record.get("requirement") or "未填写"),
        ("提交时间", record.get("created_at") or "未填写"),
    ]
    rows = "".join(
        f"<dt>{escape(label)}</dt><dd>{escape(str(value))}</dd>"
        for label, value in fields
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>华博士 - 报单详情</title>
  <style>
    body {{ margin: 0; background: #f4f7fb; color: #172033; font-family: "Microsoft YaHei", sans-serif; }}
    main {{ max-width: 680px; margin: 32px auto; padding: 0 18px; }}
    article {{ background: #fff; border: 1px solid #e4eaf2; border-radius: 16px; overflow: hidden; box-shadow: 0 12px 32px rgba(29, 56, 92, .08); }}
    header {{ padding: 24px 26px 20px; background: linear-gradient(135deg, #eff7ff, #fff); border-bottom: 1px solid #e4eaf2; }}
    h1 {{ margin: 0; font-size: 22px; }}
    p {{ margin: 8px 0 0; color: #64748b; font-size: 14px; }}
    dl {{ margin: 0; padding: 8px 26px 18px; }}
    dt {{ margin-top: 18px; color: #64748b; font-size: 13px; }}
    dd {{ margin: 6px 0 0; white-space: pre-wrap; overflow-wrap: anywhere; font-size: 16px; line-height: 1.55; }}
  </style>
</head>
<body><main><article><header><h1>华博士 - 报单详情</h1><p>请及时联系客户跟进需求。</p></header><dl>{rows}</dl></article></main></body>
</html>"""


@app.get("/lead/{lead_id}", response_class=HTMLResponse)
def lead_detail(lead_id: str):
    record = get_lead_by_id(lead_id)
    if not record:
        raise HTTPException(status_code=404, detail="报单不存在或链接已失效")
    return HTMLResponse(lead_detail_html(record))


@app.get("/api/health")
def health(check_model: bool = False):
    neo4j_status = check_neo4j_connection()
    llm_status = check_llm_connection() if check_model else model_config()
    return {
        "ok": bool(llm_status.get("ok", llm_status.get("configured"))),
        "env": CONFIG["app_env"],
        "neo4j": neo4j_status,
        "model": llm_status,
    }


@app.post("/api/speech/transcribe")
async def transcribe_speech(request: Request):
    client_ip = request_client_ip(request)
    if not speech_service.allow_speech_request(client_ip):
        raise HTTPException(status_code=429, detail="语音识别请求过于频繁，请稍后再试")

    content_type = speech_service.normalize_audio_type(request.headers.get("content-type"))
    if content_type not in speech_service.ALLOWED_AUDIO_TYPES:
        raise HTTPException(status_code=415, detail="当前录音格式不受支持")

    declared_size = request.headers.get("content-length", "")
    if declared_size.isdigit() and int(declared_size) > speech_service.MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="录音文件过大")

    audio = bytearray()
    async for chunk in request.stream():
        audio.extend(chunk)
        if len(audio) > speech_service.MAX_AUDIO_BYTES:
            raise HTTPException(status_code=413, detail="录音文件过大")
    if not audio:
        raise HTTPException(status_code=400, detail="未收到录音内容")

    try:
        text = speech_service.transcribe_audio(bytes(audio), content_type)
    except ValueError as exc:
        if str(exc) == "speech was not recognized":
            raise HTTPException(status_code=422, detail="未识别到有效语音，请重新录制") from exc
        raise HTTPException(status_code=400, detail="录音内容无效") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="语音识别暂时不可用，请稍后再试") from exc
    return {"text": text}


@app.get("/api/suggest")
def suggest(query: str = "", limit: int = 6):
    query = (query or "").strip()
    if len(query) < 2:
        return {"items": []}

    safe_limit = max(1, min(limit, 10))
    return {
        "items": public_payload(search_local_devices(query, limit=safe_limit))
    }


@app.get("/api/products/detail")
def product_detail(name: str = "", fallback_description: str = ""):
    detail = get_local_device_detail((name or "").strip())
    if not detail:
        description = fallback_description.strip()
        return {
            "name": name.strip() or "产品介绍",
            "product_code": "",
            "brand_vendor": "",
            "origin": "",
            "overview": description or "该设备暂未收录独立产品资料，请以场景方案和厂商最终资料为准。",
            "advantages": "",
            "applications": description,
            "key_specs": [],
            "sample_types": [],
            "source": "scenario_catalog",
        }
    return public_payload(detail)


@app.post("/api/chat")
def chat(req: ChatRequest, request: Request):
    client_ip = request_client_ip(request)
    user_agent = request.headers.get("user-agent", "")[:500]
    started_at = perf_counter()
    # Restore the compact state before recording this turn, so a restart does
    # not make the first follow-up look like a brand-new conversation.
    restore_session_context(req.session_id)
    record_message(
        req.session_id,
        "user",
        req.message,
        client_ip=client_ip,
        user_agent=user_agent,
        sender_type="customer",
    )

    try:
        if is_context_switch_query(req.message):
            reset_active_context(req.session_id)
        conversation_context = build_model_context(req.session_id)
        resolved_message = resolve_action_message(
            req.message,
            req.session_id,
            req.action,
            req.action_value,
        )
        catalog_result = (selection_result(req.message, req.action, req.action_value)
                          or catalog_chat_result(req.message, req.action_value if req.action == "catalog_plan" else ""))
        reviewed_stage = stage_result(conversation_context.get('scenario_id'), req.action_value) if req.action == 'select_stage' else None
        continuity_result = None if catalog_result else (
            reviewed_stage or build_scenario_scope_result(resolved_message) or build_scenario_equipment_result(resolved_message)
        )
        if catalog_result:
            result = catalog_result
        elif continuity_result:
            result = continuity_result
        elif is_acknowledgement_query(req.message) and conversation_context.get("active_object"):
            result = build_acknowledgement_result(conversation_context)
        else:
            result = run_graph_workflow(
                resolved_message,
            )
        update_session_context(
            req.session_id,
            result,
            raw_query=req.message,
            resolved_query=resolved_message,
            action=req.action,
            action_value=req.action_value,
        )
        result = apply_conversation_guidance(result, req.session_id, req.message)
        result = public_chat_payload(result)
    except Exception as exc:
        result = {
            "intent": "error",
            "answer": "这次回答暂时没有生成成功，请稍后重试。",
            "recommended_devices": [],
            "need_more_info": [],
            "clarifying_questions": [],
            "related_questions": [],
            "generation_source": "error",
            "model_error": str(exc),
        }

    result.pop("_context_devices", None)
    result.pop("diagnostics", None)
    result = public_chat_payload(result)
    result["related_questions"] = normalize_customer_followups(
        result.get("related_questions", []),
        limit=4,
    )
    record_message(
        req.session_id,
        "assistant",
        result.get("answer", ""),
        client_ip=client_ip,
        user_agent=user_agent,
        intent=str(result.get("intent") or ""),
        generation_source=str(result.get("generation_source") or ""),
        model_name=str(result.get("model_name") or ""),
        latency_ms=round((perf_counter() - started_at) * 1000, 1),
        sender_type="assistant",
        payload=result,
        metadata={"recommended_device_count": len(result.get("recommended_devices") or [])},
    )
    return result


@app.get("/api/session/{session_id}/history")
def session_history(session_id: str):
    """Return the customer's own display transcript for page refresh recovery."""
    conversation = get_conversation(session_id)
    if not conversation:
        return {"session_id": session_id, "messages": []}

    messages = []
    for item in conversation.get("messages", []):
        if not isinstance(item, dict) or item.get("role") not in {"user", "assistant"}:
            continue
        messages.append({
            "role": item.get("role"),
            "content": item.get("content", ""),
            "created_at": item.get("created_at", ""),
            "payload": item.get("payload", {}) if item.get("role") == "assistant" else {},
        })
    return {"session_id": session_id, "messages": messages[-60:]}


@app.get("/api/admin/stats")
def admin_stats(authorization: str | None = Header(default=None)):
    require_admin(authorization)
    return conversation_stats()


@app.get("/api/admin/conversations")
def admin_conversations(
    limit: int = 100,
    offset: int = 0,
    query: str = "",
    status: str = "",
    authorization: str | None = Header(default=None),
):
    require_admin(authorization)
    return list_conversations(limit=limit, offset=offset, query=query, status=status)


@app.get("/api/admin/conversations/{session_id}")
def admin_conversation(session_id: str, authorization: str | None = Header(default=None)):
    require_admin(authorization)
    result = get_conversation(session_id)
    if not result:
        raise HTTPException(status_code=404, detail="会话不存在")
    mark_conversation_read(session_id, "agent")
    return result


@app.delete("/api/session/{session_id}")
def clear_session(session_id: str):
    cleared = clear_session_context(session_id)
    return {
        "ok": True,
        "cleared": cleared,
    }


@app.post("/api/leads")
def create_lead(req: LeadRequest):
    name = req.name.strip()
    phone = req.phone.strip()
    product_name = req.product_name.strip()

    if not name:
        raise HTTPException(status_code=400, detail="请填写姓名")
    if not phone:
        raise HTTPException(status_code=400, detail="请填写手机号或微信")

    record = {
        "lead_id": secrets.token_urlsafe(24),
        # Docker images commonly use UTC; quote leads must always show China local time.
        "created_at": china_now().replace(tzinfo=None).isoformat(timespec="seconds"),
        "product_name": product_name,
        "name": name,
        "phone": phone,
        "organization": req.organization.strip(),
        "requirement": req.requirement.strip(),
        "source": req.source.strip() or "chat",
    }

    save_lead(record)

    email_sent, email_error = send_lead_email(record)
    wecom_sent, wecom_error = send_wecom_lead(record)
    message = "已收到您的报价需求，工作人员会第一时间联系您。"
    if wecom_sent:
        message = "已收到您的报价需求，并已通知工作人员。"
    elif email_sent:
        message = "已收到您的报价需求，并已邮件通知工作人员。"

    return {
        "ok": True,
        "message": message,
        "email_sent": email_sent,
        "email_error": email_error,
        "wecom_sent": wecom_sent,
        "wecom_error": wecom_error,
    }
