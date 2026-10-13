import json
import os
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

from backend.rag.chunker import build_chunks
from backend.rag.embedder import embed_text

load_dotenv()

# 如果你的 .env 已经配好，就用这一版
driver = GraphDatabase.driver(
    os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687"),
    auth=(os.getenv("NEO4J_USERNAME", "neo4j"), os.getenv("NEO4J_PASSWORD", "")),
)
DB = os.getenv("NEO4J_DATABASE", "neo4j")


def clean_text(text: str) -> str:
    if not text:
        return ""
    return " ".join(str(text).split()).strip()


def extract_sections_from_page(page: dict) -> dict:
    """
    优先读取 OCR JSON 里现成的 overview / advantages / applications。
    如果没有，就从 lines 中按标题兜底切分。
    如果还切不出来，就把整页文本兜底放到 overview。
    """
    overview = clean_text(page.get("overview", ""))
    advantages = clean_text(page.get("advantages", ""))
    applications = clean_text(page.get("applications", ""))

    lines = page.get("lines", []) or []
    full_text = "\n".join([str(x).strip() for x in lines if str(x).strip()])

    # 如果已经有结构化字段，就直接返回
    if overview or advantages or applications:
        return {
            "overview": overview,
            "advantages": advantages,
            "applications": applications,
        }

    current = None
    buckets = {
        "overview": [],
        "advantages": [],
        "applications": [],
    }

    for raw_line in lines:
        line = str(raw_line).strip()
        if not line:
            continue

        # 标题识别：产品简介 / 概述
        if any(k in line for k in ["产品简介", "简介", "产品概述", "概述"]):
            current = "overview"
            continue

        # 标题识别：产品优势 / 特点
        if any(k in line for k in ["产品优势", "优势", "核心优势", "产品特点", "特点"]):
            current = "advantages"
            continue

        # 标题识别：应用场景 / 应用领域
        if any(k in line for k in ["应用场景", "应用领域", "典型应用", "应用"]):
            current = "applications"
            continue

        if current:
            buckets[current].append(line)

    overview = clean_text(" ".join(buckets["overview"])) or overview
    advantages = clean_text(" ".join(buckets["advantages"])) or advantages
    applications = clean_text(" ".join(buckets["applications"])) or applications

    # 最后兜底：如果还是什么都没有，就把整页文本放到 overview
    if not overview and not advantages and not applications:
        overview = clean_text(full_text)

    return {
        "overview": overview,
        "advantages": advantages,
        "applications": applications,
    }


def upsert_chunk(row: dict):
    query = """
    MERGE (doc:Document {doc_id: $doc_id})
    SET doc.product_name = $product_name,
        doc.doc_type = $doc_type

    MERGE (chunk:DocumentChunk {chunk_id: $chunk_id})
    SET chunk.product_name = $product_name,
        chunk.doc_type = $doc_type,
        chunk.page = $page,
        chunk.text = $text,
        chunk.section_type = $section_type,
        chunk.embedding = $embedding

    MERGE (doc)-[:HAS_CHUNK]->(chunk)

    WITH doc
    MATCH (d:Device {name: $product_name})
    MERGE (d)-[:HAS_DOC]->(doc)
    """
    driver.execute_query(query, database_=DB, **row)


def ingest_json_file(json_path: str, doc_type: str = "product_manual"):
    with open(json_path, "r", encoding="utf-8") as f:
        pages = json.load(f)

    count = 0

    for page in pages:
        if not page.get("is_product_page"):
            continue

        product_name = clean_text(page.get("title", ""))
        if not product_name:
            continue

        section_data = extract_sections_from_page(page)

        sections = [
            ("overview", section_data.get("overview", "")),
            ("advantages", section_data.get("advantages", "")),
            ("applications", section_data.get("applications", "")),
        ]

        for section_type, section_text in sections:
            section_text = clean_text(section_text)
            if not section_text:
                continue

            chunks = build_chunks(
                product_name=product_name,
                doc_type=doc_type,
                pages=[{
                    "page": page.get("page"),
                    "lines": [section_text]
                }]
            )

            for c in chunks:
                c["doc_id"] = f"{product_name}_{doc_type}"
                c["chunk_id"] = f"{c['chunk_id']}_{section_type}"
                c["section_type"] = section_type
                c["embedding"] = embed_text(c["text"]) 

                upsert_chunk(c)
                count += 1
                print(f"已写入 chunk: {c['chunk_id']} [{section_type}]")

    print(f"总共写入 {count} 个 chunks")


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[2]
    json_path = project_root / "data" / "raw_docs" / "智荟华科产品手册_OCR页面结果.json"
    print("读取文件：", json_path)
    ingest_json_file(str(json_path))