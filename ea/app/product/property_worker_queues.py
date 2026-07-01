from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PropertyWorkerQueueSpec:
    key: str
    label: str
    purpose: str
    max_attempts: int
    timeout_seconds: int
    customer_visible: bool = False


PROPERTY_WORKER_QUEUES: tuple[PropertyWorkerQueueSpec, ...] = (
    PropertyWorkerQueueSpec(
        key="provider-fetch",
        label="Provider fetch",
        purpose="Fetch provider search/detail pages and capture source receipts.",
        max_attempts=3,
        timeout_seconds=90,
    ),
    PropertyWorkerQueueSpec(
        key="browser-extraction",
        label="Browser extraction",
        purpose="Run browser-backed provider extraction and repair volatile page workflows.",
        max_attempts=3,
        timeout_seconds=180,
    ),
    PropertyWorkerQueueSpec(
        key="official-evidence",
        label="Local context",
        purpose="Collect official/public evidence snapshots used by research and scoring.",
        max_attempts=2,
        timeout_seconds=180,
    ),
    PropertyWorkerQueueSpec(
        key="ranking",
        label="Ranking",
        purpose="Score candidates and compile shortlist decisions.",
        max_attempts=2,
        timeout_seconds=120,
    ),
    PropertyWorkerQueueSpec(
        key="llm-research",
        label="Research",
        purpose="Extract and summarize bounded evidence from sanitized listing/document packets.",
        max_attempts=2,
        timeout_seconds=240,
    ),
    PropertyWorkerQueueSpec(
        key="document-parsing",
        label="Document parsing",
        purpose="Parse user-provided or provider-provided documents into evidence claims.",
        max_attempts=2,
        timeout_seconds=240,
    ),
    PropertyWorkerQueueSpec(
        key="pdf-render",
        label="Dossier render",
        purpose="Render PDFs and premium dossier artifacts.",
        max_attempts=2,
        timeout_seconds=180,
    ),
    PropertyWorkerQueueSpec(
        key="tour-media",
        label="Tour media",
        purpose="Generate or publish request-driven 360, tour and walkthrough artifacts.",
        max_attempts=1,
        timeout_seconds=600,
    ),
    PropertyWorkerQueueSpec(
        key="notification",
        label="Notification",
        purpose="Send email, Telegram, WhatsApp and delivery-center notifications.",
        max_attempts=3,
        timeout_seconds=60,
    ),
    PropertyWorkerQueueSpec(
        key="projection-sync",
        label="Projection sync",
        purpose="Sync internal run/account state to Teable and other operator projections.",
        max_attempts=3,
        timeout_seconds=120,
    ),
    PropertyWorkerQueueSpec(
        key="repair",
        label="Repair",
        purpose="Execute bounded provider, packet and run-recovery repair work.",
        max_attempts=3,
        timeout_seconds=300,
        customer_visible=True,
    ),
)

PROPERTY_WORKER_QUEUE_INDEX = {spec.key: spec for spec in PROPERTY_WORKER_QUEUES}


def property_worker_queue_keys() -> tuple[str, ...]:
    return tuple(spec.key for spec in PROPERTY_WORKER_QUEUES)


def property_worker_queue_spec(queue_key: object) -> PropertyWorkerQueueSpec:
    key = str(queue_key or "").strip().lower()
    return PROPERTY_WORKER_QUEUE_INDEX.get(key) or PROPERTY_WORKER_QUEUE_INDEX["repair"]
