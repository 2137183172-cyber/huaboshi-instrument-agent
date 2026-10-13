"""Local channel workspace. Deterministic matching; no customer data sent to LLMs."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.config import app_config
from backend.knowledge_catalog import load_knowledge_products


def local_only(request: Request):
    if not request.client or request.client.host not in {"127.0.0.1", "::1"}:
        raise HTTPException(403, "渠道工作台目前仅开放本机访问")
    if request.url.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise HTTPException(403, "请使用本机地址打开渠道工作台")
    # Reject cross-origin browser access even though the legacy chat API allows CORS.
    origin = request.headers.get("origin")
    if origin and origin != str(request.base_url).rstrip("/"):
        raise HTTPException(403, "请从本机工作台页面访问")
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "不允许跨站访问")


router = APIRouter(dependencies=[Depends(local_only)])


@contextmanager
def database():
    path = Path(app_config()["data_dir"]) / "channel" / "workspace.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS records (kind TEXT NOT NULL, id TEXT PRIMARY KEY, body TEXT NOT NULL)")
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def records(conn, kind):
    return [json.loads(r["body"]) for r in conn.execute("SELECT body FROM records WHERE kind=? ORDER BY rowid DESC", (kind,))]


def require(conn, kind, key):
    row = conn.execute("SELECT body FROM records WHERE kind=? AND id=?", (kind, key)).fetchone()
    if not row:
        raise HTTPException(404, "关联记录不存在，请刷新后重试")
    return json.loads(row["body"])


def put(conn, kind, data):
    conn.execute("INSERT INTO records VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body", (kind, data["id"], json.dumps(data, ensure_ascii=False)))
    return data


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Profile(StrictModel):
    role: Literal["manufacturer", "dealer", "customer"]
    name: str = Field(min_length=1, max_length=160)
    regions: list[str] = Field(default_factory=list, max_length=80)
    customer_types: list[str] = Field(default_factory=list, max_length=80)
    scenarios: list[str] = Field(default_factory=list, max_length=80)
    capabilities: list[str] = Field(default_factory=list, max_length=80)
    product_ids: list[str] = Field(default_factory=list, max_length=1000)
    customer_ids: list[str] = Field(default_factory=list, max_length=1000)
    contact: str = Field(default="", max_length=200)
    owner: str = Field(default="", max_length=80)
    evidence: str = Field(default="", max_length=2000)
    notes: str = Field(default="", max_length=4000)
    active: bool = True
    product_lines: list[str] = Field(default_factory=list, max_length=80)
    decision_role: str = Field(default="", max_length=200)
    sales_team: str = Field(default="", max_length=400)
    existing_equipment: str = Field(default="", max_length=2000)
    contact_policy: Literal["待核实", "可业务联系", "拒绝联系"] = "待核实"

    @field_validator("regions", "customer_types", "scenarios", "capabilities", "product_ids", "customer_ids", "product_lines")
    @classmethod
    def clean_lists(cls, values):
        if any(len(x) > 200 for x in values):
            raise ValueError("单个标签过长")
        return list(dict.fromkeys(x.strip() for x in values if x.strip()))


class Authorization(StrictModel):
    manufacturer_id: str
    dealer_id: str
    product_ids: list[str] = Field(min_length=1, max_length=1000)
    status: Literal["pending", "confirmed", "revoked"] = "pending"
    evidence: str = Field(default="", max_length=2000)


class Demand(StrictModel):
    customer_id: str
    title: str = Field(min_length=1, max_length=160)
    region: str = Field(min_length=1, max_length=100)
    customer_type: str = Field(min_length=1, max_length=100)
    scenario: str = Field(default="", max_length=200)
    product_ids: list[str] = Field(min_length=1, max_length=1000)
    requirement: str = Field(default="", max_length=4000)
    owner: str = Field(default="", max_length=100)


class Assignment(StrictModel):
    demand_id: str
    dealer_id: str
    manufacturer_id: str


class Followup(StrictModel):
    actor_id: str
    stage: Literal["待对接", "需求确认", "方案选型", "演示验证", "商务报价", "交付实施", "售后服务", "已关闭"]
    note: str = Field(min_length=1, max_length=2000)
    next_action: str = Field(default="", max_length=1000)


def catalog():
    return {str(p["record_id"]): p for p in load_knowledge_products() if p.get("record_id")}


def validate_products(ids):
    if not set(ids) <= catalog().keys():
        raise HTTPException(422, "包含不存在的产品，请从当前产品库选择")


def participant(conn, key, role):
    item = require(conn, "profile", key)
    if item["role"] != role or not item["active"]:
        raise HTTPException(422, "关联主体角色不符或已停用")
    return item


@router.get("/channels", include_in_schema=False)
def page():
    return FileResponse(Path(__file__).resolve().parent.parent / "frontend" / "channels.html")


@router.get("/api/channels/workspace")
def workspace():
    with database() as conn:
        data = {k: records(conn, kind) for k, kind in [("profiles", "profile"), ("demands", "demand"), ("authorizations", "authorization"), ("opportunities", "opportunity")]}
    data["products"] = [{"id": key, "name": p["name"], "brand_vendor": p["brand_vendor"], "category": p["category"]} for key, p in catalog().items()]
    return data


def save_profile(body, key=None):
    validate_products(body.product_ids)
    if body.contact_policy == "可业务联系" and (not body.contact or not body.evidence):
        raise HTTPException(422, "可业务联系需填写联系方式和核实依据")
    with database() as conn:
        previous = require(conn, "profile", key) if key else None
        if previous and previous["role"] != body.role:
            raise HTTPException(409, "已有主体不能变更角色，请另建档案")
        if body.role != "dealer" and body.customer_ids:
            raise HTTPException(422, "实际客户关联仅适用于经销商")
        for cid in body.customer_ids:
            participant(conn, cid, "customer")
        if any(p["id"] != key and p["role"] == body.role and p["name"].casefold() == body.name.casefold() for p in records(conn, "profile")):
            raise HTTPException(409, "同角色主体名称已存在")
        result = dict(body.model_dump(), id=key or str(uuid4()), created_at=previous["created_at"] if previous else now(), updated_at=now())
        return put(conn, "profile", result)


@router.post("/api/channels/profiles", status_code=201)
def create_profile(body: Profile):
    return save_profile(body)


@router.put("/api/channels/profiles/{key}")
def update_profile(key: str, body: Profile):
    return save_profile(body, key)


@router.post("/api/channels/authorizations", status_code=201)
def authorization(body: Authorization):
    validate_products(body.product_ids)
    if body.status == "confirmed" and not body.evidence:
        raise HTTPException(422, "确认授权必须填写核实依据及适用范围/有效期")
    with database() as conn:
        maker = participant(conn, body.manufacturer_id, "manufacturer")
        dealer = participant(conn, body.dealer_id, "dealer")
        if not set(body.product_ids) <= set(maker["product_ids"]) & set(dealer["product_ids"]):
            raise HTTPException(422, "授权产品须同时关联至厂家与经销商")
        # Each pair has one current declaration; preserve past declarations for review.
        previous = next((a for a in records(conn, "authorization") if a["manufacturer_id"] == body.manufacturer_id and a["dealer_id"] == body.dealer_id), None)
        history = previous.get("history", []) + [{"at": previous["updated_at"], "status": previous["status"], "evidence": previous["evidence"], "product_ids": previous["product_ids"]}] if previous else []
        return put(conn, "authorization", dict(body.model_dump(), id=previous["id"] if previous else str(uuid4()), updated_at=now(), history=history))


@router.post("/api/channels/demands", status_code=201)
def create_demand(body: Demand):
    validate_products(body.product_ids)
    with database() as conn:
        participant(conn, body.customer_id, "customer")
        return put(conn, "demand", dict(body.model_dump(), id=str(uuid4()), created_at=now()))


def matches(conn, demand):
    candidates = []
    for dealer in records(conn, "profile"):
        if dealer["role"] != "dealer" or not dealer["active"]:
            continue
        overlap = sorted(set(dealer["product_ids"]) & set(demand["product_ids"]))
        if not overlap or demand["region"] not in dealer["regions"] or demand["customer_type"] not in dealer["customer_types"]:
            continue
        missing = sorted(set(demand["product_ids"]) - set(overlap))
        reasons = [f"覆盖区域：{demand['region']}", f"服务客户类型：{demand['customer_type']}", "推广产品与需求产品存在交集"]
        score = round(60 * len(overlap) / len(set(demand["product_ids"]))) + 20
        if demand["scenario"] and demand["scenario"] in dealer["scenarios"]:
            score += 10
            reasons.append("已登记对应应用场景经验")
        if demand["customer_id"] in dealer["customer_ids"]:
            score += 10
            reasons.append("已登记该终端客户接触关系")
        candidates.append({"dealer_id": dealer["id"], "name": dealer["name"], "score": score, "reasons": reasons, "product_ids": overlap, "missing_product_ids": missing, "capabilities": dealer["capabilities"], "notice": "规则匹配分，不是成交概率；推广登记不代表厂家授权。"})
    return sorted(candidates, key=lambda x: (-x["score"], x["name"]))


@router.get("/api/channels/demands/{key}/matches")
def recommend(key: str):
    with database() as conn:
        demand = require(conn, "demand", key)
        participant(conn, demand["customer_id"], "customer")
        return {"items": matches(conn, demand), "rule": "区域和客户类型须精确匹配，至少覆盖一个需求产品；信息不足时不随机推荐。"}


@router.post("/api/channels/opportunities", status_code=201)
def assign(body: Assignment):
    with database() as conn:
        demand = require(conn, "demand", body.demand_id)
        participant(conn, demand["customer_id"], "customer")
        maker = participant(conn, body.manufacturer_id, "manufacturer")
        dealer = participant(conn, body.dealer_id, "dealer")
        if body.dealer_id not in {x["dealer_id"] for x in matches(conn, demand)}:
            raise HTTPException(422, "该经销商未满足需求匹配条件")
        products = sorted(set(demand["product_ids"]) & set(maker["product_ids"]) & set(dealer["product_ids"]))
        if not products:
            raise HTTPException(422, "厂家、经销商与需求没有共同产品")
        if any(o["demand_id"] == body.demand_id and o["dealer_id"] == body.dealer_id and o["manufacturer_id"] == body.manufacturer_id and o["stage"] != "已关闭" for o in records(conn, "opportunity")):
            raise HTTPException(409, "该三方协作已经建立")
        return put(conn, "opportunity", dict(body.model_dump(), id=str(uuid4()), customer_id=demand["customer_id"], product_ids=products, stage="待对接", next_action="核实厂家授权、区域权限及客户需求", created_at=now(), events=[]))


STAGES = ["待对接", "需求确认", "方案选型", "演示验证", "商务报价", "交付实施", "售后服务", "已关闭"]


@router.post("/api/channels/opportunities/{key}/followups")
def followup(key: str, body: Followup):
    with database() as conn:
        item = require(conn, "opportunity", key)
        if body.actor_id not in {item["manufacturer_id"], item["dealer_id"], item["customer_id"]}:
            raise HTTPException(422, "跟进主体必须是该协作的三方之一")
        actor = require(conn, "profile", body.actor_id)
        if not actor["active"]:
            raise HTTPException(422, "跟进主体已停用")
        if item["stage"] == "已关闭":
            raise HTTPException(409, "已关闭协作不可继续推进")
        old, new = STAGES.index(item["stage"]), STAGES.index(body.stage)
        if body.stage != "已关闭" and new not in {old, old + 1}:
            raise HTTPException(409, "请按阶段推进，或在当前阶段补充记录")
        if body.stage in {"商务报价", "交付实施", "售后服务"}:
            verified = any(a["manufacturer_id"] == item["manufacturer_id"] and a["dealer_id"] == item["dealer_id"] and a["status"] == "confirmed" and set(item["product_ids"]) <= set(a["product_ids"]) for a in records(conn, "authorization"))
            if not verified:
                raise HTTPException(409, "进入商务阶段前请登记对应产品的厂家授权核实依据")
        item["events"].append(dict(body.model_dump(), at=now(), actor_name=actor["name"]))
        item.update(stage=body.stage, next_action=body.next_action, updated_at=now())
        return put(conn, "opportunity", item)
