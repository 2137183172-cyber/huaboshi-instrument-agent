import os
from dotenv import load_dotenv
from backend.rag.embedder import embed_text
from neo4j import GraphDatabase

load_dotenv()

driver = GraphDatabase.driver(
    os.getenv("NEO4J_URI"),
    auth=(os.getenv("NEO4J_USERNAME"), os.getenv("NEO4J_PASSWORD")),
    max_transaction_retry_time=2,
) if os.getenv("NEO4J_URI") else None
DB = os.getenv("NEO4J_DATABASE", "neo4j")

def retrieve_chunks(query_text: str, product_names=None, top_k: int = 5):
    if driver is None or not os.getenv("OPENAI_API_KEY"):
        return []
    product_names = product_names or []
    query_vector = embed_text(query_text)

    if product_names:
        cypher = """
        CALL db.index.vector.queryNodes('chunk_embedding_index', $top_k, $query_vector)
        YIELD node, score
        WHERE node.product_name IN $product_names
        RETURN node.chunk_id AS chunk_id,
               node.product_name AS product_name,
               node.page AS page,
               node.text AS text,
               score
        ORDER BY score DESC
        """
        records, summary, keys = driver.execute_query(
            cypher,
            database_=DB,
            top_k=top_k,
            query_vector=query_vector,
            product_names=product_names
        )
    else:
        cypher = """
        CALL db.index.vector.queryNodes('chunk_embedding_index', $top_k, $query_vector)
        YIELD node, score
        RETURN node.chunk_id AS chunk_id,
               node.product_name AS product_name,
               node.page AS page,
               node.text AS text,
               score
        ORDER BY score DESC
        """
        records, summary, keys = driver.execute_query(
            cypher,
            database_=DB,
            top_k=top_k,
            query_vector=query_vector
        )

    return [r.data() for r in records]
