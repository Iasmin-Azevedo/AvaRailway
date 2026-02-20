from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from app.repositories.user_repository import UserRepository
from app.core.security import verificar_senha, criar_token_acesso
from app.schemas.auth_schema import LoginRequest

class AuthService:
    def __init__(self):
        self.user_repo = UserRepository()

    def login(self, db: Session, dados: LoginRequest):
        user = self.user_repo.get_by_email(db, dados.email)
        if not user or not verificar_senha(dados.senha, user.senha_hash):
            raise HTTPException(status_code=401, detail="Credenciais inválidas")
        
        token = criar_token_acesso(data={"sub": user.email, "role": user.role})
        return {"access_token": token, "token_type": "bearer"}