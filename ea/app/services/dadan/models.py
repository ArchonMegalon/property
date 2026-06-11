from __future__ import annotations

from pydantic import BaseModel, Field


class DadanRecordingRequest(BaseModel):
    request_code: str
    request_url: str
    title: str
    status: str = "created"
    raw_response_json: dict[str, object] = Field(default_factory=dict)


class DadanRecordingRequestStatus(BaseModel):
    request_code: str
    status: str = "unknown"
    recording_url: str = ""
    submitted_at: str = ""
    raw_response_json: dict[str, object] = Field(default_factory=dict)
