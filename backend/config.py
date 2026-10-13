import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

ROOT_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def app_config() -> dict[str, Any]:
    app_env = os.getenv("APP_ENV", "development").strip().lower()
    cors_origins = split_csv(os.getenv("CORS_ORIGINS"))
    allowed_hosts = split_csv(os.getenv("ALLOWED_HOSTS"))

    if app_env != "production" and not cors_origins:
        cors_origins = ["*"]

    data_dir = Path(os.getenv("DATA_DIR", str(ROOT_DIR / "data")))
    return {
        "app_env": app_env,
        "debug": env_bool("APP_DEBUG", app_env != "production"),
        "cors_origins": cors_origins,
        "allowed_hosts": allowed_hosts,
        "data_dir": data_dir,
        "leads_file": Path(os.getenv("LEADS_FILE", str(data_dir / "leads.jsonl"))),
        "rate_limit_per_minute": env_int("RATE_LIMIT_PER_MINUTE", 60),
        "rate_limit_enabled": env_bool("RATE_LIMIT_ENABLED", True),
    }
