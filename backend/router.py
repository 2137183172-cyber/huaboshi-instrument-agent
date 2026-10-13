from backend.device_name_extractor import extract_device_name


def looks_like_unknown_device_detail(text: str) -> bool:
    if not any(keyword in text for keyword in ["介绍", "详情", "参数", "配置", "做什么", "是什么"]):
        return False
    if any(keyword in text for keyword in ["设备", "系统", "仪", "工作站", "平台"]):
        return True
    return any(ch.isascii() and ch.isalnum() for ch in text) and len(text.strip()) >= 6

def route_intent(user_query: str) -> str:
    text = (user_query or "").strip()

    compare_keywords = ["对比", "区别", "差异", "哪个好"]
    recommend_keywords = ["推荐", "选型", "哪些设备", "有什么推荐", "方案", "怎么选"]
    detail_keywords = ["介绍", "是什么", "做什么", "详情", "参数", "配置"]
    supplement_markers = ["补充信息", "补充信", "您的样本类型", "样本类型", "类器官", "组织切片", "培养细胞", "血浆", "血清"]

    if text.startswith("根据上一轮候选设备"):
        return "recommend"

    if any(x in text for x in supplement_markers) and not extract_device_name(text):
        return "recommend"

    # 1. 对比优先
    if any(x in text for x in compare_keywords):
        return "compare"

    # 2. 先尝试识别设备名
    device_name = extract_device_name(text)

    # 3. 只要识别出明确设备名，而且没有明显推荐词，就走 detail
    if device_name and not any(x in text for x in recommend_keywords):
        return "detail"

    # 4. 明确详情问法
    if any(x in text for x in detail_keywords) and (device_name or looks_like_unknown_device_detail(text)):
        return "detail"

    # 5. 推荐类
    if any(x in text for x in recommend_keywords) or ("适合" in text and not device_name):
        return "recommend"

    # 6. 默认：有设备名就详情，没有就推荐
    if device_name:
        return "detail"

    return "recommend"
