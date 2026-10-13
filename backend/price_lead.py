import re
from typing import Any

from backend.device_name_extractor import extract_device_name
from backend.llm_service import model_config

PRICE_KEYWORDS = ["价格", "多少钱", "报价", "费用", "采购价", "市场价", "询价"]


def is_price_query(user_query: str) -> bool:
    text = (user_query or "").strip()
    return bool(text) and any(keyword in text for keyword in PRICE_KEYWORDS)


def extract_price_product_name(user_query: str) -> str:
    text = (user_query or "").strip()
    device_name = extract_device_name(text)
    if device_name:
        return device_name

    match = re.search(r"关于(.+?)[，,。？?\s]", text)
    if match:
        return match.group(1).strip()

    return ""


def build_price_lead_result(user_query: str) -> dict[str, Any]:
    product_name = extract_price_product_name(user_query)
    product_text = f"《{product_name}》" if product_name else "该产品"
    answer = (
        f"{product_text}的价格通常会根据配置、采购数量、配套试剂/耗材、安装培训和售后服务方案而变化。"
        "若您想了解产品价格，请留下您的联系方式，工作人员会第一时间为您提供报价方案。"
    ) if product_name else (
        "产品价格通常会根据具体型号、配置、采购数量、配套试剂/耗材、安装培训和售后服务方案而变化。"
        "请填写咨询产品和联系方式，工作人员会第一时间为您提供报价方案。"
    )

    fields = [
        {
            "name": "name",
            "label": "姓名",
            "type": "text",
            "required": True,
            "placeholder": "请输入您的姓名",
        },
        {
            "name": "phone",
            "label": "手机号/微信",
            "type": "text",
            "required": True,
            "placeholder": "便于工作人员联系报价",
        },
        {
            "name": "organization",
            "label": "单位/机构",
            "type": "text",
            "required": False,
            "placeholder": "例如：医院、科研院所、企业",
        },
        {
            "name": "requirement",
            "label": "需求备注",
            "type": "textarea",
            "required": False,
            "placeholder": "可填写样本类型、通量、采购时间或配置要求",
        },
    ]

    if not product_name:
        fields.insert(0, {
            "name": "product_name",
            "label": "咨询产品",
            "type": "text",
            "required": True,
            "placeholder": "请输入想了解报价的产品名称",
        })

    return {
        "intent": "lead_capture",
        "answer": answer,
        "recommended_devices": [],
        "need_more_info": [],
        "clarifying_questions": [],
        "related_questions": [
            f"{product_text}有哪些配置可选？",
            f"{product_text}适合哪些应用场景？",
            "我需要准备哪些采购需求信息？",
        ],
        "disclaimer": "价格与供货方案以工作人员正式报价和合同约定为准。",
        "generation_source": "fallback",
        "model_name": model_config()["name"],
        "lead_form": {
            "type": "price_quote",
            "title": "获取产品报价方案",
            "product_name": product_name,
            "submit_label": "提交报价需求",
            "success_message": "已收到您的报价需求，工作人员会第一时间联系您。",
            "fields": fields,
        },
    }
