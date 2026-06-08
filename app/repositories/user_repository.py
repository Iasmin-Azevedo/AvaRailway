from sqlalchemy import or_
from sqlalchemy.orm import Session
from typing import List, Optional
from app.models.user import AdminScope, TeacherRole, Usuario, UserRole
from app.schemas.user_schema import UserCreate
from app.core.security import get_password_hash

_UNSET = object()


class UserRepository:
    def get_by_email(self, db: Session, email: str) -> Optional[Usuario]:
        return db.query(Usuario).filter(Usuario.email == email).first()

    def get_by_id(self, db: Session, id: int) -> Optional[Usuario]:
        return db.query(Usuario).filter(Usuario.id == id).first()

    def listar(
        self,
        db: Session,
        role: Optional[UserRole] = None,
        admin_scope: Optional[AdminScope] = None,
        search: Optional[str] = None,
        ativo_only: bool = True,
    ) -> List[Usuario]:
        q = db.query(Usuario)
        if role is not None:
            q = q.filter(Usuario.role == role)
        if admin_scope is not None:
            q = q.filter(Usuario.role == UserRole.ADMIN)
            if admin_scope == AdminScope.PLATAFORMA:
                q = q.filter(
                    or_(
                        Usuario.escopo_administrativo == AdminScope.PLATAFORMA,
                        Usuario.escopo_administrativo.is_(None),
                    )
                )
            else:
                q = q.filter(Usuario.escopo_administrativo == admin_scope)
        if ativo_only:
            q = q.filter(Usuario.ativo == True)
        if search:
            term = f"%{search.strip()}%"
            q = q.filter(or_(Usuario.nome.ilike(term), Usuario.email.ilike(term)))
        return q.order_by(Usuario.nome).all()

    def create(self, db: Session, user: UserCreate) -> Usuario:
        db_user = Usuario(
            nome=user.nome,
            email=user.email,
            senha_hash=get_password_hash(user.senha),
            role=user.role,
            permite_cadastro_trilha_geral=bool(getattr(user, "permite_cadastro_trilha_geral", False)),
            funcao_docente=getattr(user, "funcao_docente", None),
            escopo_administrativo=getattr(user, "escopo_administrativo", None),
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
        permite_cadastro_trilha_geral: Optional[bool] = None,
        funcao_docente: Optional[TeacherRole] | object = _UNSET,
        escopo_administrativo: Optional[AdminScope] | object = _UNSET,
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
        if permite_cadastro_trilha_geral is not None:
            obj.permite_cadastro_trilha_geral = bool(permite_cadastro_trilha_geral)
        if funcao_docente is not _UNSET:
            obj.funcao_docente = funcao_docente
        if escopo_administrativo is not _UNSET:
            obj.escopo_administrativo = escopo_administrativo
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