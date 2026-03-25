from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.schemas.auth_schema import LoginRequest, TokenResponse
from app.services.auth_service import AuthService

router = APIRouter()
service = AuthService()


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
        return service.login(db, dados)

    form = await request.form()
    dados = LoginRequest(email=form.get("email"), senha=form.get("senha"))
    token = service.login(db, dados)
    user = service.user_repo.get_by_email(db, dados.email)
    redirect_url = _role_redirect_path(user.role if user else None)

    if accepts_html:
        response = RedirectResponse(url=redirect_url, status_code=303)
        response.set_cookie(
            key="access_token",
            value=token["access_token"],
            httponly=True,
            secure=False,
            samesite="lax",
        )
        return response

    return JSONResponse(content=token)


@router.get("/logout")
def logout():
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(key="access_token", path="/")
    return response