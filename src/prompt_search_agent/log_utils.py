"""Small helpers for concise, readable operational logs."""

import json
from typing import Any


def log_value(value: Any, max_chars: int = 600) -> str:
    """Render a value for one-line logs without dumping unbounded output."""
    if hasattr(value, "model_dump"):
        value = value.model_dump()

    if isinstance(value, (dict, list, tuple)):
        try:
            rendered = json.dumps(
                value,
                ensure_ascii=False,
                default=str,
                separators=(",", ":"),
            )
        except (TypeError, ValueError):
            rendered = repr(value)
    else:
        rendered = str(value) if value is not None else "-"

    rendered = rendered.replace("\r", "\\r").replace("\n", "\\n")

    if len(rendered) <= max_chars:
        return rendered

    return f"{rendered[:max_chars]}...<truncated>"
