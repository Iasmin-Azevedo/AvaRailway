from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.schemas.auth_schema import LoginRequest, RefreshTokenResponse, TokenResponse
from app.services.auth_service import AuthService

router = APIRouter()
service = AuthService()


def _safe_internal_path(raw: str | None, fallback: str) -> str:
    if not raw or not isinstance(raw, str):
        return fallback
    s = raw.strip()
    if not s.startswith("/") or s.startswith("//"):
        return fallback
    return s


def _role_redirect_path(role) -> str:
    role_value = getattr(role, "value", role)
    role_value = str(role_value).strip().lower()
    if role_value == "aluno":
        return "/aluno"
    if role_value == "professor":
        return "/professor"
    if role_value == "coordenador":
        return "/coordenador"
    if role_value == "gestor":
        return "/gestor"
    if role_value == "admin":
        return "/admin"
    return "/"


@router.post("/login", response_model=TokenResponse)
async def login(request: Request, db: Session = Depends(get_db)):
    content_type = request.headers.get("content-type", "")
    accepts_html = "text/html" in request.headers.get("accept", "")

    if "application/json" in content_type:
        payload = await request.json()
        dados = LoginRequest(**payload)
        return service.login(db, dados, request.client.host if request.client else None)

    form = await request.form()
    dados = LoginRequest(email=form.get("email"), senha=form.get("senha"))
    token = service.login(db, dados, request.client.host if request.client else None)
    user = service.user_repo.get_by_email(db, dados.email)
    default_dest = _role_redirect_path(user.role if user else None)
    redirect_url = _safe_internal_path(form.get("next"), default_dest)

    if accepts_html:
        response = RedirectResponse(url=redirect_url, status_code=303)
        response.set_cookie(
            key=settings.ACCESS_COOKIE_NAME,
            value=token["access_token"],
            httponly=True,
            secure=settings.COOKIE_SECURE,
            samesite="lax",
            domain=settings.COOKIE_DOMAIN,
        )
        response.set_cookie(
            key=settings.REFRESH_COOKIE_NAME,
            value=token["refresh_token"],
            httponly=True,
            secure=settings.COOKIE_SECURE,
            samesite="lax",
            domain=settings.COOKIE_DOMAIN,
        )
        return response

    return JSONResponse(content=token)


@router.post("/refresh", response_model=RefreshTokenResponse)
def refresh_token(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get(settings.REFRESH_COOKIE_NAME)
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1]
    if not token:
        raise HTTPException(status_code=401, detail="Refresh token ausente")

    refreshed = service.refresh(db, token, request.client.host if request.client else None)
    response = JSONResponse(content=refreshed)
    response.set_cookie(
        key=settings.ACCESS_COOKIE_NAME,
        value=refreshed["access_token"],
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
        domain=settings.COOKIE_DOMAIN,
    )
    return response


@router.get("/logout")
def logout():
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(key=settings.ACCESS_COOKIE_NAME, path="/", domain=settings.COOKIE_DOMAIN)
    response.delete_cookie(key=settings.REFRESH_COOKIE_NAME, path="/", domain=settings.COOKIE_DOMAIN)
    return response
