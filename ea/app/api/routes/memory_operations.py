from __future__ import annotations

from fastapi import APIRouter

from app.api.routes.memory_commitments import router as memory_commitments_router
from app.api.routes.memory_followups import router as memory_followups_router
from app.api.routes.memory_windows import router as memory_windows_router

router = APIRouter(tags=["memory"])
router.include_router(memory_commitments_router)
router.include_router(memory_followups_router)
router.include_router(memory_windows_router)
