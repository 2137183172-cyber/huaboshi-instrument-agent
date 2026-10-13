"""Evidence-gated product-led outreach, separate from sales authorization."""
from datetime import date
from uuid import uuid4
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from backend.channel_service import (
    StrictModel, catalog, database, local_only, now, put, records, require,
)

router = APIRouter(prefix="/api/precision", dependencies=[Depends(local_only)])
CASE_ID = "meeting-20260921-DEMO-INSTRUMENT-232"


def example():
    products = [p for p in catalog().values() if p.get("product_code") == "DEMO-INSTRUMENT-232"]
    return {
        "id": CASE_ID, "title": "分子互作样本制备设备精准拓展",
        "source": "2026-09-21周会 01:53:59、02:23:52、02:42:11",
        "products": [{"id": p["record_id"], "name": p["name"], "vendor": p.get("brand_vendor", "")} for p in products],
        "workflow": ["确认样品、现有检测机型和制样痛点", "核实梯度稀释/反应体系配制需求", "核实制样设备与目标方法的适配", "交由下游互作仪检测并比较结果", "经销商联合厂家开展演示与商务跟进"],
        "boundary": "这是前置样品配制设备，不等于互作检测仪、蛋白纯化仪或分子垂钓系统。SPR/BLI/MST仅为待核验应用方向，不代表任意机型兼容，也不代表所有客户必配。",
        "data_warning": "同型号存在多个产品记录，需人工选择主记录；部分参数疑似混入SPR检测仪指标。案例不引用这些参数，不自动合并或修改PIM。",
        "checks": ["产品负责人：主记录、型号、真实功能与竞品差异", "应用负责人：具体下游机型、耗材、体积、缓冲液和方法验证", "商务负责人：合作状态、授权区域、报价和商机保护", "证据：适配报告、可核实文章或客户案例；缺失保留待核实"],
        "routes": ["产品线：寻找经营SPR/BLI/MST的经销商，核实其客户是否有重复配样痛点", "客户群：寻找分子互作研究客户，再查已有经销商客户关系，不虚构关系"],
        "outreach": "我们正在梳理分子互作检测前的配样环节。贵司客户是否存在梯度配样重复、人工工作量较大的情况？如有，可先确认现有机型和方法，再由厂家共同验证是否适用；目前不承诺全机型兼容。",
    }


class Brief(StrictModel):
    title: str = Field(min_length=1, max_length=160)
    product_id: str
    owner: str = Field(min_length=1, max_length=80)
    due_date: date
    priority: Literal["重点合作", "付费合作", "战略候选"] = "战略候选"
    product_lines: list[str] = Field(default_factory=list, max_length=30)
    target_scenarios: list[str] = Field(default_factory=list, max_length=30)
    regions: list[str] = Field(default_factory=list, max_length=30)
    benefit: str = Field(min_length=1, max_length=2000)
    boundary: str = Field(min_length=1, max_length=2000)


class Review(StrictModel):
    role: Literal["产品", "应用", "商务"]
    decision: Literal["待核实", "通过", "不通过"]
    reviewer: str = Field(min_length=1, max_length=80)
    evidence: str = Field(min_length=1, max_length=3000)
    scope: str = Field(min_length=1, max_length=2000)


class Action(StrictModel):
    target_id: str
    owner: str = Field(min_length=1, max_length=80)
    due_date: date
    kind: Literal["资料核实", "业务触达"] = "资料核实"
    next_action: str = Field(min_length=1, max_length=1000)


class Feedback(StrictModel):
    result: Literal["待执行", "已联系", "有效意向", "暂无需求", "拒绝联系", "商机关联"]
    note: str = Field(min_length=1, max_length=2000)
    next_action: str = Field(min_length=1, max_length=1000)
    due_date: date
    opportunity_id: str = ""


def target(conn, key):
    for kind in ("profile", "growth_prospect"):
        row = conn.execute("SELECT id FROM records WHERE kind=? AND id=?", (kind, key)).fetchone()
        if row:
            p = require(conn, kind, key)
            if p.get("active") is False or p.get("stage") == "关闭" or p.get("contact_policy") == "拒绝联系":
                raise HTTPException(422, "主体停用、关闭或拒绝联系")
            return p
    raise HTTPException(404, "目标主体不存在")


def ready(brief):
    return all(brief.get("reviews", {}).get(r, {}).get("decision") == "通过" for r in ("产品", "应用", "商务"))


def candidates(conn, brief):
    def overlap(a, b):
        return sorted({str(x).strip().casefold() for x in a} & {str(x).strip().casefold() for x in b})
    profiles = records(conn, "profile")
    prospects = [p for p in records(conn, "growth_prospect") if not p.get("profile_id")]
    output = []
    for p in profiles + prospects:
        if p.get("role") not in ("dealer", "customer") or p.get("active") is False or p.get("stage") == "关闭" or p.get("contact_policy") == "拒绝联系":
            continue
        lines = overlap(brief["product_lines"], p.get("product_lines", []))
        scenes = overlap(brief["target_scenarios"], p.get("scenarios", []))
        if not (lines or scenes):
            continue
        if brief["regions"] and not overlap(brief["regions"], p.get("regions", [])):
            continue
        linked = [d["name"] for d in profiles if d["role"] == "dealer" and d.get("active") and p["id"] in d.get("customer_ids", [])]
        output.append({"id": p["id"], "name": p["name"], "role": p["role"],
                       "reasons": [*( ["产品线标签：" + "、".join(lines)] if lines else []), *( ["应用标签：" + "、".join(scenes)] if scenes else [])],
                       "linked_dealers": linked, "notice": "标签命中仅为候选；需要核实实际客户、具体机型与制样痛点，不代表授权或科学适配。"})
    return output


@router.get("/workspace")
def workspace():
    with database() as conn:
        briefs = records(conn, "precision_brief")
        actions = records(conn, "precision_action")
        for b in briefs:
            b["ready"] = ready(b)
            b["candidates"] = candidates(conn, b)
        for a in actions:
            a["overdue"] = a["due_date"] < date.today().isoformat() and a["result"] not in ("拒绝联系", "暂无需求", "商机关联")
        return {"example": example(), "briefs": briefs, "actions": actions,
                "metrics": {"briefs": len(briefs), "reviewed": sum(b["ready"] for b in briefs),
                            "contacted": sum(any(e.get("result") in ("已联系", "有效意向", "商机关联") for e in a["events"]) for a in actions),
                            "opportunities": len({a["opportunity_id"] for a in actions if a.get("opportunity_id")})}}


@router.post("/briefs", status_code=201)
def create_brief(body: Brief):
    if body.product_id not in catalog():
        raise HTTPException(422, "请选择当前产品库记录")
    with database() as conn:
        if any(b["product_id"] == body.product_id and b["title"] == body.title for b in records(conn, "precision_brief")):
            raise HTTPException(409, "同产品同名拓展任务已存在")
        return put(conn, "precision_brief", dict(body.model_dump(mode="json"), id=str(uuid4()), reviews={}, events=[], created_at=now()))


@router.post("/briefs/{key}/reviews")
def review(key: str, body: Review):
    with database() as conn:
        b = require(conn, "precision_brief", key)
        event = dict(body.model_dump(), at=now())
        b["reviews"][body.role] = event
        b["events"].append(event)
        return put(conn, "precision_brief", b)


@router.post("/briefs/{key}/actions", status_code=201)
def action(key: str, body: Action):
    with database() as conn:
        b = require(conn, "precision_brief", key)
        p = target(conn, body.target_id)
        if p["id"] not in {c["id"] for c in candidates(conn, b)}:
            raise HTTPException(422, "目标不在当前候选范围，请先补充真实画像")
        if body.kind == "业务触达" and (not ready(b) or p.get("contact_policy") != "可业务联系"):
            raise HTTPException(422, "业务触达需要三方审核通过及目标可业务联系；可先建立资料核实任务")
        if any(a["brief_id"] == key and a["target_id"] == body.target_id for a in records(conn, "precision_action")):
            raise HTTPException(409, "已有该目标任务，请继续更新反馈")
        return put(conn, "precision_action", dict(body.model_dump(mode="json"), id=str(uuid4()), brief_id=key, target_name=p["name"], result="待执行", events=[], opportunity_id="", created_at=now()))


@router.post("/actions/{key}/feedback")
def feedback(key: str, body: Feedback):
    with database() as conn:
        a = require(conn, "precision_action", key)
        if a["result"] == "拒绝联系":
            raise HTTPException(409, "目标已拒绝联系，不得继续推进此任务")
        p = target(conn, a["target_id"])
        b = require(conn, "precision_brief", a["brief_id"])
        if body.result in ("已联系", "有效意向", "商机关联") and (not ready(b) or p.get("contact_policy") != "可业务联系"):
            raise HTTPException(422, "请先完成审核并核实联系条件")
        if body.result == "商机关联":
            o = require(conn, "opportunity", body.opportunity_id)
            profile_id = p.get("profile_id") or p["id"]
            if profile_id not in (o["dealer_id"], o["customer_id"]) or b["product_id"] not in o["product_ids"]:
                raise HTTPException(422, "商机主体或产品不符")
        elif body.opportunity_id:
            raise HTTPException(422, "仅商机关联阶段填写商机")
        if body.result == "拒绝联系":
            p["contact_policy"] = "拒绝联系"
            kind = "growth_prospect" if "source_reference" in p else "profile"
            put(conn, kind, p)
        a.update(body.model_dump(mode="json"))
        a["events"].append(dict(body.model_dump(mode="json"), at=now()))
        return put(conn, "precision_action", a)
