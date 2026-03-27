from fastapi import Depends, HTTPException, Request, status
from jose import JWTError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import validar_tipo_token
from app.models.user import UserRole, Usuario
from app.repositories.user_repository import UserRepository


def _get_token(request: Request) -> str | None:
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header.split(" ", 1)[1]
    return request.cookies.get(settings.ACCESS_COOKIE_NAME)


def get_current_user(request: Request, db: Session = Depends(get_db)) -> Usuario:
    token = _get_token(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Nao autenticado",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = validar_tipo_token(token, "access")
        email = payload.get("sub")
        if not email:
            raise HTTPException(status_code=401, detail="Token invalido")
    except JWTError:
        raise HTTPException(status_code=401, detail="Token invalido ou expirado")

    repo = UserRepository()
    user = repo.get_by_email(db, email)
    if not user or not user.ativo:
        raise HTTPException(status_code=401, detail="Usuario inativo ou nao encontrado")
    return user


def require_admin(current_user: Usuario = Depends(get_current_user)) -> Usuario:
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso restrito a administradores",
        )
    return current_user


def get_current_user_optional(request: Request, db: Session = Depends(get_db)) -> Usuario | None:
    token = _get_token(request)
    if not token:
        return None
    try:
        payload = validar_tipo_token(token, "access")
        email = payload.get("sub")
        if not email:
            return None
    except JWTError:
        return None

    repo = UserRepository()
    user = repo.get_by_email(db, email)
    if not user or not user.ativo:
        return None
    return user


def require_admin_redirect(
    request: Request,
    current_user: Usuario | None = Depends(get_current_user_optional),
):
    from fastapi.responses import RedirectResponse

    if current_user is None:
        return RedirectResponse(url="/login", status_code=302)
    if current_user.role != UserRole.ADMIN:
        return RedirectResponse(url="/", status_code=302)
    return current_user


def require_role_redirect(*allowed_roles: UserRole):
    def _require(
        request: Request,
        current_user: Usuario | None = Depends(get_current_user_optional),
    ):
        from fastapi.responses import RedirectResponse

        if current_user is None:
            return RedirectResponse(url="/login", status_code=302)
        if current_user.role not in allowed_roles:
            return RedirectResponse(url="/", status_code=302)
        return current_user

    return _require
