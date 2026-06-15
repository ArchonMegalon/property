#!/usr/bin/env python3
from __future__ import annotations

import os
import sys


def main() -> int:
    database_url = str(os.environ.get("DATABASE_URL") or "").strip()
    if not database_url:
        print("DATABASE_URL is not set; cannot migrate property search storage schema.", file=sys.stderr)
        return 1

    from app.product.property_search_storage import (
        _ensure_property_search_run_schema,
        _ensure_property_source_listing_cache_schema,
    )

    _ensure_property_search_run_schema()
    _ensure_property_source_listing_cache_schema()
    print("property search storage schema ensured")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
