"""Public presentation helpers for reviewed scenario plans."""


_EMPTY_MODELS = {"", "-", "——"}


def public_device_name(name, model=""):
    """Remove a known model wrapper while preserving semantic annotations."""
    text = str(name or "").strip()
    model = str(model or "").strip()
    if not text or model in _EMPTY_MODELS or model not in text:
        return text
    start = text.find(model)
    end = start + len(model)
    if start > 0 and end < len(text) and text[start - 1] in "（(" and text[end] in "）)":
        text = text[: start - 1] + text[end + 1 :]
    else:
        text = text.replace(model, "")
    return " ".join(text.split()).strip(" ；;,，")


def public_text(plan, value):
    """Hide catalog models in public scenario prose without changing source data."""
    text = str(value or "")
    rows = plan.get("equipment_table", []) if isinstance(plan, dict) else []
    replacements = []
    for row in rows:
        raw_name = str(row.get("name") or "")
        visible_name = public_device_name(raw_name, row.get("model"))
        if raw_name and raw_name != visible_name:
            replacements.append((raw_name, visible_name))
    for raw_name, visible_name in sorted(replacements, key=lambda item: len(item[0]), reverse=True):
        text = text.replace(raw_name, visible_name)
    return text

