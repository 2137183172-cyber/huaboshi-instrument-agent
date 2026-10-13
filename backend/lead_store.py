import json
from pathlib import Path
from threading import Lock
from typing import Any

from backend.config import app_config

_lock = Lock()


def leads_file() -> Path:
    return app_config()["leads_file"]


def save_lead(record: dict[str, Any]) -> None:
    path = leads_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False)
    with _lock:
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def get_lead_by_id(lead_id: str) -> dict[str, Any] | None:
    """Return a lead by its random public detail identifier."""
    if not lead_id:
        return None

    path = leads_file()
    if not path.exists():
        return None

    with _lock:
        lines = path.read_text(encoding="utf-8").splitlines()

    for line in reversed(lines):
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict) and record.get("lead_id") == lead_id:
            return record
    return None
