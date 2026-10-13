import os
from typing import Any, Dict, List

from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv(override=True)

driver = GraphDatabase.driver(
    os.getenv("NEO4J_URI"),
    auth=(os.getenv("NEO4J_USERNAME"), os.getenv("NEO4J_PASSWORD")),
    max_transaction_retry_time=2,
) if os.getenv("NEO4J_URI") else None
DB = os.getenv("NEO4J_DATABASE", "neo4j")


def check_neo4j_connection() -> Dict[str, Any]:
    if driver is None:
        return {"ok": False, "error": "Neo4j is not configured; using local data."}
    try:
        driver.verify_connectivity()
        return {
            "ok": True,
            "uri": os.getenv("NEO4J_URI"),
            "database": DB,
        }
    except Exception as e:
        return {
            "ok": False,
            "uri": os.getenv("NEO4J_URI"),
            "database": DB,
            "error": str(e),
        }


def _rows(query: str, **params) -> List[Dict[str, Any]]:
    if driver is None:
        return []
    records, summary, keys = driver.execute_query(query, database_=DB, **params)
    return [r.data() for r in records]


def _clean_list(values: List[Any]) -> List[Any]:
    if not isinstance(values, list):
        return []
    result = []
    for x in values:
        if x is None:
            continue
        if isinstance(x, str) and not x.strip():
            continue
        result.append(x)
    return result


def _clean_constraints(values: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not isinstance(values, list):
        return []
    result = []
    for x in values:
        if not isinstance(x, dict):
            continue
        if not x.get("constraint"):
            continue
        result.append({
            "constraint": x.get("constraint"),
            "relation": x.get("relation"),
        })
    return result


def get_device_detail(device_name: str) -> Dict[str, Any]:
    query = """
    MATCH (d:Device {name: $device_name})
    OPTIONAL MATCH (d)-[:HAS_CAPABILITY]->(c:Capability)
    OPTIONAL MATCH (d)-[:APPLIED_IN]->(t:ExperimentTask)
    OPTIONAL MATCH (ct:Constraint)-[r]->(d)
    OPTIONAL MATCH (d)-[:HAS_DOC]->(doc:Document)-[:HAS_CHUNK]->(chunk:DocumentChunk)

    WITH d,
         collect(DISTINCT c.capability_name) AS capabilities,
         collect(DISTINCT t.task_name) AS tasks,
         collect(DISTINCT {constraint: ct.constraint_name, relation: type(r)}) AS constraints,
         collect(DISTINCT chunk) AS chunks

    RETURN d.name AS name,
           null AS product_code,
           capabilities,
           tasks,
           constraints,
           [x IN chunks WHERE x.section_type = 'overview' | x.text][0] AS overview,
           [x IN chunks WHERE x.section_type = 'advantages' | x.text][0] AS advantages,
           [x IN chunks WHERE x.section_type = 'applications' | x.text][0] AS applications,
           [x IN chunks WHERE x IS NOT NULL | {
               chunk_id: x.chunk_id,
               page: x.page,
               section_type: x.section_type,
               text: x.text
           }] AS evidence_chunks
    """
    rows = _rows(query, device_name=device_name)
    if not rows:
        return {"error": "未找到该设备"}

    row = rows[0]
    return {
        "name": row.get("name"),
        "product_code": row.get("product_code"),
        "capabilities": _clean_list(row.get("capabilities", [])),
        "tasks": _clean_list(row.get("tasks", [])),
        "constraints": _clean_constraints(row.get("constraints", [])),
        "overview": row.get("overview") or "",
        "advantages": row.get("advantages") or "",
        "applications": row.get("applications") or "",
        "evidence_chunks": _clean_list(row.get("evidence_chunks", [])),
    }


def find_devices_by_task(task_keyword: str) -> List[Dict[str, Any]]:
    query = """
    MATCH (d:Device)-[:APPLIED_IN]->(t:ExperimentTask)
    WHERE t.task_name CONTAINS $task_keyword
    OPTIONAL MATCH (d)-[:HAS_CAPABILITY]->(c:Capability)
    RETURN d.name AS name,
           null AS product_code,
           collect(DISTINCT c.capability_name) AS capabilities,
           collect(DISTINCT t.task_name) AS tasks
    ORDER BY d.name
    LIMIT 10
    """
    rows = _rows(query, task_keyword=task_keyword)
    return [
        {
            "name": row.get("name"),
            "product_code": row.get("product_code"),
            "capabilities": _clean_list(row.get("capabilities", [])),
            "tasks": _clean_list(row.get("tasks", [])),
        }
        for row in rows
    ]


def find_devices_by_capability(capability_keyword: str) -> List[Dict[str, Any]]:
    query = """
    MATCH (d:Device)-[:HAS_CAPABILITY]->(c:Capability)
    WHERE c.capability_name CONTAINS $capability_keyword
    OPTIONAL MATCH (d)-[:APPLIED_IN]->(t:ExperimentTask)
    RETURN d.name AS name,
           null AS product_code,
           collect(DISTINCT c.capability_name) AS capabilities,
           collect(DISTINCT t.task_name) AS tasks
    ORDER BY d.name
    LIMIT 10
    """
    rows = _rows(query, capability_keyword=capability_keyword)
    return [
        {
            "name": row.get("name"),
            "product_code": row.get("product_code"),
            "capabilities": _clean_list(row.get("capabilities", [])),
            "tasks": _clean_list(row.get("tasks", [])),
        }
        for row in rows
    ]


def find_devices_by_constraint(constraint_keyword: str) -> List[Dict[str, Any]]:
    query = """
    MATCH (ct:Constraint)-[r]->(d:Device)
    WHERE ct.constraint_name CONTAINS $constraint_keyword
    OPTIONAL MATCH (d)-[:HAS_CAPABILITY]->(c:Capability)
    OPTIONAL MATCH (d)-[:APPLIED_IN]->(t:ExperimentTask)
    RETURN d.name AS name,
           null AS product_code,
           ct.constraint_name AS constraint_name,
           type(r) AS relation,
           collect(DISTINCT c.capability_name) AS capabilities,
           collect(DISTINCT t.task_name) AS tasks
    ORDER BY d.name
    LIMIT 10
    """
    rows = _rows(query, constraint_keyword=constraint_keyword)
    return [
        {
            "name": row.get("name"),
            "product_code": row.get("product_code"),
            "constraint_name": row.get("constraint_name"),
            "relation": row.get("relation"),
            "capabilities": _clean_list(row.get("capabilities", [])),
            "tasks": _clean_list(row.get("tasks", [])),
        }
        for row in rows
    ]


def search_devices_fallback(keyword: str) -> List[Dict[str, Any]]:
    query = """
    MATCH (d:Device)
    WHERE d.name CONTAINS $keyword
    OPTIONAL MATCH (d)-[:HAS_CAPABILITY]->(c:Capability)
    OPTIONAL MATCH (d)-[:APPLIED_IN]->(t:ExperimentTask)
    RETURN d.name AS name,
           null AS product_code,
           collect(DISTINCT c.capability_name) AS capabilities,
           collect(DISTINCT t.task_name) AS tasks
    ORDER BY d.name
    LIMIT 10
    """
    rows = _rows(query, keyword=keyword)
    return [
        {
            "name": row.get("name"),
            "product_code": row.get("product_code"),
            "capabilities": _clean_list(row.get("capabilities", [])),
            "tasks": _clean_list(row.get("tasks", [])),
        }
        for row in rows
    ]
