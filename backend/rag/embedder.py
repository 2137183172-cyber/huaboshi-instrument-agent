"""Embedding utilities for retrieval."""
import os
from functools import lru_cache

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(override=True)

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-v4")
TIMEOUT_SECONDS = float(os.getenv("EMBEDDING_TIMEOUT_SECONDS", "8"))
MAX_RETRIES = max(0, int(os.getenv("EMBEDDING_MAX_RETRIES", "0")))
CACHE_MAX = max(1, int(os.getenv("EMBEDDING_CACHE_MAX", "256")))

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url=os.getenv("OPENAI_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
    timeout=TIMEOUT_SECONDS,
    max_retries=MAX_RETRIES,
) if os.getenv("OPENAI_API_KEY") else None


@lru_cache(maxsize=CACHE_MAX)
def _embed_text_cached(text: str):
    if client is None:
        raise RuntimeError("Embedding service is not configured")
    resp = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=text,
    )
    return resp.data[0].embedding


def embed_text(text: str):
    return _embed_text_cached(str(text or "").strip())
