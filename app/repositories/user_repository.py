from sqlalchemy.orm import Session
from typing import List, Optional
from app.models.user import Usuario, UserRole
from app.schemas.user_schema import UserCreate
from app.core.security import get_password_hash

class UserRepository:
    def get_by_email(self, db: Session, email: str) -> Optional[Usuario]:
        return db.query(Usuario).filter(Usuario.email == email).first()

    def get_by_id(self, db: Session, id: int) -> Optional[Usuario]:
        return db.query(Usuario).filter(Usuario.id == id).first()

    def listar(
        self,
        db: Session,
        role: Optional[UserRole] = None,
        ativo_only: bool = True,
    ) -> List[Usuario]:
        q = db.query(Usuario)
        if role is not None:
            q = q.filter(Usuario.role == role)
        if ativo_only:
            q = q.filter(Usuario.ativo == True)
        return q.order_by(Usuario.nome).all()

    def create(self, db: Session, user: UserCreate) -> Usuario:
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

    def update(
        self,
        db: Session,
        id: int,
        nome: Optional[str] = None,
        email: Optional[str] = None,
        senha: Optional[str] = None,
        role: Optional[UserRole] = None,
        ativo: Optional[bool] = None,
    ) -> Optional[Usuario]:
        obj = self.get_by_id(db, id)
        if not obj:
            return None
        if nome is not None:
            obj.nome = nome
        if email is not None:
            obj.email = email
        if senha is not None:
            obj.senha_hash = get_password_hash(senha)
        if role is not None:
            obj.role = role
        if ativo is not None:
            obj.ativo = ativo
        db.commit()
        db.refresh(obj)
        return obj

    def delete(self, db: Session, id: int) -> bool:
        obj = self.get_by_id(db, id)
        if not obj:
            return False
        db.delete(obj)
        db.commit()
        return True