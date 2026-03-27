import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
limiter = Limiter(key_func=get_remote_address)


def _senha_para_bcrypt(senha: str) -> str:
    senha_bytes = senha.encode("utf-8")
    if len(senha_bytes) > 72:
        return hashlib.sha256(senha_bytes).hexdigest()
    return senha


def criar_token(data: dict[str, Any], expires_minutes: int, token_type: str) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
    to_encode.update({"exp": expire, "type": token_type})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def criar_token_acesso(data: dict[str, Any]) -> str:
    return criar_token(data=data, expires_minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES, token_type="access")


def criar_refresh_token(data: dict[str, Any]) -> str:
    return criar_token(data=data, expires_minutes=settings.REFRESH_TOKEN_EXPIRE_MINUTES, token_type="refresh")


def decodificar_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])


def validar_tipo_token(token: str, expected_type: str) -> dict[str, Any]:
    payload = decodificar_token(token)
    token_type = payload.get("type")
    if token_type != expected_type:
        raise JWTError("Tipo de token invalido")
    return payload


def get_password_hash(senha):
    return pwd_context.hash(_senha_para_bcrypt(senha))


def verificar_senha(senha_plana, senha_hash):
    if pwd_context.verify(senha_plana, senha_hash):
        return True
    return pwd_context.verify(_senha_para_bcrypt(senha_plana), senha_hash)
