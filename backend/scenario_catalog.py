from __future__ import annotations

import json
from html import escape
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from backend.scenario_names import display_title, present_result
from backend.published_scenarios import topic_items, document_item, publication, reviewed_plan, plan_html


router = APIRouter()
CATALOG_ROOT = Path(__file__).resolve().parent.parent / "data" / "scenario_catalog"
CATALOG_FILE = CATALOG_ROOT / "catalog.json"

# These catalog plans are newer presentations of topics already covered by a
# runtime plan, or by the retained revised plan immediately above them. Keep
# the source files and direct routes available, but do not show duplicate
# topics in the unified directory.
MERGED_CATALOG_IDS = {
    "six-04", "six-05", "six-06",
    "ten-01", "ten-02", "ten-03", "ten-04", "ten-05", "ten-06", "ten-08",
}


def _load_catalog() -> dict:
    try:
        data = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
        for group in data.get('groups', []):
            for item in group.get('items', []):
                old = item['title']
                item['base_title'] = old
                item['title'] = display_title(item['id'], old)
                if item.get('html'):
                    item['html'] = item['html'].replace(old, item['title'])
                if item.get('scenario_plan'):
                    item['scenario_plan'] = present_result({'scenario_plan': item['scenario_plan']})['scenario_plan']
        return data
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=503, detail="方案目录暂不可用") from exc


def _items() -> list[dict]:
    return [item for group in _load_catalog().get("groups", []) for item in group.get("items", [])] + topic_items()


def _runtime_items() -> list[dict]:
    from backend.knowledge_catalog import load_scenarios

    return [
        {
            "id": scenario.get("scenario_id", ""),
            "group": "现有运行方案",
            "title": display_title(scenario.get('scenario_id'), scenario.get('title', '')),
            "summary": "点击查看完整方案",
            "source": "runtime",
        }
        for scenario in load_scenarios()
        if scenario.get("scenario_id") and scenario.get("title") and scenario.get("steps")
    ]


def directory_items() -> list[dict]:
    runtime = _runtime_items()
    additions = [item for item in _items() if item.get("id") not in MERGED_CATALOG_IDS]
    return runtime + additions


def _public_item(item: dict, include_html: bool = False) -> dict:
    result = {key: item.get(key, "") for key in ("id", "group", "title", "summary")}
    if item.get("source") != "runtime" or document_item(item['id']):
        result["download"] = f"/api/scenario-catalog/{item['id']}/download"
    if include_html:
        reviewed = reviewed_plan(item['id'])
        result["html"] = plan_html(reviewed) if reviewed else item.get("html", "")
        result["scenario_plan"] = item.get("scenario_plan")
    return result


def catalog_chat_result(query: str, item_id: str = ""):
    item = next((value for value in _items() if
                 (item_id and value.get("id") == item_id) or
                 query.strip() == value.get("title")), None)
    if not item:
        runtime = next((value for value in _runtime_items() if
                        (item_id and value.get("id") == item_id) or
                        query.strip() == value.get("title")), None)
        if not runtime:
            return None
        from backend.scenario_service import build_scenario_result
        return present_result(build_scenario_result(runtime["id"]))
    if not item.get("scenario_plan"):
        return None
    return {
        "intent": "scenario_plan",
        "answer": f"《{item['title']}》",
        "scenario_plan": item["scenario_plan"],
        "recommended_devices": [], "related_questions": [],
        "clarifying_questions": [], "need_more_info": [],
        "generation_source": "scenario_catalog",
    }


@router.get("/api/scenario-catalog")
def scenario_catalog():
    data = _load_catalog()
    additions = [item for item in _items() if item.get("id") not in MERGED_CATALOG_IDS and not item['id'].startswith('topic-')]
    return {
        "version": publication()['version'] or data.get("version", ""),
        "groups": [
            {"id": "runtime", "title": "现有运行方案", "items": [_public_item(item) for item in _runtime_items()]},
            {"id": "new", "title": "新增方案", "items": [_public_item(item) for item in additions]},
            *([{"id": "topics", "title": "专题方案", "items": [_public_item(item) for item in topic_items()]}] if topic_items() else []),
        ],
    }


@router.get("/api/scenario-catalog/{item_id}")
def scenario_catalog_detail(item_id: str):
    item = next((value for value in _items() if value.get("id") == item_id), None)
    if not item:
        runtime = next((value for value in _runtime_items() if value.get("id") == item_id), None)
        if runtime:
            result = catalog_chat_result(runtime["title"], item_id)
            return {**_public_item(runtime), "scenario_plan": result.get("scenario_plan") if result else None}
    if not item:
        raise HTTPException(status_code=404, detail="方案不存在")
    return _public_item(item, include_html=True)


@router.get("/api/scenario-catalog/{item_id}/download")
def scenario_catalog_download(item_id: str):
    item = document_item(item_id) or next((value for value in _items() if value.get("id") == item_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="方案不存在")
    path = CATALOG_ROOT / item.get("file", "")
    if not path.is_file() or path.resolve().parent.parent != CATALOG_ROOT.resolve():
        raise HTTPException(status_code=404, detail="方案文件不存在")
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=f"{item.get('title', '华博士方案')}.docx",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/api/scenario-catalog/{item_id}/view", response_class=HTMLResponse)
def mobile_download_page(item_id: str):
    item = document_item(item_id) or next((v for v in _items() if v.get("id") == item_id), None)
    if not item:
        raise HTTPException(404, "方案不存在")
    title = escape(item['title'])
    url = f"/api/scenario-catalog/{item['id']}/download"
    return HTMLResponse(f'''<!doctype html><html lang="zh-CN"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>
body{{font:15px/1.6 system-ui,sans-serif;color:#233438;margin:0;padding:20px;max-width:680px;overflow-wrap:anywhere}}h1{{font-size:20px}}a{{display:inline-block;padding:12px 0;color:#075dba;font-weight:800}}input{{box-sizing:border-box;width:100%;padding:10px;font-size:16px}}p{{color:#52636c}}
</style></head><body><h1>{title}</h1>
<a href="{url}">下载完整方案word文档</a>
<p>文档使用系统自带黑体，未设置只读保护，可使用 Word 或 WPS 编辑。若 Word 因浏览器安全策略显示“只读”，请点击“启用编辑”；微信内无法下载时，请点击右上角“…”选择在浏览器打开。</p>
<label for="link">下载页面链接</label><input id="link" readonly aria-label="下载页面链接">
<p><a href="/">返回华博士</a></p>
<script>document.getElementById('link').value=location.href;document.getElementById('link').onclick=function(){{this.select();}};</script>
</body></html>''', headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex"})
