import os
from dotenv import load_dotenv
from neo4j import GraphDatabase
from backend.rag.embedder import embed_text

load_dotenv()

driver = GraphDatabase.driver(
    os.getenv("NEO4J_URI"),
    auth=(os.getenv("NEO4J_USERNAME"), os.getenv("NEO4J_PASSWORD")),
)
DB = os.getenv("NEO4J_DATABASE", "neo4j")

TEXT = "通过整合专利的染色技术试剂、高效可靠的成像检测设备、经过真实数据训练的数据分析软件，实现高质量和高分辨率的光学切片图像。"

embedding = embed_text(TEXT)
print("embedding长度：", len(embedding))

query = """
MATCH (chunk:DocumentChunk {chunk_id: $chunk_id})
SET chunk.embedding = $embedding
RETURN chunk.chunk_id AS chunk_id, size(chunk.embedding) AS dim
"""

records, summary, keys = driver.execute_query(
    query,
    database_=DB,
    chunk_id="CHUNK001",
    embedding=embedding
)

for r in records:
    print(r.data())

driver.close()