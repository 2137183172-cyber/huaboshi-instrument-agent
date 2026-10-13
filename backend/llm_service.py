import json
import os
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(override=True)

MODEL = os.getenv("CHAT_OPENAI_MODEL", os.getenv("OPENAI_MODEL", "qwen-plus"))
BASE_URL = os.getenv(
    "CHAT_OPENAI_BASE_URL",
    os.getenv("OPENAI_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
)
CONFIGURED_TIMEOUT_SECONDS = float(
    os.getenv("CHAT_OPENAI_TIMEOUT_SECONDS", os.getenv("OPENAI_TIMEOUT_SECONDS", "28"))
)
HARD_TIMEOUT_SECONDS = float(os.getenv("CHAT_OPENAI_HARD_TIMEOUT_SECONDS", "28"))
TIMEOUT_SECONDS = min(CONFIGURED_TIMEOUT_SECONDS, HARD_TIMEOUT_SECONDS)
TEMPERATURE = float(os.getenv("CHAT_OPENAI_TEMPERATURE", os.getenv("OPENAI_TEMPERATURE", "0.2")))
MAX_RETRIES = max(0, int(os.getenv("CHAT_OPENAI_MAX_RETRIES", "0")))
MAX_TOKENS = max(64, int(os.getenv("CHAT_OPENAI_MAX_TOKENS", "800")))
ENABLE_THINKING = os.getenv("CHAT_OPENAI_ENABLE_THINKING", "false").strip().lower() in {"1", "true", "yes", "on"}


def build_client() -> OpenAI:
    api_key = os.getenv("CHAT_OPENAI_API_KEY", os.getenv("OPENAI_API_KEY"))
    if not api_key:
        raise RuntimeError("CHAT_OPENAI_API_KEY or OPENAI_API_KEY is not configured")

    return OpenAI(
        api_key=api_key,
        base_url=BASE_URL,
        timeout=TIMEOUT_SECONDS,
        max_retries=MAX_RETRIES,
    )


def model_config() -> dict[str, Any]:
    return {
        "configured": bool(os.getenv("CHAT_OPENAI_API_KEY", os.getenv("OPENAI_API_KEY"))),
        "name": MODEL,
        "base_url": BASE_URL,
        "embedding_model": os.getenv("EMBEDDING_MODEL", "text-embedding-v4"),
        "chat_provider": "local_ollama" if "127.0.0.1:11434" in BASE_URL or "localhost:11434" in BASE_URL else "openai_compatible",
        "timeout_seconds": TIMEOUT_SECONDS,
        "max_retries": MAX_RETRIES,
        "max_tokens": MAX_TOKENS,
        "enable_thinking": ENABLE_THINKING,
    }


def extract_json_object(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        raise ValueError("model returned empty text")

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise
        return json.loads(text[start : end + 1])


def generate_text(prompt: str, max_tokens: int | None = None) -> tuple[str | None, str | None]:
    try:
        resp = build_client().chat.completions.create(
            model=MODEL,
            temperature=TEMPERATURE,
            max_tokens=max_tokens or MAX_TOKENS,
            extra_body={"enable_thinking": ENABLE_THINKING},
            messages=[
                {
                    "role": "system",
                    "content": "你是华博士，一名严谨的科学仪器选型顾问。仅基于给定审核产品资料总结，不编造未提供的参数。缺失字段显示-。不输出产品编号、产业编号、记录键或库内产品数量。型号可以展示。内部参考报价不得输出，供货单位不得当作制造商。",
                },
                {"role": "user", "content": prompt},
            ],
        )
        text = (resp.choices[0].message.content or "").strip()
        return (text or None), None
    except Exception as e:
        return None, str(e)


def generate_json(prompt: str) -> tuple[dict[str, Any] | None, str | None]:
    text, error = generate_text(prompt)
    if error:
        return None, error

    try:
        return extract_json_object(text or ""), None
    except Exception as e:
        return None, f"model returned non-json output: {e}"


def check_llm_connection() -> dict[str, Any]:
    config = model_config()
    if not config["configured"]:
        return {
            **config,
            "ok": False,
            "error": "OPENAI_API_KEY is not configured",
        }

    text, error = generate_text("请只回复：ok", max_tokens=8)
    if error:
        return {
            **config,
            "ok": False,
            "error": error,
        }

    return {
        **config,
        "ok": True,
        "sample": text,
    }
