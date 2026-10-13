"""Acquisition pools and human-operated growth workflow; no outbound messaging."""
import csv
import io
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import Field, ValidationError, model_validator

from backend.channel_service import (
    Profile, StrictModel, database, local_only, now, put, records, require, validate_products,
)

router = APIRouter(dependencies=[Depends(local_only)])
Role = Literal["manufacturer", "dealer", "customer"]
Stage = Literal["发现", "已核实", "已触达", "有效意向", "培育", "关闭"]
POLICY = Literal["待核实", "可业务联系", "拒绝联系"]


def normalized(value):
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", value)).casefold()


class Campaign(StrictModel):
    name: str = Field(min_length=1, max_length=160)
    role: Role
    channel: str = Field(min_length=1, max_length=120)
    owner: str = Field(min_length=1, max_length=80)
    start_date: date
    end_date: date
    target_qualified: int = Field(ge=1, le=100000)
    budget: float = Field(default=0, ge=0, le=100000000, allow_inf_nan=False)
    actual_cost: float = Field(default=0, ge=0, le=100000000, allow_inf_nan=False)
    proposition: str = Field(min_length=1, max_length=2000)
    active: bool = True

    @model_validator(mode="after")
    def dates(self):
        if self.end_date < self.start_date:
            raise ValueError("结束日期不能早于开始日期")
        return self


class Prospect(StrictModel):
    role: Role
    name: str = Field(min_length=1, max_length=160)
    source: str = Field(min_length=1, max_length=120)
    source_reference: str = Field(min_length=1, max_length=2000)
    campaign_id: str = ""
    referrer_id: str = ""
    owner: str = Field(min_length=1, max_length=80)
    regions: list[str] = Field(default_factory=list, max_length=80)
    customer_types: list[str] = Field(default_factory=list, max_length=80)
    scenarios: list[str] = Field(default_factory=list, max_length=80)
    capabilities: list[str] = Field(default_factory=list, max_length=80)
    product_ids: list[str] = Field(default_factory=list, max_length=1000)
    contact: str = Field(default="", max_length=200)
    contact_policy: POLICY = "待核实"
    evidence: str = Field(default="", max_length=2000)
    fit_note: str = Field(default="", max_length=2000)
    notes: str = Field(default="", max_length=4000)


class Progress(StrictModel):
    stage: Stage
    note: str = Field(min_length=1, max_length=2000)


class Task(StrictModel):
    prospect_id: str
    action: str = Field(min_length=1, max_length=400)
    owner: str = Field(min_length=1, max_length=80)
    due_date: date
    kind: Literal["资料核实", "业务联系", "内部准备"] = "资料核实"


class CompleteTask(StrictModel):
    outcome: str = Field(min_length=1, max_length=2000)


class Conversion(StrictModel):
    existing_profile_id: str = ""


class CSVImport(StrictModel):
    csv_text: str = Field(min_length=1, max_length=500000)
    commit: bool = False
    campaign_id: str = ""


def validate_prospect(conn, body, key=None):
    if not normalized(body.name):
        raise HTTPException(422, "请填写有效机构名称")
    validate_products(body.product_ids)
    # Reuse the established profile tag validation and normalization.
    cleaned = Profile(**{k: v for k, v in body.model_dump().items() if k in Profile.model_fields})
    if body.campaign_id:
        campaign = require(conn, "growth_campaign", body.campaign_id)
        if campaign["role"] != body.role or (not campaign["active"] and key is None):
            raise HTTPException(422, "拓展项目的主体类型不一致或项目已停用")
    if body.referrer_id:
        referrer = require(conn, "profile", body.referrer_id)
        if not referrer["active"]:
            raise HTTPException(422, "转介绍主体已停用")
    if any(p["id"] != key and p["role"] == body.role and normalized(p["name"]) == normalized(body.name) for p in records(conn, "growth_prospect")):
        raise HTTPException(409, "该主体已在线索池中，请搜索并更新原记录")
    if body.contact_policy == "可业务联系" and (not body.contact or not body.evidence):
        raise HTTPException(422, "可业务联系需要业务联系方式及核实依据")
    result = body.model_dump()
    for name in ["regions", "customer_types", "scenarios", "capabilities", "product_ids"]:
        result[name] = getattr(cleaned, name)
    return result


def new_prospect(conn, body):
    result = validate_prospect(conn, body)
    return put(conn, "growth_prospect", dict(result, id=str(uuid4()), stage="关闭" if body.contact_policy == "拒绝联系" else "发现", created_at=now(), updated_at=now(), events=[], qualified_at=None, contacted_at=None, engaged_at=None, converted_at=None, profile_id=""))


def close_tasks(conn, prospect_id):
    for task in records(conn, "growth_task"):
        if task["prospect_id"] == prospect_id and task["status"] == "待办":
            task.update(status="取消", completed_at=now(), outcome="线索关闭、入池或拒绝联系，取消待办")
            put(conn, "growth_task", task)


def today():
    return datetime.now(timezone(timedelta(hours=8))).date().isoformat()


@router.get("/growth", include_in_schema=False)
def page():
    return FileResponse(Path(__file__).resolve().parent.parent / "frontend" / "growth.html")


@router.get("/api/growth/workspace")
def workspace():
    with database() as conn:
        prospects = records(conn, "growth_prospect")
        campaigns = records(conn, "growth_campaign")
        tasks = records(conn, "growth_task")
        profiles = records(conn, "profile")
        demands = records(conn, "demand")
        opportunities = records(conn, "opportunity")
        for p in prospects:
            p["existing_profile_id"] = next((x["id"] for x in profiles if x["role"] == p["role"] and normalized(x["name"]) == normalized(p["name"])), "")
        for task in tasks:
            task["overdue"] = task["status"] == "待办" and task["due_date"] < today()
        def metrics(items):
            total = len(items)
            qualified = sum(bool(p["qualified_at"]) for p in items)
            converted = sum(bool(p["converted_at"]) for p in items)
            def activated(p):
                if not p["converted_at"]:
                    return False
                if p["role"] == "customer" and any(d["customer_id"] == p["profile_id"] and d["created_at"] >= p["converted_at"] for d in demands):
                    return True
                return any(p["profile_id"] in {o["manufacturer_id"], o["dealer_id"], o["customer_id"]} and any(e["at"] >= p["converted_at"] and e["stage"] not in {"待对接", "已关闭"} for e in o["events"]) for o in opportunities)
            return {"discovered": total, "qualified": qualified, "contacted": sum(bool(p["contacted_at"]) for p in items), "engaged": sum(bool(p["engaged_at"]) for p in items), "converted": converted, "created_profiles": sum(p.get("conversion_kind") == "new" for p in items), "activated": sum(activated(p) for p in items), "qualified_rate": qualified / total if total else None, "conversion_rate": converted / qualified if qualified else None}
        for campaign in campaigns:
            related = [p for p in prospects if p["campaign_id"] == campaign["id"]]
            campaign["metrics"] = metrics(related)
            campaign["metrics"]["cost_per_qualified"] = campaign["actual_cost"] / campaign["metrics"]["qualified"] if campaign["metrics"]["qualified"] else None
        return {"prospects": prospects, "campaigns": campaigns, "tasks": tasks, "metrics": metrics(prospects), "by_role": {role: metrics([p for p in prospects if p["role"] == role]) for role in ["manufacturer", "dealer", "customer"]}, "by_source": [{"source": source, **metrics([p for p in prospects if p["source"] == source])} for source in sorted({p["source"] for p in prospects})], "today": today()}


@router.post("/api/growth/campaigns", status_code=201)
def create_campaign(body: Campaign):
    with database() as conn:
        return put(conn, "growth_campaign", dict(body.model_dump(mode="json"), id=str(uuid4()), created_at=now()))


@router.put("/api/growth/campaigns/{key}")
def edit_campaign(key: str, body: Campaign):
    with database() as conn:
        old = require(conn, "growth_campaign", key)
        if old["role"] != body.role:
            raise HTTPException(409, "项目主体类型不能修改")
        return put(conn, "growth_campaign", dict(body.model_dump(mode="json"), id=key, created_at=old["created_at"], updated_at=now()))


@router.post("/api/growth/prospects", status_code=201)
def create_prospect(body: Prospect):
    with database() as conn:
        return new_prospect(conn, body)


@router.put("/api/growth/prospects/{key}")
def edit_prospect(key: str, body: Prospect):
    with database() as conn:
        old = require(conn, "growth_prospect", key)
        if old["converted_at"]:
            raise HTTPException(409, "已转入正式档案，请在渠道协作工作台维护")
        if old["role"] != body.role:
            raise HTTPException(409, "线索主体类型不能变更")
        for field in ["source", "source_reference", "campaign_id", "referrer_id"]:
            if old[field] != getattr(body, field):
                raise HTTPException(409, "首次来源归因不可改写，补充来源请记入备注")
        result = validate_prospect(conn, body, key)
        old["events"].append({"at": now(), "stage": old["stage"], "note": "更新画像资料", "previous": {k: old[k] for k in result}})
        old.update(result, updated_at=now())
        if body.contact_policy == "拒绝联系":
            old.update(stage="关闭")
            close_tasks(conn, key)
        return put(conn, "growth_prospect", old)


TRANSITIONS = {"发现": {"已核实", "关闭"}, "已核实": {"已触达", "培育", "关闭"}, "已触达": {"有效意向", "培育", "关闭"}, "有效意向": {"培育", "关闭"}, "培育": {"已核实", "已触达", "关闭"}, "关闭": set()}


@router.post("/api/growth/prospects/{key}/progress")
def progress(key: str, body: Progress):
    with database() as conn:
        p = require(conn, "growth_prospect", key)
        if p["converted_at"] or p["stage"] == "关闭":
            raise HTTPException(409, "已入池或关闭的线索不能推进")
        if body.stage != p["stage"] and body.stage not in TRANSITIONS[p["stage"]]:
            raise HTTPException(409, "请先完成前置核实与触达步骤")
        if body.stage in {"已核实", "已触达", "有效意向"} and (not p["evidence"] or not p["fit_note"] or not p["regions"]):
            raise HTTPException(422, "请补充核实依据、业务匹配理由和区域")
        if body.stage in {"已触达", "有效意向"} and (p["contact_policy"] != "可业务联系" or not p["contact"]):
            raise HTTPException(422, "业务联系状态及联系方式尚未核实")
        p["events"].append({"at": now(), "stage": body.stage, "note": body.note})
        for stage, field in [("已核实", "qualified_at"), ("已触达", "contacted_at"), ("有效意向", "engaged_at")]:
            if body.stage == stage and not p[field]:
                p[field] = now()
        p.update(stage=body.stage, updated_at=now())
        if body.stage == "关闭":
            close_tasks(conn, key)
        return put(conn, "growth_prospect", p)


@router.post("/api/growth/prospects/{key}/convert")
def convert(key: str, body: Conversion):
    with database() as conn:
        p = require(conn, "growth_prospect", key)
        if p["converted_at"]:
            return {"profile_id": p["profile_id"], "already_converted": True}
        if p["stage"] != "有效意向" or p["contact_policy"] != "可业务联系" or not p["evidence"] or not p["fit_note"] or not p["regions"]:
            raise HTTPException(409, "先完成资料核实、触达并确认有效意向")
        if not p["customer_types"] or not p["scenarios"]:
            raise HTTPException(422, "入池前须补充客户类型与应用场景")
        if p["role"] in {"manufacturer", "dealer"} and not (p["product_ids"] or p["capabilities"]):
            raise HTTPException(422, "厂家/经销商须补充关联产品或待引入产品的能力说明")
        matches = [x for x in records(conn, "profile") if x["role"] == p["role"] and normalized(x["name"]) == normalized(p["name"])]
        if body.existing_profile_id:
            profile = require(conn, "profile", body.existing_profile_id)
            if not profile["active"] or profile not in matches:
                raise HTTPException(409, "仅可关联同角色同名且启用的已有档案")
        elif matches:
            raise HTTPException(409, "已有同名档案，请选择关联已有档案，不能重复创建")
        else:
            validate_products(p["product_ids"])
            profile_body = Profile(**{k: v for k, v in p.items() if k in Profile.model_fields})
            profile = dict(profile_body.model_dump(), id=str(uuid4()), created_at=now(), updated_at=now(), acquisition_prospect_id=key)
            put(conn, "profile", profile)
        p.update(stage="已入池", profile_id=profile["id"], converted_at=now(), updated_at=now(), conversion_kind="existing" if body.existing_profile_id else "new")
        p["events"].append({"at": now(), "stage": "已入池", "note": "人工确认转入正式档案"})
        close_tasks(conn, key)
        put(conn, "growth_prospect", p)
        return {"profile_id": profile["id"], "already_converted": False}


@router.post("/api/growth/tasks", status_code=201)
def create_task(body: Task):
    with database() as conn:
        p = require(conn, "growth_prospect", body.prospect_id)
        if p["stage"] in {"已入池", "关闭"} or p["contact_policy"] == "拒绝联系":
            raise HTTPException(409, "该线索不接受新增拓展任务")
        if body.kind == "业务联系" and (p["contact_policy"] != "可业务联系" or not p["contact"]):
            raise HTTPException(422, "请先核实业务联系条件")
        return put(conn, "growth_task", dict(body.model_dump(mode="json"), id=str(uuid4()), status="待办", created_at=now(), outcome=""))


@router.post("/api/growth/tasks/{key}/complete")
def complete_task(key: str, body: CompleteTask):
    with database() as conn:
        task = require(conn, "growth_task", key)
        if task["status"] != "待办":
            raise HTTPException(409, "任务已完成或取消")
        task.update(status="完成", outcome=body.outcome, completed_at=now())
        put(conn, "growth_task", task)
        return task


CSV_FIELDS = ["role", "name", "source", "source_reference", "owner", "regions", "customer_types", "scenarios", "contact", "notes"]


@router.get("/api/growth/import-template")
def template():
    return Response("\ufeff" + ",".join(CSV_FIELDS) + "\r\n", media_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="growth_import_template.csv"'})


@router.post("/api/growth/import")
def import_prospects(body: CSVImport):
    reader = csv.DictReader(io.StringIO(body.csv_text.lstrip("\ufeff")), strict=True)
    try:
        fields = reader.fieldnames
        rows = list(reader)
    except csv.Error as exc:
        raise HTTPException(422, f"CSV 格式错误：{exc}") from exc
    if not fields or set(fields) != set(CSV_FIELDS) or len(fields) != len(CSV_FIELDS):
        raise HTTPException(422, "请使用导入模板的完整列名")
    results, prepared, seen = [], [], set()
    with database() as conn:
        for number, row in enumerate(rows, 2):
            if number > 201:
                raise HTTPException(422, "单批最多 200 条，请拆分文件")
            try:
                if None in row or any(v is None for v in row.values()):
                    raise ValueError("列数不一致")
                for key in ["regions", "customer_types", "scenarios"]:
                    row[key] = [x.strip() for x in re.split(r"[;；]", row[key]) if x.strip()]
                prospect = Prospect(**row, campaign_id=body.campaign_id)
                fingerprint = (prospect.role, normalized(prospect.name))
                if fingerprint in seen:
                    raise ValueError("本批次重复机构")
                validate_prospect(conn, prospect)
                seen.add(fingerprint)
                prepared.append(prospect)
                results.append({"row": number, "name": prospect.name, "ok": True, "error": ""})
            except (ValidationError, ValueError, HTTPException) as exc:
                results.append({"row": number, "name": str(row.get("name", "")), "ok": False, "error": str(exc.detail) if isinstance(exc, HTTPException) else str(exc)})
        errors = sum(not r["ok"] for r in results)
        if not results:
            raise HTTPException(422, "导入文件没有数据行")
        committed = body.commit and not errors
        if committed:
            for prospect in prepared:
                new_prospect(conn, prospect)
        return {"rows": results, "errors": errors, "committed": committed, "imported": len(prepared) if committed else 0}
