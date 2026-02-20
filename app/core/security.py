from passlib.context import CryptContext
from datetime import datetime, timedelta
import hashlib
from jose import jwt
from app.core.config import settings
from slowapi import Limiter
from slowapi.util import get_remote_address

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
limiter = Limiter(key_func=get_remote_address)


def _senha_para_bcrypt(senha: str) -> str:
    """
    Bcrypt aceita no maximo 72 bytes.
    Para manter compatibilidade com entradas longas, usa SHA-256 em hex.
    """
    senha_bytes = senha.encode("utf-8")
    if len(senha_bytes) > 72:
        return hashlib.sha256(senha_bytes).hexdigest()
    return senha

def criar_token_acesso(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

def get_password_hash(senha):
    return pwd_context.hash(_senha_para_bcrypt(senha))

def verificar_senha(senha_plana, senha_hash):
    # Compatibilidade com hashes antigos (senha direta)
    if pwd_context.verify(senha_plana, senha_hash):
        return True
    # Compatibilidade com hashes novos (senha preprocessada)
    return pwd_context.verify(_senha_para_bcrypt(senha_plana), senha_hash)