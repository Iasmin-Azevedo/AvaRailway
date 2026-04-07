from datetime import datetime
import re

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.aluno import Aluno
from app.models.relacoes import ProfessorTurma
from app.models.user import UserRole, Usuario
from app.repositories.live_support_repository import (
    AulaAoVivoRepository,
    SolicitacaoProfessorRepository,
)
from app.schemas.live_support_schema import (
    AulaAoVivoCreateRequest,
    SolicitacaoProfessorCreateRequest,
)


class LiveSupportService:
    """Orquestra agenda de aulas ao vivo e pedidos de apoio ao professor."""

    def __init__(self, db: Session):
        self.db = db
        self.aula_repo = AulaAoVivoRepository()
        self.solicitacao_repo = SolicitacaoProfessorRepository()

    def _slugify_room(self, text: str) -> str:
        value = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower())
        value = re.sub(r"-+", "-", value).strip("-")
        return value or "sala-ava-mj"

    def _build_room_name(self, user: Usuario, payload: AulaAoVivoCreateRequest) -> str:
        return f"ava-mj-{payload.turma_id}-{self._slugify_room(payload.disciplina)}-{self._slugify_room(payload.titulo)}-{user.id}"

    def _build_meeting_url(self, room_name: str, external_url: str | None) -> tuple[str, str]:
        if external_url:
            return "externo", external_url.strip()
        base_url = settings.JITSI_BASE_URL.rstrip("/")
        return "jitsi", f"{base_url}/{room_name}"

    def _serialize_live_class(self, item):
        return {
            "id": item.id,
            "professor_id": item.professor_id,
            "turma_id": item.turma_id,
            "disciplina": item.disciplina,
            "titulo": item.titulo,
            "descricao": item.descricao,
            "meeting_provider": item.meeting_provider,
            "room_name": item.room_name,
            "meeting_url": item.meeting_url,
            "scheduled_at": item.scheduled_at,
            "duration_minutes": item.duration_minutes,
            "ativa": item.ativa,
            "created_at": item.created_at,
            "join_path": f"/ao-vivo/{item.id}",
        }

    def create_live_class(self, user: Usuario, payload: AulaAoVivoCreateRequest):
        if user.role != UserRole.PROFESSOR:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Somente professores podem agendar aulas ao vivo.",
            )

        professor_turmas = {
            rel.turma_id
            for rel in self.db.query(ProfessorTurma).filter(ProfessorTurma.professor_id == user.id).all()
        }
        if payload.turma_id not in professor_turmas:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="A turma informada nao esta vinculada ao professor autenticado.",
            )
        if payload.scheduled_at <= datetime.utcnow():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A aula ao vivo precisa ser agendada para uma data futura.",
            )

        room_name = self._build_room_name(user, payload)
        meeting_provider, meeting_url = self._build_meeting_url(room_name, payload.meeting_url)

        created = self.aula_repo.create(
            self.db,
            {
                "professor_id": user.id,
                "turma_id": payload.turma_id,
                "disciplina": payload.disciplina.strip(),
                "titulo": payload.titulo.strip(),
                "descricao": (payload.descricao or "").strip() or None,
                "meeting_provider": meeting_provider,
                "room_name": room_name,
                "meeting_url": meeting_url,
                "scheduled_at": payload.scheduled_at,
                "duration_minutes": payload.duration_minutes,
                "ativa": True,
            },
        )
        return self._serialize_live_class(created)

    def list_live_classes_for_student(self, user: Usuario):
        aluno = self.db.query(Aluno).filter(Aluno.usuario_id == user.id).first()
        if not aluno or not aluno.turma_id:
            return []
        return [
            self._serialize_live_class(item)
            for item in self.aula_repo.list_upcoming_for_turma(self.db, aluno.turma_id)
        ]

    def list_live_classes_for_professor(self, user: Usuario):
        if user.role != UserRole.PROFESSOR:
            return []
        return [
            self._serialize_live_class(item)
            for item in self.aula_repo.list_upcoming_for_professor(self.db, user.id)
        ]

    def get_live_class_for_user(self, user: Usuario, live_class_id: int) -> dict:
        item = self.aula_repo.get(self.db, live_class_id)
        if not item or not item.ativa:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Aula ao vivo nao encontrada.")

        role = getattr(user.role, "value", user.role)
        if role == "professor" and item.professor_id != user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acesso nao autorizado a esta aula.")

        if role == "aluno":
            aluno = self.db.query(Aluno).filter(Aluno.usuario_id == user.id).first()
            if not aluno or aluno.turma_id != item.turma_id:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acesso nao autorizado a esta aula.")

        return self._serialize_live_class(item)

    def create_teacher_help_request(self, user: Usuario, payload: SolicitacaoProfessorCreateRequest):
        aluno = self.db.query(Aluno).filter(Aluno.usuario_id == user.id).first()
        turma_id = aluno.turma_id if aluno else None
        professor_id = None

        if turma_id is not None:
            rel = (
                self.db.query(ProfessorTurma)
                .filter(ProfessorTurma.turma_id == turma_id)
                .order_by(ProfessorTurma.professor_id.asc())
                .first()
            )
            professor_id = rel.professor_id if rel else None

        return self.solicitacao_repo.create(
            self.db,
            {
                "requester_user_id": user.id,
                "professor_id": professor_id,
                "turma_id": turma_id,
                "disciplina": payload.disciplina.strip(),
                "assunto": payload.assunto.strip(),
                "requester_role": getattr(user.role, "value", str(user.role)),
                "session_id": payload.session_id,
                "status": "pendente",
                "origem": "chatbot",
            },
        )

    def list_teacher_help_requests(self, user: Usuario):
        if user.role != UserRole.PROFESSOR:
            return []
        return self.solicitacao_repo.list_for_professor(self.db, user.id)
