import json
import os
from dotenv import load_dotenv

from backend.llm_service import generate_json, model_config
from backend.workflow import run_workflow
from backend.product_publication import public_payload

load_dotenv()


CLARIFYING_TEMPLATES = {
    "product_direction": {
        "question": "请选择需要查看的完整方案",
        "options": [],  # Loaded from complete plans, not arbitrary categories.
    },
    "scenario_direction": {
        "question": "请选择需要查看的场景方案",
        "options": [
            "中医药研究方案",
            "临床前药物研发综合方案",
            "类器官研究综合方案",
            "空间组学/组织原位多重检测方案",
            "NGS靶向测序方案",
            "细胞治疗/细胞生产工艺方案",
            "蛋白互作筛选方案",
            "中药材/茶叶/食品品质多光谱检测方案",
        ],
    },
    "workflow_goal": {
        "question": "您希望重点完成哪个实验环节？",
        "options": ["样本前处理与分装", "核酸提取或文库制备", "细胞培养与过程监测", "成像与定量分析", "高通量筛选"],
    },
    "sample_type": {
        "question": "样本类型是什么？",
        "options": ["组织切片/FFPE样本", "培养细胞", "类器官/3D细胞模型", "血浆/血清", "DNA/RNA核酸样本", "蛋白质样本", "植物/食品样本"],
    },
    "throughput": {
        "question": "样本通量大概是多少？",
        "options": ["探索性研究（1-12个样本）", "常规批次（24-96个样本）", "高通量筛选（96个以上样本）"],
    },
    "budget": {
        "question": "预算范围是多少？",
        "options": ["30万以内", "30-50万", "50万以上", "预算不限"],
    },
    "automation": {
        "question": "自动化程度偏好是什么？",
        "options": ["优先全自动", "可接受半自动", "人工操作可接受"],
    },
}


def build_clarifying_questions(need_more_info: list[str]) -> list[dict]:
    """Return one deterministic, answerable clarification question at most."""
    text = " ".join(str(x) for x in need_more_info)
    if "设备" in text and "名称" in text:
        return []

    if any(marker in text for marker in ["场景方案", "查看的场景"]):
        key = "scenario_direction"
    elif any(marker in text for marker in ["产品方向", "仪器类别", "产品类别"]):
        key = "product_direction"
    elif "样本" in text:
        key = "sample_type"
    elif "通量" in text or "批量" in text:
        key = "throughput"
    elif "预算" in text:
        key = "budget"
    elif "自动" in text:
        key = "automation"
    else:
        key = "product_direction"

    template = CLARIFYING_TEMPLATES[key]
    if key in ('product_direction', 'scenario_direction'):
        from backend.scenario_selection import option_titles
        template = {'question':'请选择需要查看的完整方案','options':option_titles()}
    return [{
        "id": key,
        "question": template["question"],
        "options": template["options"],
    }]


def normalize_clarifying_questions(value, need_more_info: list[str]) -> list[dict]:
    # LLM-generated chips may be vague, overlapping, or not supported by the
    # catalog. The controlled templates above always carry usable answers.
    del value
    return build_clarifying_questions(need_more_info) if need_more_info else []


def trim_text(text: str, max_len: int = 260) -> str:
    text = " ".join(str(text or "").split())
    if len(text) <= max_len:
        return text
    return text[:max_len].rstrip() + "..."


def normalize_evidence_items(value) -> list[dict]:
    if not isinstance(value, list):
        return []

    normalized = []
    for item in value:
        if isinstance(item, str):
            text = trim_text(item)
            if text:
                normalized.append({"page": None, "text": text, "score": None})
            continue

        if not isinstance(item, dict):
            continue

        text = trim_text(item.get("text", ""))
        if not text:
            continue

        score = item.get("score")
        if isinstance(score, (int, float)):
            score = round(float(score), 3)
        else:
            score = None

        normalized.append({
            "page": item.get("page"),
            "text": text,
            "score": score,
            "chunk_id": item.get("chunk_id"),
        })

    return normalized[:3]


def build_device_evidence(device_name: str | None, evidence_chunks: list[dict]) -> list[dict]:
    if not device_name or not isinstance(evidence_chunks, list):
        return []

    matched = [
        item
        for item in evidence_chunks
        if isinstance(item, dict) and item.get("product_name") == device_name
    ]
    return normalize_evidence_items(matched[:2])


def build_fit_tags(item: dict) -> list[str]:
    tags = []
    for value in item.get("tasks", [])[:3] + item.get("capabilities", [])[:3]:
        if value and value not in tags:
            tags.append(value)
    return tags[:5]


def build_source_pages(evidence_items: list[dict]) -> list[int]:
    pages = []
    for item in evidence_items:
        page = item.get("page")
        if isinstance(page, int) and page not in pages:
            pages.append(page)
    return pages


def build_matched_reason(item: dict, evidence_items: list[dict]) -> str:
    if evidence_items:
        pages = build_source_pages(evidence_items)
        page_text = "、".join(str(x) for x in pages) if pages else "相关"
        return f"图谱能力与用户需求匹配，并在产品手册第 {page_text} 页找到相关证据。"

    reasons = []
    if item.get("capabilities"):
        reasons.append("能力：" + "、".join(item["capabilities"][:2]))
    if item.get("tasks"):
        reasons.append("任务：" + "、".join(item["tasks"][:2]))
    return "；".join(reasons) or "该产品在图谱候选结果中命中。"


def build_selection_notes(item: dict) -> list[str]:
    notes = ["最终选型仍需确认样本类型、通量、预算和实际配置。"]
    capabilities = " ".join(item.get("capabilities", []))
    tasks = " ".join(item.get("tasks", []))
    text = capabilities + " " + tasks

    if "单细胞" in text or "空间" in text:
        notes.append("如用于空间组学或单细胞原位检测，需确认样本制备、靶标数量和图像分析流程。")
    if "自动" in text or "高通量" in text:
        notes.append("如强调自动化或高通量，建议进一步确认批量样本数量和无人值守时长。")

    return notes[:3]


def normalize_result(result: dict) -> dict:
    if not isinstance(result, dict):
        result = {}

    result.setdefault("intent", "recommendation")
    result.setdefault("answer", "已完成初步分析。")
    result.setdefault("recommended_devices", [])
    result.setdefault("related_questions", [])
    result.setdefault("disclaimer", "内容由AI生成，仅供参考。")
    result.setdefault("generation_source", "fallback")
    result.setdefault("model_name", os.getenv("OPENAI_MODEL", "qwen-plus"))
    result.setdefault("model_error", "")

    need_more_info = result.get("need_more_info", [])
    if isinstance(need_more_info, bool):
        need_more_info = ["请补充样本类型、预算和实验目标。"] if need_more_info else []
    elif isinstance(need_more_info, str):
        need_more_info = [need_more_info]
    elif not isinstance(need_more_info, list):
        need_more_info = []
    result["need_more_info"] = need_more_info
    result["clarifying_questions"] = normalize_clarifying_questions(
        result.get("clarifying_questions"),
        need_more_info,
    )

    result["related_questions"] = normalize_related_questions(result.get("related_questions", []))

    normalized_devices = []
    for item in result.get("recommended_devices", []):
        if not isinstance(item, dict):
            continue

        normalized_devices.append({
            "name": item.get("name"),
            "product_code": item.get("product_code"),
            "industrial_code": item.get("industrial_code") or item.get("product_code"),
            "brochure_url": item.get("brochure_url", ""),
            "reasons": item.get("reasons", []) if isinstance(item.get("reasons"), list) else [],
            "capabilities": item.get("capabilities", []) if isinstance(item.get("capabilities"), list) else [],
            "tasks": item.get("tasks", []) if isinstance(item.get("tasks"), list) else [],
            "overview": item.get("overview", "") if isinstance(item.get("overview"), str) else "",
            "advantages": item.get("advantages", "") if isinstance(item.get("advantages"), str) else "",
            "applications": item.get("applications", "") if isinstance(item.get("applications"), str) else "",
            "description": item.get("description", "") if isinstance(item.get("description"), str) else "",
            "matched_reason": item.get("matched_reason", "") if isinstance(item.get("matched_reason"), str) else "",
            "fit_tags": item.get("fit_tags", []) if isinstance(item.get("fit_tags"), list) else [],
            "selection_notes": item.get("selection_notes", []) if isinstance(item.get("selection_notes"), list) else [],
            "source_pages": item.get("source_pages", []) if isinstance(item.get("source_pages"), list) else [],
            "evidence": normalize_evidence_items(item.get("evidence", [])),
        })

    result["recommended_devices"] = normalized_devices
    return result


def normalize_related_questions(value) -> list[str]:
    if not isinstance(value, list):
        return []
    blocked_fragments = (
        "请补充", "请提供", "请告诉", "请选择", "需要您", "您需要补充",
        "你的样本是什么", "样本是什么", "预算是多少",
    )
    normalized = []
    for item in value:
        text = " ".join(str(item or "").split())
        if not text:
            continue
        if any(fragment in text for fragment in blocked_fragments):
            continue
        if not text.endswith(("？", "?")) and not any(verb in text for verb in ("查看", "比较", "按", "生成", "了解")):
            text = f"了解{text}"
        if text not in normalized:
            normalized.append(text)
        if len(normalized) >= 4:
            break
    return normalized


def build_recommend_fallback(result: dict) -> dict:
    devices = []
    evidence = result.get("evidence_chunks", []) if isinstance(result.get("evidence_chunks"), list) else []
    fast_reason = result.get("fast_reason")

    for item in result.get("candidate_devices", [])[:3]:
        if not isinstance(item, dict):
            continue

        reasons = list(item.get("match_reasons", [])[:4]) if isinstance(item.get("match_reasons"), list) else []
        if item.get("capabilities"):
            reasons.append("相关能力：" + "、".join(item["capabilities"][:3]))
        if item.get("tasks"):
            reasons.append("相关任务：" + "、".join(item["tasks"][:2]))
        if item.get("automation_level") and item.get("automation_level") != "无明确自动化":
            reasons.append("自动化程度：" + item["automation_level"])
        if item.get("throughput_level") and item.get("throughput_level") != "未明确":
            reasons.append("通量特征：" + item["throughput_level"])

        description = ""
        top_evidence = [x for x in evidence if x.get("product_name") == item.get("name")]
        if top_evidence:
            description = top_evidence[0].get("text", "")

        device_evidence = build_device_evidence(item.get("name"), evidence)

        devices.append({
            "name": item.get("name"),
            "product_code": item.get("product_code"),
            "industrial_code": item.get("industrial_code") or item.get("product_code"),
            "brochure_url": item.get("brochure_url") or (f"/api/products/brochure?name={item.get('name')}" if item.get("name") else ""),
            "reasons": reasons,
            "capabilities": item.get("capabilities", []),
            "tasks": item.get("tasks", []),
            "overview": "",
            "advantages": "",
            "applications": "",
            "description": description,
            "matched_reason": build_matched_reason(item, device_evidence),
            "fit_tags": build_fit_tags(item) + [x for x in item.get("sample_types", [])[:2] if x],
            "selection_notes": build_selection_notes(item),
            "source_pages": build_source_pages(device_evidence),
            "evidence": device_evidence,
        })

    if fast_reason == "broad_capability_query":
        answer = (
            "你的需求重点是高通量、自动化和批量样本处理。"
            "这类需求不建议一开始只锁定单台设备，建议先按实验流程选择候选平台："
            "液体处理、样本前处理、文库制备或批量打断/点样。下面这些产品可以优先看。"
        )
    else:
        answer = "我先根据当前需求筛选出以下候选产品。"

    return {
        "intent": "recommend",
        "answer": answer,
        "recommended_devices": devices,
        # Candidates are already available, so show concrete products first.
        # The user can refine through the follow-up questions when needed.
        "need_more_info": [],
        "clarifying_questions": [],
        "related_questions": ["比较这些候选设备的差异", "按我的样本类型和通量继续收敛", "生成一版采购沟通清单"],
        "disclaimer": "本推荐基于当前图谱与文档检索结果生成，仅供参考，实际选型需结合样本类型、预算、实验流程和设备配置综合评估。"
    }


def build_detail_fallback(result: dict) -> dict:
    if result.get("error"):
        return {
            "intent": "detail",
            "answer": "未找到明确设备，请提供更完整的设备名称。",
            "recommended_devices": [],
            "need_more_info": ["请提供设备完整名称。"],
            "related_questions": [],
            "disclaimer": "内容由AI生成，仅供参考。"
        }

    overview = result.get("overview") or ""
    advantages = result.get("advantages") or ""
    applications = result.get("applications") or ""

    description_parts = [
        "【产品简介】" + (overview or "-"),
        "【产品优势】" + (advantages or "-"),
        "【应用场景】" + (applications or "-"),
    ]
    full_description = "\n\n".join(description_parts)
    evidence = normalize_evidence_items(result.get("evidence_chunks", []))

    device = {
        "name": result.get("name"),
        "product_code": result.get("product_code"),
        "reasons": ["该设备已在图谱和文档中命中，可查看完整详情。"],
        "capabilities": [x for x in result.get("capabilities", []) if x],
        "tasks": [x for x in result.get("tasks", []) if x],
        "overview": overview,
        "advantages": advantages,
        "applications": applications,
        "description": full_description,
        "matched_reason": "该设备名称已明确命中图谱与产品详情。",
        "fit_tags": build_fit_tags(result),
        "selection_notes": build_selection_notes(result),
        "source_pages": build_source_pages(evidence),
        "evidence": evidence,
    }

    answer = f"可以，下面是《{result.get('name')}》的产品介绍。"
    if overview:
        answer += " " + trim_text(overview, 150)

    return {
        "intent": "detail",
        "answer": answer,
        "recommended_devices": [device],
        "need_more_info": [],
        "related_questions": ["这台设备适合哪些样本？", "这台设备和其他方案有什么区别？"],
        "disclaimer": "内容由AI生成，仅供参考。"
    }


def build_compare_fallback(result: dict) -> dict:
    if result.get("error"):
        return {
            "intent": "compare",
            "answer": result.get("error", "设备对比失败，请确认设备名称。"),
            "recommended_devices": [],
            "need_more_info": ["请提供两个明确的设备名称。"],
            "related_questions": [],
            "disclaimer": "内容由AI生成，仅供参考。"
        }

    answer = f"已完成《{result.get('device_a')}》与《{result.get('device_b')}》的初步对比。"

    description = ""
    common_caps = result.get("common_capabilities", [])
    only_a_caps = result.get("only_a_capabilities", [])
    only_b_caps = result.get("only_b_capabilities", [])

    description_parts = []
    if common_caps:
        description_parts.append("【共同能力】" + "、".join(common_caps))
    if only_a_caps:
        description_parts.append(f"【{result.get('device_a')} 独有能力】" + "、".join(only_a_caps))
    if only_b_caps:
        description_parts.append(f"【{result.get('device_b')} 独有能力】" + "、".join(only_b_caps))
    description = "\n\n".join(description_parts)

    return {
        "intent": "compare",
        "answer": answer,
        "recommended_devices": [
            {
                "name": f"{result.get('device_a')} vs {result.get('device_b')}",
                "product_code": None,
                "reasons": ["已完成设备能力对比。"],
                "capabilities": common_caps,
                "tasks": [],
                "overview": "",
                "advantages": "",
                "applications": "",
                "description": description,
                "matched_reason": "已基于图谱能力关系生成对比摘要。",
                "fit_tags": common_caps[:5],
                "selection_notes": ["建议结合具体实验任务、样本类型和预算进一步确认。"],
                "source_pages": [],
                "evidence": [],
            }
        ],
        "need_more_info": [],
        "related_questions": ["这两个设备哪个更适合我的样本类型？", "这两个设备在自动化能力上有什么差异？"],
        "disclaimer": "内容由AI生成，仅供参考。"
    }


def build_similar_fallback(result: dict) -> dict:
    base_device = result.get("base_device") or "上一轮产品"
    if result.get("error"):
        return {
            "intent": "similar",
            "answer": "我没有找到上一轮可作为参照的产品，暂时无法检索类似产品。请先明确一个产品名称或实验任务。",
            "recommended_devices": [],
            "need_more_info": ["请提供要参照的产品名称或实验任务。"],
            "related_questions": ["有哪些适合NGS建库的设备？", "请介绍一下全自动基因测序文库制备系统DEMO-INSTRUMENT-078"],
            "disclaimer": "内容由AI生成，仅供参考。"
        }

    evidence = result.get("evidence_chunks", []) if isinstance(result.get("evidence_chunks"), list) else []
    devices = []
    for item in result.get("candidate_devices", [])[:3]:
        if not isinstance(item, dict):
            continue

        device_evidence = build_device_evidence(item.get("name"), evidence)
        reasons = []
        if item.get("category") and result.get("base_category") == item.get("category"):
            reasons.append(f"与{base_device}同属{item.get('category')}。")
        if item.get("tasks"):
            reasons.append("覆盖相关任务：" + "、".join(item["tasks"][:3]) + "。")
        if item.get("capabilities"):
            reasons.append("具备相关能力：" + "、".join(item["capabilities"][:3]) + "。")

        devices.append({
            "name": item.get("name"),
            "product_code": item.get("product_code"),
            "reasons": reasons[:4],
            "capabilities": item.get("capabilities", []),
            "tasks": item.get("tasks", []),
            "overview": item.get("overview", ""),
            "advantages": item.get("advantages", ""),
            "applications": item.get("applications", ""),
            "description": item.get("overview", ""),
            "matched_reason": f"基于上一轮产品《{base_device}》的类别、任务标签和能力标签检索到的相似候选。",
            "fit_tags": build_fit_tags(item),
            "selection_notes": build_selection_notes(item),
            "source_pages": build_source_pages(device_evidence),
            "evidence": device_evidence,
        })

    if not devices:
        return {
            "intent": "similar",
            "answer": f"我已按《{base_device}》检索类似产品，但当前本地目录没有找到足够相近的候选。",
            "recommended_devices": [],
            "need_more_info": ["可以补充实验任务、样本类型或自动化要求后再次检索。"],
            "related_questions": ["按NGS建库推荐设备", "按自动化样本处理推荐设备"],
            "disclaimer": "内容由AI生成，仅供参考。"
        }

    return {
        "intent": "similar",
        "answer": f"可以。基于上一轮产品《{base_device}》及当前需求，我为您筛选了以下相似或可替代的候选产品。",
        "recommended_devices": devices,
        "need_more_info": [],
        "clarifying_questions": [],
        "related_questions": ["这些产品哪个更适合RNA建库？", "这些产品是否支持高通量自动化？"],
        "disclaimer": "本推荐基于当前本地产品目录与文档检索结果生成，仅供参考，实际选型需结合样本类型、通量、预算、配置和厂商确认。"
    }


def build_default_fallback(intent: str) -> dict:
    return {
        "intent": intent,
        "answer": "已完成初步处理。",
        "recommended_devices": [],
        "need_more_info": [],
        "related_questions": [],
        "disclaimer": "内容由AI生成，仅供参考。"
    }


def build_fallback_answer(user_input: str, workflow_result: dict) -> dict:
    intent = workflow_result.get("intent", "recommendation")
    result = workflow_result.get("result", {})

    if intent == "recommend":
        return build_recommend_fallback(result)

    if intent == "detail":
        return build_detail_fallback(result)

    if intent == "compare":
        return build_compare_fallback(result)

    if intent == "similar":
        return build_similar_fallback(result)

    return build_default_fallback(intent)


def build_prompt(workflow_result: dict) -> str:
    workflow_result = public_payload(workflow_result)
    if workflow_result.get("intent") == "detail":
        return f'''
你是华博士，生物产品顾问智能体。
请只基于下面提供的设备详情结果回答用户问题，不要编造。
请严格输出一个 JSON 对象，不要输出 markdown，不要输出解释文字。

JSON字段必须是：
intent, answer, recommended_devices, need_more_info, clarifying_questions, related_questions, disclaimer

recommended_devices 必须是长度为1的列表，且包含：
name, product_code, reasons, capabilities, tasks, overview, advantages, applications, description,
matched_reason, fit_tags, selection_notes, source_pages, evidence

clarifying_questions 必须是列表；如果无需追问则输出空列表。每个元素包含：
id, question, options

evidence 必须是列表；每个元素包含 page, text, score。没有证据时输出空列表。

要求：
1. answer 要直接回应用户问题。如果用户要求“总结、生成介绍、提炼卖点、写给客户”，就按对应场景生成内容；否则用 1 到 2 句话概括这台设备。
2. overview、advantages、applications 尽量直接使用 workflow 结果里的对应字段。
3. 如果 workflow 结果里的 result.evidence_chunks 有内容，evidence 最多放 2 条，source_pages 输出对应页码列表。
4. matched_reason 要说明设备名已命中图谱，并指出有产品手册证据支撑。
5. selection_notes 输出 1 到 3 条选型注意点。
6. 如果用户询问价格、报价或费用，但 workflow 结果没有明确价格字段，必须明确回答“当前资料未提供公开价格/报价”，不要编造金额。
7. description 必须严格按以下格式输出：

【产品简介】
{{overview内容}}

【产品优势】
{{advantages内容}}

【应用场景】
{{applications内容}}

如果某一部分为空，也要保留标题。
不要把三部分合并成一段。
disclaimer 必须完整，不要截断。

用户问题：
{workflow_result.get("user_query", "")}

下面是 workflow 结果：
{json.dumps(workflow_result, ensure_ascii=False)}
'''
    return f'''
你是华博士，生物产品顾问智能体。
请只基于下面提供的 workflow 结果回答，不要编造。
如果信息不足，请明确说明，并只提出1个关键追问。
请严格输出一个 JSON 对象，不要输出 markdown，不要输出解释文字。

JSON字段必须是：
intent, answer, recommended_devices, need_more_info, clarifying_questions, related_questions, disclaimer

recommended_devices 里的每个元素必须包含：
name, product_code, reasons, capabilities, tasks, overview, advantages, applications, description,
matched_reason, fit_tags, selection_notes, source_pages, evidence

clarifying_questions 必须是列表；如果信息不足，最多输出 1 个可点选追问。每个元素包含：
id, question, options

evidence 必须是列表；每个元素包含 page, text, score。只能使用 workflow 结果里的 evidence_chunks，不要编造证据。

要求：
1. 如果用户原始问题没有明确实验任务、样本类型、设备名称或应用目标，即使 workflow 里有 candidate_devices 或 evidence_chunks，也不要推荐具体产品；recommended_devices 必须输出空列表，answer 只说明需要补充哪些信息，并给出 clarifying_questions。
2. 只有需求明确时，answer 才能先给出明确推荐结论，再说明推荐依据。
3. recommended_devices 最多返回 3 个。
4. recommended_devices[0].reasons 必须是 2 到 4 条简洁理由。
5. 如果 workflow 结果里存在 evidence_chunks，请将最相关证据概括进 answer，但不能把无关证据当成推荐依据。
6. 每个推荐设备的 matched_reason 要说明为什么命中当前需求。
7. 每个推荐设备的 evidence 最多放 2 条，text 控制在 260 字以内，source_pages 输出对应页码列表。
8. selection_notes 输出 1 到 3 条选型注意点。
9. description 不要写太长，控制在 1 到 3 句。
10. overview、advantages、applications 在推荐场景下可为空字符串。
11. clarifying_questions 的 options 必须是用户可直接点击、可由当前产品目录回答的短选项。最多保留一个问题，优先追问产品方向或样本类型；同一问题的选项必须互斥。已有候选产品时不要生成追问。
12. disclaimer 必须完整输出，不要截断。

下面是 workflow 结果：
{json.dumps(workflow_result, ensure_ascii=False)}
'''


def run_agent(user_input: str) -> dict:
    workflow_result = run_workflow(user_input)
    prompt = build_prompt(workflow_result)

    model_result, error = generate_json(prompt)
    if model_result:
        result = normalize_result(model_result)
        result["generation_source"] = "llm"
        result["model_name"] = model_config()["name"]
        return result

    fallback = normalize_result(build_fallback_answer(user_input, workflow_result))
    fallback["generation_source"] = "fallback"
    fallback["model_name"] = model_config()["name"]
    fallback["model_error"] = error or "model returned empty output"
    return fallback
