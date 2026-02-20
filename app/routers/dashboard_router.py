from fastapi import APIRouter, Request
from app.core.security import limiter

router = APIRouter()

@router.get("/dashboard/gestor")
@limiter.limit("5/minute")
def dashboard_gestor(request: Request):
    return {
        "indicadores": {
            "media_geral": 7.5,
            "risco_critico": 12
        }
    }