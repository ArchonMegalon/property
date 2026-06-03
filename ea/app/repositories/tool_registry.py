from __future__ import annotations

from dataclasses import replace
from typing import Dict, List, Protocol

from app.domain.models import ToolDefinition, now_utc_iso


class ToolRegistryRepository(Protocol):
    def upsert(self, row: ToolDefinition) -> ToolDefinition:
        ...

    def get(self, tool_name: str) -> ToolDefinition | None:
        ...

    def list_enabled(self, limit: int = 100) -> list[ToolDefinition]:
        ...


class InMemoryToolRegistryRepository:
    def __init__(self) -> None:
        self._rows: Dict[str, ToolDefinition] = {}
        self._order: List[str] = []

    def upsert(self, row: ToolDefinition) -> ToolDefinition:
        key = str(row.tool_name or "").strip()
        if not key:
            raise ValueError("tool_name is required")
        updated = replace(row, tool_name=key, updated_at=now_utc_iso())
        if key not in self._rows:
            self._order.append(key)
        self._rows[key] = updated
        return updated

    def get(self, tool_name: str) -> ToolDefinition | None:
        return self._rows.get(str(tool_name or "").strip())

    def list_enabled(self, limit: int = 100) -> list[ToolDefinition]:
        n = max(1, min(500, int(limit or 100)))
        keys = list(reversed(self._order))
        rows = [self._rows[k] for k in keys if k in self._rows and self._rows[k].enabled]
        return rows[:n]
