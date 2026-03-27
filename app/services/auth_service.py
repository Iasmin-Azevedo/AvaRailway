from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import (
    criar_refresh_token,
    criar_token_acesso,
    validar_tipo_token,
    verificar_senha,
)
from app.models.user import AuditLog
from app.repositories.user_repository import UserRepository
from app.schemas.auth_schema import LoginRequest


class AuthService:
    def __init__(self):
        self.user_repo = UserRepository()

    def _registrar_auditoria(
        self,
        db: Session,
        user_id: int | None,
        acao: str,
        detalhes: str,
        ip: str | None = None,
    ) -> None:
        db.add(AuditLog(usuario_id=user_id, acao=acao, detalhes=detalhes, ip=ip))
        db.commit()

    def login(self, db: Session, dados: LoginRequest, ip: str | None = None):
        user = self.user_repo.get_by_email(db, dados.email)
        if not user or not user.ativo or not verificar_senha(dados.senha, user.senha_hash):
            self._registrar_auditoria(
                db,
                user.id if user else None,
                "login_falhou",
                f"Tentativa de login para {dados.email}",
                ip,
            )
            raise HTTPException(status_code=401, detail="Credenciais invalidas")

        access_token = criar_token_acesso(data={"sub": user.email, "role": user.role})
        refresh_token = criar_refresh_token(data={"sub": user.email, "role": user.role})
        self._registrar_auditoria(db, user.id, "login_sucesso", "Usuario autenticado com sucesso", ip)
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
        }

    def refresh(self, db: Session, refresh_token: str, ip: str | None = None):
        try:
            payload = validar_tipo_token(refresh_token, "refresh")
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token invalido ou expirado",
            )

        email = payload.get("sub")
        user = self.user_repo.get_by_email(db, email)
        if not user or not user.ativo:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Usuario inativo ou nao encontrado",
            )

        access_token = criar_token_acesso(data={"sub": user.email, "role": user.role})
        self._registrar_auditoria(db, user.id, "refresh_token", "Token renovado com sucesso", ip)
        return {"access_token": access_token, "token_type": "bearer"}
