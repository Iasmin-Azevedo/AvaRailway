from datetime import datetime, timezone
import re

from fastapi import HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.aluno import Aluno
from app.models.gestao import Turma
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
        scope_ref = payload.turma_id or payload.escola_id or "rede"
        return (
            f"ava-mj-{scope_ref}-{self._slugify_room(payload.disciplina)}-"
            f"{self._slugify_room(payload.titulo)}-{user.id}"
        )

    def _build_meeting_url(self, room_name: str, external_url: str | None) -> tuple[str, str]:
        # Fluxo simplificado: sempre usa sala interna Jitsi.
        base_url = settings.JITSI_BASE_URL.rstrip("/")
        return "jitsi", f"{base_url}/{room_name}"

    def _to_naive_utc(self, value: datetime) -> datetime:
        """
        Normaliza datetime para UTC sem timezone (naive), compatível com a coluna DateTime atual.
        """
        if value.tzinfo is None:
            return value
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def _serialize_live_class(self, item):
        return {
            "id": item.id,
            "organizador_user_id": item.organizador_user_id,
            "professor_id": item.professor_id,
            "turma_id": item.turma_id,
            "escola_id": item.escola_id,
            "audience_role": item.audience_role,
            "audience_scope": item.audience_scope,
            "target_label": item.target_label,
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

    def _role_value(self, role) -> str:
        return getattr(role, "value", str(role or "")).strip().lower()

    def _professor_turma_ids(self, professor_user_id: int) -> set[int]:
        rows = (
            self.db.query(ProfessorTurma.turma_id)
            .filter(ProfessorTurma.professor_id == professor_user_id)
            .all()
        )
        return {r[0] for r in rows}

    def _professor_escola_ids(self, professor_user_id: int) -> set[int]:
        rows = (
            self.db.query(Turma.escola_id)
            .join(ProfessorTurma, ProfessorTurma.turma_id == Turma.id)
            .filter(ProfessorTurma.professor_id == professor_user_id)
            .distinct()
            .all()
        )
        return {r[0] for r in rows}

    def _gestor_escola_ids(self, gestor_user_id: int) -> set[int]:
        from app.models.relacoes import GestorEscola

        rows = (
            self.db.query(GestorEscola.escola_id)
            .filter(GestorEscola.gestor_id == gestor_user_id)
            .all()
        )
        return {r[0] for r in rows}

    def _coordenador_escola_ids(self, coordenador_user_id: int) -> set[int]:
        from app.models.relacoes import CoordenadorEscola

        rows = (
            self.db.query(CoordenadorEscola.escola_id)
            .filter(CoordenadorEscola.coordenador_id == coordenador_user_id)
            .all()
        )
        return {r[0] for r in rows}

    def _resolve_target_for_professor(self, user: Usuario, payload: AulaAoVivoCreateRequest) -> dict:
        professor_turmas = self._professor_turma_ids(user.id)
        if payload.turma_id is None:
            raise HTTPException(status_code=400, detail="Turma obrigatoria para professor.")
        if payload.turma_id not in professor_turmas:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="A turma informada nao esta vinculada ao professor autenticado.",
            )
        return {
            "professor_id": user.id,
            "turma_id": payload.turma_id,
            "escola_id": None,
            "audience_role": UserRole.ALUNO.value,
            "audience_scope": "turma",
            "target_label": payload.target_label or "Alunos da turma",
        }

    def _resolve_target_for_gestor(self, user: Usuario, payload: AulaAoVivoCreateRequest) -> dict:
        escolas_gestor = self._gestor_escola_ids(user.id)
        if not escolas_gestor:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Gestor sem escola vinculada para agendamento de lives.",
            )
        scope = (payload.target_scope or "professores_escolas_gestor").strip().lower()
        if scope in {"professores_turma", "turma"}:
            if payload.turma_id is None:
                raise HTTPException(status_code=400, detail="Turma obrigatoria para este tipo de agendamento.")
            turma = self.db.query(Turma).filter(Turma.id == payload.turma_id).first()
            if not turma or turma.escola_id not in escolas_gestor:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="A turma informada nao pertence a escola do gestor.",
                )
            turma_nome = (turma.nome or "").strip() or f"#{turma.id}"
            return {
                "professor_id": None,
                "turma_id": turma.id,
                "escola_id": turma.escola_id,
                "audience_role": UserRole.PROFESSOR.value,
                "audience_scope": "turma",
                "target_label": payload.target_label or f"Professores da turma {turma_nome}",
            }
        if scope in {"professores_escolas_gestor", "gestor_escolas"}:
            return {
                "professor_id": None,
                "turma_id": None,
                "escola_id": None,
                "audience_role": UserRole.PROFESSOR.value,
                "audience_scope": "gestor_escolas",
                "target_label": payload.target_label
                or "Professores de todas as turmas das escolas do gestor",
            }
        raise HTTPException(status_code=400, detail="Escopo de agendamento do gestor invalido.")

    def _resolve_target_for_coordenador(self, user: Usuario, payload: AulaAoVivoCreateRequest) -> dict:
        escolas_coord = self._coordenador_escola_ids(user.id)
        if not escolas_coord:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Coordenador sem escola vinculada para agendamento de lives.",
            )
        scope = (payload.target_scope or "gestores_escolas").strip().lower()
        if scope == "gestores_escolas":
            if payload.escola_id is not None:
                if payload.escola_id not in escolas_coord:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Escola fora do escopo do coordenador.",
                    )
                return {
                    "professor_id": None,
                    "turma_id": None,
                    "escola_id": payload.escola_id,
                    "audience_role": UserRole.GESTOR.value,
                    "audience_scope": "escola",
                    "target_label": payload.target_label or "Gestores da escola selecionada",
                }
            return {
                "professor_id": None,
                "turma_id": None,
                "escola_id": None,
                "audience_role": UserRole.GESTOR.value,
                "audience_scope": "coordenador_escolas",
                "target_label": payload.target_label or "Gestores das escolas do coordenador",
            }
        if scope == "professores_todas_escolas":
            return {
                "professor_id": None,
                "turma_id": None,
                "escola_id": None,
                "audience_role": UserRole.PROFESSOR.value,
                "audience_scope": "coordenador_escolas",
                "target_label": payload.target_label or "Professores de todas as escolas do coordenador",
            }
        if scope == "coordenadores_escola":
            if payload.escola_id is None:
                raise HTTPException(status_code=400, detail="Escola obrigatoria para live entre coordenadores.")
            if payload.escola_id not in escolas_coord:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Escola fora do escopo do coordenador.",
                )
            return {
                "professor_id": None,
                "turma_id": None,
                "escola_id": payload.escola_id,
                "audience_role": UserRole.COORDENADOR.value,
                "audience_scope": "escola",
                "target_label": payload.target_label or "Coordenadores da escola selecionada",
            }
        raise HTTPException(status_code=400, detail="Escopo de agendamento do coordenador invalido.")

    def _resolve_target(self, user: Usuario, payload: AulaAoVivoCreateRequest) -> dict:
        role = self._role_value(user.role)
        if role == UserRole.PROFESSOR.value:
            return self._resolve_target_for_professor(user, payload)
        if role == UserRole.GESTOR.value:
            return self._resolve_target_for_gestor(user, payload)
        if role == UserRole.COORDENADOR.value:
            return self._resolve_target_for_coordenador(user, payload)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Perfil sem permissao para agendar lives.",
        )

    def create_live_class(self, user: Usuario, payload: AulaAoVivoCreateRequest):
        scheduled_at = self._to_naive_utc(payload.scheduled_at)
        if scheduled_at <= datetime.utcnow():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A aula ao vivo precisa ser agendada para uma data futura.",
            )
        target = self._resolve_target(user, payload)

        room_name = self._build_room_name(user, payload)
        meeting_provider, meeting_url = self._build_meeting_url(room_name, payload.meeting_url)

        created = self.aula_repo.create(
            self.db,
            {
                "organizador_user_id": user.id,
                "professor_id": target["professor_id"],
                "turma_id": target["turma_id"],
                "escola_id": target["escola_id"],
                "audience_role": target["audience_role"],
                "audience_scope": target["audience_scope"],
                "target_label": target["target_label"],
                "disciplina": payload.disciplina.strip(),
                "titulo": payload.titulo.strip(),
                "descricao": (payload.descricao or "").strip() or None,
                "meeting_provider": meeting_provider,
                "room_name": room_name,
                "meeting_url": meeting_url,
                "scheduled_at": scheduled_at,
                "duration_minutes": payload.duration_minutes,
                "ativa": True,
            },
        )
        return self._serialize_live_class(created)

    def _build_visibility_context(self, user: Usuario) -> dict:
        role = self._role_value(user.role)
        ctx = {
            "role": role,
            "professor_turmas": set(),
            "professor_escolas": set(),
            "gestor_escolas": set(),
            "coordenador_escolas": set(),
            "aluno_turma_id": None,
        }
        if role == UserRole.PROFESSOR.value:
            ctx["professor_turmas"] = self._professor_turma_ids(user.id)
            ctx["professor_escolas"] = self._professor_escola_ids(user.id)
        elif role == UserRole.GESTOR.value:
            ctx["gestor_escolas"] = self._gestor_escola_ids(user.id)
        elif role == UserRole.COORDENADOR.value:
            ctx["coordenador_escolas"] = self._coordenador_escola_ids(user.id)
        elif role == UserRole.ALUNO.value:
            aluno = self.db.query(Aluno).filter(Aluno.usuario_id == user.id).first()
            ctx["aluno_turma_id"] = aluno.turma_id if aluno else None
        return ctx

    def _organizer_school_ids(self, item, cache: dict[tuple[str, int], set[int]]) -> set[int]:
        if item.escola_id:
            return {item.escola_id}
        key = (item.audience_scope, item.organizador_user_id)
        if key in cache:
            return cache[key]
        if item.audience_scope == "gestor_escolas":
            schools = self._gestor_escola_ids(item.organizador_user_id)
        elif item.audience_scope == "coordenador_escolas":
            schools = self._coordenador_escola_ids(item.organizador_user_id)
        else:
            schools = set()
        cache[key] = schools
        return schools

    def _can_view_live(self, user: Usuario, item, ctx: dict, school_cache: dict[tuple[str, int], set[int]]) -> bool:
        if item.organizador_user_id == user.id:
            return True
        role = ctx["role"]
        if role == UserRole.ALUNO.value:
            return (
                item.audience_role == UserRole.ALUNO.value
                and item.audience_scope == "turma"
                and item.turma_id is not None
                and item.turma_id == ctx["aluno_turma_id"]
            )
        if role == UserRole.PROFESSOR.value:
            if item.audience_role != UserRole.PROFESSOR.value:
                return False
            if item.audience_scope == "turma":
                return item.turma_id in ctx["professor_turmas"]
            if item.audience_scope == "escola":
                return item.escola_id in ctx["professor_escolas"]
            if item.audience_scope in {"gestor_escolas", "coordenador_escolas"}:
                target_school_ids = self._organizer_school_ids(item, school_cache)
                return bool(ctx["professor_escolas"].intersection(target_school_ids))
            return False
        if role == UserRole.GESTOR.value:
            if item.audience_role != UserRole.GESTOR.value:
                return False
            if item.audience_scope == "escola":
                return item.escola_id in ctx["gestor_escolas"]
            if item.audience_scope == "coordenador_escolas":
                target_school_ids = self._organizer_school_ids(item, school_cache)
                return bool(ctx["gestor_escolas"].intersection(target_school_ids))
            return False
        if role == UserRole.COORDENADOR.value:
            if item.audience_role != UserRole.COORDENADOR.value:
                return False
            if item.audience_scope == "escola":
                return item.escola_id in ctx["coordenador_escolas"]
            if item.audience_scope == "coordenador_escolas":
                target_school_ids = self._organizer_school_ids(item, school_cache)
                return bool(ctx["coordenador_escolas"].intersection(target_school_ids))
            return False
        return False

    def _list_live_classes_for_user(self, user: Usuario, *, limit: int = 10) -> list[dict]:
        try:
            items = (
                self.db.query(self.aula_repo.model)
                .filter(
                    self.aula_repo.model.ativa.is_(True),
                    self.aula_repo.model.scheduled_at >= datetime.utcnow(),
                )
                .order_by(self.aula_repo.model.scheduled_at.asc())
                .limit(200)
                .all()
            )
        except SQLAlchemyError:
            return []
        ctx = self._build_visibility_context(user)
        school_cache: dict[tuple[str, int], set[int]] = {}
        visible = []
        for item in items:
            if self._can_view_live(user, item, ctx, school_cache):
                visible.append(self._serialize_live_class(item))
            if len(visible) >= limit:
                break
        return visible

    def list_live_classes_for_student(self, user: Usuario):
        return self._list_live_classes_for_user(user, limit=10)

    def list_live_classes_for_professor(self, user: Usuario):
        if self._role_value(user.role) != UserRole.PROFESSOR.value:
            return []
        return self._list_live_classes_for_user(user, limit=15)

    def list_live_classes_for_gestor(self, user: Usuario):
        if self._role_value(user.role) != UserRole.GESTOR.value:
            return []
        return self._list_live_classes_for_user(user, limit=15)

    def list_live_classes_for_coordenador(self, user: Usuario):
        if self._role_value(user.role) != UserRole.COORDENADOR.value:
            return []
        return self._list_live_classes_for_user(user, limit=15)

    def get_live_class_for_user(self, user: Usuario, live_class_id: int) -> dict:
        item = self.aula_repo.get(self.db, live_class_id)
        if not item or not item.ativa:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Aula ao vivo nao encontrada.")
        ctx = self._build_visibility_context(user)
        school_cache: dict[tuple[str, int], set[int]] = {}
        if not self._can_view_live(user, item, ctx, school_cache):
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

    def list_teacher_help_requests(self, user: Usuario, limit: int = 25, turma_ids: list[int] | None = None):
        if user.role != UserRole.PROFESSOR:
            return []
        return self.solicitacao_repo.list_for_professor(self.db, user.id, limit=limit, turma_ids=turma_ids)

    def update_teacher_help_request_status(self, user: Usuario, request_id: int, next_status: str):
        if user.role != UserRole.PROFESSOR:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Somente professores podem atualizar o status da solicitação.",
            )

        normalized = (next_status or "").strip().lower()
        allowed_statuses = {"pendente", "em_analise", "respondida"}
        if normalized not in allowed_statuses:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Status inválido. Use pendente, em_analise ou respondida.",
            )

        item = self.solicitacao_repo.get_for_professor(self.db, user.id, request_id)
        if not item:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Solicitação não encontrada para o professor autenticado.",
            )

        item.status = normalized
        item.responded_at = datetime.utcnow() if normalized == "respondida" else None
        self.db.add(item)
        self.db.commit()
        self.db.refresh(item)
        return item
