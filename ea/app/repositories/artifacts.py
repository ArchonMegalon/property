from __future__ import annotations

from typing import Dict, Protocol

from app.domain.models import Artifact, normalize_artifact


class ArtifactRepository(Protocol):
    def save(self, artifact: Artifact) -> None:
        ...

    def get(self, artifact_id: str) -> Artifact | None:
        ...

    def list_for_session(self, session_id: str) -> list[Artifact]:
        ...


class InMemoryArtifactRepository:
    def __init__(self) -> None:
        self._rows: Dict[str, Artifact] = {}

    def save(self, artifact: Artifact) -> None:
        normalized = normalize_artifact(artifact)
        self._rows[normalized.artifact_id] = normalized

    def get(self, artifact_id: str) -> Artifact | None:
        return self._rows.get(str(artifact_id or ""))

    def list_for_session(self, session_id: str) -> list[Artifact]:
        sid = str(session_id or "")
        return [row for row in self._rows.values() if row.execution_session_id == sid]
