from __future__ import annotations

from app.product.property_worker_queues import (
    PROPERTY_WORKER_QUEUES,
    property_worker_queue_keys,
    property_worker_queue_spec,
)


def test_property_worker_queue_catalog_covers_required_lanes() -> None:
    keys = set(property_worker_queue_keys())

    assert keys >= {
        "provider-fetch",
        "browser-extraction",
        "official-evidence",
        "ranking",
        "llm-research",
        "document-parsing",
        "pdf-render",
        "tour-media",
        "notification",
        "projection-sync",
        "repair",
    }
    assert len(keys) == len(PROPERTY_WORKER_QUEUES)
    assert all(spec.max_attempts >= 1 for spec in PROPERTY_WORKER_QUEUES)
    assert all(spec.timeout_seconds >= 30 for spec in PROPERTY_WORKER_QUEUES)


def test_property_worker_queue_spec_fails_closed_to_repair_lane() -> None:
    unknown = property_worker_queue_spec("unknown-lane")

    assert unknown.key == "repair"
    assert unknown.label == "Search health"
    assert "provider" not in unknown.purpose.lower()
    assert unknown.customer_visible is True
