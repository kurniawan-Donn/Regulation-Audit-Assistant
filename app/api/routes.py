"""
Router API utama — menggabungkan router per tool.

Setiap tool punya modulnya sendiri (lihat app/api/*_routes.py); helper
bersama ada di app/api/common.py.
"""

from fastapi import APIRouter

from app.api.audit_routes import router as audit_router
from app.api.chat_routes import router as chat_router
from app.api.compliance_routes import router as compliance_router
from app.api.gap_routes import router as gap_router
from app.api.history_routes import router as history_router
from app.api.search_routes import router as search_router
from app.api.settings_routes import router as settings_router

router = APIRouter()
router.include_router(audit_router)
router.include_router(gap_router)
router.include_router(settings_router)
router.include_router(search_router)
router.include_router(compliance_router)
router.include_router(chat_router)
router.include_router(history_router)
