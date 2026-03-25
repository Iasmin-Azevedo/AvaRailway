from sqlalchemy.orm import Session
from typing import List, Optional

from app.models.saeb import Descritor


class DescritorRepository:
    def listar(
        self,
        db: Session,
        disciplina: Optional[str] = None,
    ) -> List[Descritor]:
        q = db.query(Descritor)
        if disciplina:
            q = q.filter(Descritor.disciplina == disciplina)
        return q.order_by(Descritor.codigo).all()

    def get(self, db: Session, id: int) -> Optional[Descritor]:
        return db.query(Descritor).filter(Descritor.id == id).first()

    def get_by_codigo(self, db: Session, codigo: str) -> Optional[Descritor]:
        return db.query(Descritor).filter(Descritor.codigo == codigo).first()

    def create(
        self,
        db: Session,
        codigo: str,
        descricao: str,
        disciplina: str,
    ) -> Descritor:
        obj = Descritor(codigo=codigo, descricao=descricao, disciplina=disciplina)
        db.add(obj)
        db.commit()
        db.refresh(obj)
        return obj

    def update(
        self,
        db: Session,
        id: int,
        codigo: Optional[str] = None,
        descricao: Optional[str] = None,
        disciplina: Optional[str] = None,
    ) -> Optional[Descritor]:
        obj = self.get(db, id)
        if not obj:
            return None
        if codigo is not None:
            obj.codigo = codigo
        if descricao is not None:
            obj.descricao = descricao
        if disciplina is not None:
            obj.disciplina = disciplina
        db.commit()
        db.refresh(obj)
        return obj

    def delete(self, db: Session, id: int) -> bool:
        obj = self.get(db, id)
        if not obj:
            return False
        db.delete(obj)
        db.commit()
        return True
