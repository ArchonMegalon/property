from pathlib import Path


def test_provider_extraction_playbook_keeps_provider_gimmicks_generic() -> None:
    text = Path("docs/PROPERTY_PROVIDER_EXTRACTION_PLAYBOOK.md").read_text(encoding="utf-8")

    required_contracts = [
        "Provider-specific code may only normalize access to source data",
        "Concrete location guard",
        "Detailed concrete location guard",
        "Gallery media scan plus visual floorplan classifier",
        "Document/archive floorplan recovery",
        "Attempted provider query plus post-filter receipt",
        "Review packets, tours, fly-throughs, and notifications must only be created after the detailed concrete-location guard.",
        "Near-miss prompts must never be sent for outside-area listings.",
        "Provider failures and repair tasks stay operator-only.",
    ]

    for contract in required_contracts:
        assert contract in text
