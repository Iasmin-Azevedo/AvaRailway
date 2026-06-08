from sqlalchemy.orm import Session
from typing import List, Optional

from app.core.catalogs import FUNDAMENTAL_SUBJECTS
from app.models.gestao import Escola, Turma, Curso, Trilha
from app.schemas.gestao_schema import (
    EscolaCreate,
    EscolaUpdate,
    TurmaCreate,
    TurmaUpdate,
    CursoCreate,
    CursoUpdate,
    TrilhaCreate,
    TrilhaUpdate,
)


class EscolaRepository:
    def listar(self, db: Session, ativo_only: bool = False) -> List[Escola]:
        q = db.query(Escola)
        if ativo_only:
            q = q.filter(Escola.ativo == True)
        return q.order_by(Escola.nome).all()

    def get(self, db: Session, id: int) -> Optional[Escola]:
        return db.query(Escola).filter(Escola.id == id).first()

    def create(self, db: Session, data: EscolaCreate) -> Escola:
        obj = Escola(nome=data.nome, ativo=data.ativo, endereco=data.endereco)
        db.add(obj)
        db.commit()
        db.refresh(obj)
        return obj

    def update(self, db: Session, id: int, data: EscolaUpdate) -> Optional[Escola]:
        obj = self.get(db, id)
        if not obj:
            return None
        if data.nome is not None:
            obj.nome = data.nome
        if data.ativo is not None:
            obj.ativo = data.ativo
        if data.endereco is not None:
            obj.endereco = data.endereco
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


class TurmaRepository:
    @staticmethod
    def build_nome(ano_escolar: int, sigla: Optional[str] = None) -> str:
        sigla_limpa = (sigla or "").strip().upper()
        return f"{ano_escolar}º ano {sigla_limpa}".strip()

    def listar(
        self,
        db: Session,
        escola_id: Optional[int] = None,
        ano_escolar: Optional[int] = None,
    ) -> List[Turma]:
        q = db.query(Turma)
        if escola_id is not None:
            q = q.filter(Turma.escola_id == escola_id)
        if ano_escolar is not None:
            q = q.filter(Turma.ano_escolar == ano_escolar)
        return q.order_by(Turma.escola_id, Turma.ano_escolar, Turma.sigla, Turma.nome).all()

    def get(self, db: Session, id: int) -> Optional[Turma]:
        return db.query(Turma).filter(Turma.id == id).first()

    def create(self, db: Session, data: TurmaCreate) -> Turma:
        obj = Turma(
            nome=self.build_nome(data.ano_escolar, data.sigla),
            sigla=(data.sigla or "").strip().upper() or None,
            ano_escolar=data.ano_escolar,
            escola_id=data.escola_id,
            ano_letivo=data.ano_letivo,
        )
        db.add(obj)
        db.commit()
        db.refresh(obj)
        return obj

    def update(self, db: Session, id: int, data: TurmaUpdate) -> Optional[Turma]:
        obj = self.get(db, id)
        if not obj:
            return None
        next_sigla = obj.sigla
        next_ano = obj.ano_escolar
        if data.sigla is not None:
            next_sigla = (data.sigla or "").strip().upper() or None
        if data.ano_escolar is not None:
            next_ano = data.ano_escolar
        if data.escola_id is not None:
            obj.escola_id = data.escola_id
        if data.ano_letivo is not None:
            obj.ano_letivo = data.ano_letivo
        obj.sigla = next_sigla
        obj.ano_escolar = next_ano
        obj.nome = self.build_nome(next_ano, next_sigla)
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


class CursoRepository:
    @staticmethod
    def _ensure_default_courses(db: Session) -> None:
        existentes = {str(nome).strip().lower() for (nome,) in db.query(Curso.nome).all()}
        novos = [Curso(nome=nome) for nome in FUNDAMENTAL_SUBJECTS if nome.strip().lower() not in existentes]
        if novos:
            db.add_all(novos)
            db.commit()

    def listar(self, db: Session) -> List[Curso]:
        self._ensure_default_courses(db)
        return db.query(Curso).order_by(Curso.nome).all()

    def get(self, db: Session, id: int) -> Optional[Curso]:
        self._ensure_default_courses(db)
        return db.query(Curso).filter(Curso.id == id).first()

    def create(self, db: Session, data: CursoCreate) -> Curso:
        obj = Curso(nome=data.nome)
        db.add(obj)
        db.commit()
        db.refresh(obj)
        return obj

    def update(self, db: Session, id: int, data: CursoUpdate) -> Optional[Curso]:
        obj = self.get(db, id)
        if not obj:
            return None
        if data.nome is not None:
            obj.nome = data.nome
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


class TrilhaRepository:
    def listar(
        self,
        db: Session,
        curso_id: Optional[int] = None,
        ano_escolar: Optional[int] = None,
    ) -> List[Trilha]:
        q = db.query(Trilha)
        if curso_id is not None:
            q = q.filter(Trilha.curso_id == curso_id)
        if ano_escolar is not None:
            q = q.filter(
                (Trilha.ano_escolar == ano_escolar) | (Trilha.ano_escolar.is_(None))
            )
        return q.order_by(Trilha.curso_id, Trilha.ordem, Trilha.nome).all()

    def get(self, db: Session, id: int) -> Optional[Trilha]:
        return db.query(Trilha).filter(Trilha.id == id).first()

    def create(self, db: Session, data: TrilhaCreate) -> Trilha:
        obj = Trilha(
            nome=data.nome,
            curso_id=data.curso_id,
            ano_escolar=data.ano_escolar,
            semestre=data.semestre,
            ordem=data.ordem,
        )
        db.add(obj)
        db.commit()
        db.refresh(obj)
        return obj

    def update(self, db: Session, id: int, data: TrilhaUpdate) -> Optional[Trilha]:
        obj = self.get(db, id)
        if not obj:
            return None
        if data.nome is not None:
            obj.nome = data.nome
        if data.curso_id is not None:
            obj.curso_id = data.curso_id
        if data.ano_escolar is not None:
            obj.ano_escolar = data.ano_escolar
        if data.semestre is not None:
            obj.semestre = data.semestre
        if data.ordem is not None:
            obj.ordem = data.ordem
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
