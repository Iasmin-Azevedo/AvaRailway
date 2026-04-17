from datetime import datetime

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.models.aluno import Aluno
from app.models.live_support import AulaAoVivo, SolicitacaoProfessor
from app.models.relacoes import ProfessorTurma


class AulaAoVivoRepository:
    model = AulaAoVivo

    def create(self, db: Session, data: dict) -> AulaAoVivo:
        obj = AulaAoVivo(**data)
        db.add(obj)
        db.commit()
        db.refresh(obj)
        return obj

    def list_upcoming_for_turma(self, db: Session, turma_id: int, limit: int = 5) -> list[AulaAoVivo]:
        return (
            db.query(AulaAoVivo)
            .filter(
                AulaAoVivo.turma_id == turma_id,
                AulaAoVivo.ativa == True,
                AulaAoVivo.scheduled_at >= datetime.utcnow(),
            )
            .order_by(AulaAoVivo.scheduled_at.asc())
            .limit(limit)
            .all()
        )

    def list_upcoming_for_professor(self, db: Session, professor_id: int, limit: int = 10) -> list[AulaAoVivo]:
        return (
            db.query(AulaAoVivo)
            .filter(
                AulaAoVivo.professor_id == professor_id,
                AulaAoVivo.ativa == True,
                AulaAoVivo.scheduled_at >= datetime.utcnow(),
            )
            .order_by(AulaAoVivo.scheduled_at.asc())
            .limit(limit)
            .all()
        )

    def get(self, db: Session, live_class_id: int) -> AulaAoVivo | None:
        return db.query(AulaAoVivo).filter(AulaAoVivo.id == live_class_id).first()


class SolicitacaoProfessorRepository:
    def create(self, db: Session, data: dict) -> SolicitacaoProfessor:
        obj = SolicitacaoProfessor(**data)
        db.add(obj)
        db.commit()
        db.refresh(obj)
        return obj

    def _turma_ids_do_professor(self, db: Session, professor_usuario_id: int) -> list[int]:
        return [
            r[0]
            for r in db.query(ProfessorTurma.turma_id)
            .filter(ProfessorTurma.professor_id == professor_usuario_id)
            .all()
        ]

    def _usuario_ids_alunos_nas_turmas(self, db: Session, turma_ids: list[int]) -> list[int]:
        if not turma_ids:
            return []
        rows = (
            db.query(Aluno.usuario_id)
            .filter(Aluno.turma_id.in_(turma_ids))
            .distinct()
            .all()
        )
        return [r[0] for r in rows]

    def _filtro_legado_sem_vinculo(self):
        """Registros antigos sem professor/turma vinculados explicitamente."""
        return and_(
            SolicitacaoProfessor.professor_id.is_(None),
            SolicitacaoProfessor.turma_id.is_(None),
        )

    def list_for_professor(
        self,
        db: Session,
        professor_usuario_id: int,
        limit: int = 10,
        turma_ids: list[int] | None = None,
    ) -> list[SolicitacaoProfessor]:
        """Solicitações visíveis ao docente: atribuídas a si, turmas em que leciona ou pedidos de alunos dessas turmas."""
        turmas_docente = self._turma_ids_do_professor(db, professor_usuario_id)
        vis = SolicitacaoProfessor.professor_id == professor_usuario_id
        vis = or_(vis, self._filtro_legado_sem_vinculo())
        if turmas_docente:
            vis = or_(vis, SolicitacaoProfessor.turma_id.in_(turmas_docente))
            alum_docente = self._usuario_ids_alunos_nas_turmas(db, turmas_docente)
            if alum_docente:
                vis = or_(vis, SolicitacaoProfessor.requester_user_id.in_(alum_docente))
        q = db.query(SolicitacaoProfessor).filter(vis)
        if turma_ids is not None:
            alum_filtro = self._usuario_ids_alunos_nas_turmas(db, turma_ids)
            tfilter = SolicitacaoProfessor.turma_id.in_(turma_ids)
            if alum_filtro:
                tfilter = or_(tfilter, SolicitacaoProfessor.requester_user_id.in_(alum_filtro))
            tfilter = or_(tfilter, self._filtro_legado_sem_vinculo())
            q = q.filter(tfilter)
        return (
            q.order_by(SolicitacaoProfessor.created_at.desc())
            .limit(limit)
            .all()
        )

    def get_for_professor(self, db: Session, professor_usuario_id: int, request_id: int) -> SolicitacaoProfessor | None:
        turmas_docente = self._turma_ids_do_professor(db, professor_usuario_id)
        vis = SolicitacaoProfessor.professor_id == professor_usuario_id
        vis = or_(vis, self._filtro_legado_sem_vinculo())
        if turmas_docente:
            vis = or_(vis, SolicitacaoProfessor.turma_id.in_(turmas_docente))
            alum_docente = self._usuario_ids_alunos_nas_turmas(db, turmas_docente)
            if alum_docente:
                vis = or_(vis, SolicitacaoProfessor.requester_user_id.in_(alum_docente))
        return (
            db.query(SolicitacaoProfessor)
            .filter(SolicitacaoProfessor.id == request_id)
            .filter(vis)
            .first()
        )
