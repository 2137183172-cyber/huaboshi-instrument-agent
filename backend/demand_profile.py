from __future__ import annotations

from typing import Any


def _unique(items: list[str]) -> list[str]:
    result = []
    for item in items:
        if item and item not in result:
            result.append(item)
    return result


TASK_RULES = [
    ("单细胞原位空间组学", ["单细胞", "空间组学", "原位", "空间转录组"]),
    ("NGS测序建库", ["NGS", "测序", "建库", "文库制备", "文库构建"]),
    ("核酸提取/纯化", ["核酸提取", "RNA提取", "DNA提取", "提取", "纯化", "磁珠"]),
    ("蛋白样本前处理", ["蛋白", "蛋白组学", "蛋白样本", "酶解", "肽段"]),
    ("MALDI靶标板点样", ["MALDI", "靶标板", "点样"]),
    ("质谱检测", ["质谱", "飞行时间", "MALDI"]),
    ("细胞培养自动化", ["细胞培养", "换液", "培养自动化", "细胞生产"]),
    ("类器官/3D细胞分析", ["类器官", "3D细胞", "三维细胞"]),
    ("活体/显微成像", ["成像", "显微", "活体", "高光谱", "共聚焦"]),
    ("外泌体处理", ["外泌体"]),
    ("分子互作", ["分子互作", "互作"]),
]

SAMPLE_RULES = [
    ("组织切片", ["组织切片", "切片", "冰冻组织", "FFPE", "组织芯片"]),
    ("培养细胞", ["培养细胞", "贴壁细胞", "悬浮细胞", "细胞样本"]),
    ("类器官", ["类器官", "3D细胞", "三维细胞"]),
    ("血液/血清", ["血液", "血清", "血浆", "血涂片", "骨髓片"]),
    ("96孔板样本", ["96孔", "96 孔", "孔板"]),
    ("动物/植物活体", ["小动物", "动物活体", "植物活体", "活体"]),
    ("核酸样本", ["DNA", "RNA", "核酸", "PCR扩增产物"]),
    ("蛋白样本", ["蛋白", "肽段", "蛋白样本"]),
]


def parse_demand(user_query: str) -> dict[str, Any]:
    text = user_query or ""
    tasks = []
    sample_types = []

    for label, keywords in TASK_RULES:
        if any(keyword in text for keyword in keywords):
            tasks.append(label)

    for label, keywords in SAMPLE_RULES:
        if any(keyword in text for keyword in keywords):
            sample_types.append(label)

    automation = any(keyword in text for keyword in ["自动化", "全自动", "无人值守", "减少人工", "自动"])
    high_throughput = any(keyword in text for keyword in ["高通量", "批量", "大批量", "样本量大", "96", "384", ">96"])
    medium_throughput = any(keyword in text for keyword in ["24-96", "中等通量", "中通量"])
    low_throughput = any(keyword in text for keyword in ["1-12", "少量", "低通量"])

    resolution = None
    if any(keyword in text for keyword in ["≤ 100 nm", "≤100nm", "100 nm", "纳米", "亚细胞"]):
        resolution = "纳米/亚细胞级"
    elif any(keyword in text for keyword in ["单细胞分辨率", "单细胞级"]):
        resolution = "单细胞级"
    elif any(keyword in text for keyword in ["高分辨率", "分辨率高"]):
        resolution = "高分辨率"

    budget = None
    for marker in ["30万", "50万", "100万", "预算不限"]:
        if marker in text:
            budget = marker
            break

    return {
        "tasks": _unique(tasks),
        "sample_types": _unique(sample_types),
        "automation": automation,
        "high_throughput": high_throughput,
        "medium_throughput": medium_throughput,
        "low_throughput": low_throughput,
        "resolution": resolution,
        "budget": budget,
    }
