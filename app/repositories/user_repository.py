from sqlalchemy.orm import Session
from app.models.user import Usuario
from app.schemas.user_schema import UserCreate
from app.core.security import get_password_hash

class UserRepository:
    def get_by_email(self, db: Session, email: str):
        return db.query(Usuario).filter(Usuario.email == email).first()

    def create(self, db: Session, user: UserCreate):
        db_user = Usuario(
            nome=user.nome,
            email=user.email,
            senha_hash=get_password_hash(user.senha),
            role=user.role
        )
        db.add(db_user)
        db.commit()
        db.refresh(db_user)
        return db_user