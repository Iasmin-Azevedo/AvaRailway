from datetime import datetime

from sqlalchemy.orm import Session

from app.models.live_support import AulaAoVivo, SolicitacaoProfessor


class AulaAoVivoRepository:
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

    def list_for_professor(self, db: Session, professor_id: int, limit: int = 10) -> list[SolicitacaoProfessor]:
        return (
            db.query(SolicitacaoProfessor)
            .filter(SolicitacaoProfessor.professor_id == professor_id)
            .order_by(SolicitacaoProfessor.created_at.desc())
            .limit(limit)
            .all()
        )

    def get_for_professor(self, db: Session, professor_id: int, request_id: int) -> SolicitacaoProfessor | None:
        return (
            db.query(SolicitacaoProfessor)
            .filter(
                SolicitacaoProfessor.id == request_id,
                SolicitacaoProfessor.professor_id == professor_id,
            )
            .first()
        )
