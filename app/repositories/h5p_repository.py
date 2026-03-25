from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime

from app.models.h5p import AtividadeH5P, ProgressoH5P
from app.schemas.h5p_schema import AtividadeH5PCreate, AtividadeH5PUpdate


class AtividadeH5PRepository:
    def listar(
        self,
        db: Session,
        trilha_id: Optional[int] = None,
        ativo_only: bool = True,
    ) -> List[AtividadeH5P]:
        q = db.query(AtividadeH5P)
        if trilha_id is not None:
            q = q.filter(AtividadeH5P.trilha_id == trilha_id)
        if ativo_only:
            q = q.filter(AtividadeH5P.ativo == True)
        return q.order_by(AtividadeH5P.ordem, AtividadeH5P.titulo).all()

    def get(self, db: Session, id: int) -> Optional[AtividadeH5P]:
        return db.query(AtividadeH5P).filter(AtividadeH5P.id == id).first()

    def create(self, db: Session, data: AtividadeH5PCreate) -> AtividadeH5P:
        obj = AtividadeH5P(
            titulo=data.titulo,
            tipo=data.tipo,
            path_ou_json=data.path_ou_json,
            trilha_id=data.trilha_id,
            descritor_id=data.descritor_id,
            ordem=data.ordem,
            ativo=data.ativo,
        )
        db.add(obj)
        db.commit()
        db.refresh(obj)
        return obj

    def update(self, db: Session, id: int, data: AtividadeH5PUpdate) -> Optional[AtividadeH5P]:
        obj = self.get(db, id)
        if not obj:
            return None
        if data.titulo is not None:
            obj.titulo = data.titulo
        if data.tipo is not None:
            obj.tipo = data.tipo
        if data.path_ou_json is not None:
            obj.path_ou_json = data.path_ou_json
        if data.trilha_id is not None:
            obj.trilha_id = data.trilha_id
        if data.descritor_id is not None:
            obj.descritor_id = data.descritor_id
        if data.ordem is not None:
            obj.ordem = data.ordem
        if data.ativo is not None:
            obj.ativo = data.ativo
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


class ProgressoH5PRepository:
    def get_or_create(
        self, db: Session, aluno_id: int, atividade_id: int
    ) -> ProgressoH5P:
        p = (
            db.query(ProgressoH5P)
            .filter(
                ProgressoH5P.aluno_id == aluno_id,
                ProgressoH5P.atividade_id == atividade_id,
            )
            .first()
        )
        if p:
            return p
        p = ProgressoH5P(aluno_id=aluno_id, atividade_id=atividade_id)
        db.add(p)
        db.commit()
        db.refresh(p)
        return p

    def marcar_concluido(
        self,
        db: Session,
        aluno_id: int,
        atividade_id: int,
        score: Optional[float] = None,
    ) -> ProgressoH5P:
        p = self.get_or_create(db, aluno_id, atividade_id)
        p.concluido = True
        p.score = score
        p.data_conclusao = datetime.utcnow()
        p.tentativas += 1
        db.commit()
        db.refresh(p)
        return p

    def listar_por_aluno(self, db: Session, aluno_id: int) -> List[ProgressoH5P]:
        return (
            db.query(ProgressoH5P)
            .filter(ProgressoH5P.aluno_id == aluno_id)
            .all()
        )
