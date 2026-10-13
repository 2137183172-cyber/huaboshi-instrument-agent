import re
import string

from backend.agent import normalize_result
from backend.llm_service import model_config


MEANINGFUL_PATTERN = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]")

GENERIC_QUERIES = {
    "你好",
    "您好",
    "在吗",
    "推荐",
    "推荐一下",
    "帮我推荐",
    "产品",
    "设备",
    "仪器",
    "有什么产品",
    "有哪些产品",
    "有什么设备",
    "有哪些设备",
    "生物产品",
    "生物仪器",
}


def meaningful_text(user_query: str) -> str:
    return "".join(MEANINGFUL_PATTERN.findall(user_query or "")).lower()


def is_uninformative_query(user_query: str) -> bool:
    text = (user_query or "").strip()
    if not text:
        return True

    normalized = meaningful_text(text)
    if not normalized:
        return True

    if len(normalized) <= 1:
        return True

    clean_text = text.strip(string.whitespace + string.punctuation + "，。！？；：、“”‘’（）【】《》…")
    return clean_text in GENERIC_QUERIES


def build_uninformative_query_result(user_query: str = "") -> dict:
    text = (user_query or "").strip()
    selection_request = any(marker in text for marker in ("推荐", "选型", "怎么选", "适合", "需要什么"))
    if not selection_request:
        return normalize_result({
            "intent": "guide",
            "answer": "您好，我可以帮您查具体产品、按仪器类别浏览，或根据实验任务进行选型。请直接告诉我想了解的产品名称、仪器类别或实验需求。",
            "recommended_devices": [],
            "need_more_info": [],
            "clarifying_questions": [],
            "related_questions": [
                "有什么产品",
                "按实验任务推荐产品",
                "请介绍一个具体产品",
            ],
            "disclaimer": "当前回答用于引导下一步咨询。",
            "generation_source": "fallback",
            "model_name": model_config()["name"],
        })

    return normalize_result({
        "intent": "clarify",
        "answer": (
            "我还不能直接推荐具体产品，因为当前问题没有包含实验任务、样本类型或目标指标。"
            "请先补充你要做什么实验、样本是什么，以及是否有通量、预算或自动化要求。"
        ),
        "recommended_devices": [],
        "need_more_info": [
            "请选择最接近的产品方向，便于继续匹配具体设备。",
        ],
        "clarifying_questions": [],
        "related_questions": [
            "按我的实验任务推荐设备",
            "请介绍一个具体产品",
            "比较两台设备的差异",
        ],
        "disclaimer": "当前回答未调用产品推荐，仅用于澄清需求。",
        "generation_source": "fallback",
        "model_name": model_config()["name"],
    })
