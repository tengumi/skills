"""Audit log — JSON-lines, append-only.

То же что в remote-exec/lib/audit.py — переиспользуем дизайн.
Логирует каждую заметную операцию watcher'а: запуск, обнаружение request,
выполнение команд, ошибки.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class AuditLog:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch(mode=0o644)

    def log(self, event: str, **fields: Any) -> None:
        entry = {"ts": _now(), "event": event, **fields}
        line = json.dumps(entry, ensure_ascii=False, default=_default)
        try:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass

    def tail(self, n: int = 50) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except OSError:
            return []
        result = []
        for line in lines[-n:]:
            line = line.strip()
            if not line:
                continue
            try:
                result.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return result


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _default(obj: Any) -> Any:
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    return str(obj)
