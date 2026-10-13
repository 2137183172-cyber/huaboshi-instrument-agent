def extract_slots(user_query: str) -> dict:
    result = {
        "task": None,
        "sample_type": None,
        "resolution": None,
        "automation": False,
        "throughput": None,
        "budget": None,
    }

    # 任务识别
    if "单细胞" in user_query and "空间" in user_query:
        result["task"] = "单细胞原位空间组学"
    elif "NGS" in user_query or "建库" in user_query or "测序" in user_query:
        result["task"] = "NGS测序建库"
    elif "蛋白组学" in user_query:
        result["task"] = "蛋白组学分析"
    elif "激光切割" in user_query or "显微切割" in user_query:
        result["task"] = "激光显微切割"

    # 样本类型识别
    if "组织切片" in user_query:
        result["sample_type"] = "组织切片"
    elif "培养细胞" in user_query:
        result["sample_type"] = "培养细胞"
    elif "血浆" in user_query:
        result["sample_type"] = "血浆"
    elif "细胞" in user_query:
        result["sample_type"] = "细胞样本"

    # 分辨率
    if "高分辨率" in user_query or "分辨率高" in user_query:
        result["resolution"] = "高"
    elif "单细胞分辨率" in user_query:
        result["resolution"] = "单细胞级"

    # 自动化
    if "自动化" in user_query or "无人值守" in user_query:
        result["automation"] = True

    # 通量
    if "高通量" in user_query:
        result["throughput"] = "高通量"
    elif "低通量" in user_query:
        result["throughput"] = "低通量"

    # 预算
    if "30万" in user_query:
        result["budget"] = "30万"
    elif "50万" in user_query:
        result["budget"] = "50万"
    elif "预算不限" in user_query:
        result["budget"] = "不限"

    return result