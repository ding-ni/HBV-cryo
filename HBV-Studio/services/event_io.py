from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from services.json_utils import read_json_file


def read_csv_flexible(path: Path) -> pd.DataFrame:
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "gbk", "gb18030"):
        try:
            return pd.read_csv(path, encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    return pd.read_csv(path)


def read_event_table_file(path: Path) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix in {".json", ".geojson"}:
        raw = read_json_file(path)
        if isinstance(raw, dict):
            events = raw.get("\u4e8b\u4ef6\u8868", raw.get("events", []))
        else:
            events = raw
        return [dict(item) for item in events if isinstance(item, dict)] if isinstance(events, list) else []
    if suffix in {".xlsx", ".xls"}:
        frame = pd.read_excel(path)
    else:
        frame = read_csv_flexible(path)
    return [
        {str(key).strip(): value for key, value in row.items() if str(key).strip()}
        for row in frame.to_dict(orient="records")
    ]
