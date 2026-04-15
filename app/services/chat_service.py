import re
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.aluno import Aluno
from app.models.h5p import AtividadeH5P, ProgressoH5P
from app.models.interacao_ia import InteracaoIA
from app.models.live_support import AulaAoVivo
from app.models.gestao import Trilha
from app.models.user import AuditLog, Usuario
from app.repositories.chat_repository import ChatRepository
from app.schemas.chat_schema import ChatMessageRequest, ChatMessageResponse
from app.services.chat_context_service import ChatContextService
from app.services.chat_guardrails_service import ChatGuardrailsService
from app.services.chat_math_service import ChatMathService
from app.services.chat_memory_service import ChatMemoryService
from app.services.chat_nlu_service import ChatNLUService
from app.services.chat_router_service import ChatRouterService
from app.services.ia_service import IAService
from app.services.prompt_builder_service import PromptBuilderService
from app.services.retrieval_service import RetrievalService


class ChatService:
    """Orquestra o fluxo principal de conversas do chatbot."""

    def __init__(self, db: Session):
        self.db = db
        self.chat_repository = ChatRepository(db)
        self.router_service = ChatRouterService()
        self.guardrails_service = ChatGuardrailsService()
        self.memory_service = ChatMemoryService(self.chat_repository)
        self.math_service = ChatMathService()
        self.nlu_service = ChatNLUService(self.router_service)
        self.context_service = ChatContextService(db)
        self.retrieval_service = RetrievalService(db)
        self.prompt_builder = PromptBuilderService()
        self.ia_service = IAService()

    def create_session(self, user: Usuario, titulo: str) -> object:
        """Cria uma nova sessão de conversa para o usuário autenticado."""
        role = getattr(user.role, "value", user.role)
        return self.chat_repository.create_session(user_id=user.id, perfil=role, titulo=titulo)

    def _build_session_title(self, message: str) -> str:
        cleaned = " ".join(message.strip().split())
        if not cleaned:
            return "Nova conversa"
        return cleaned[:60]

    def _is_follow_up_message(self, message: str) -> bool:
        normalized = self.retrieval_service._normalize(" ".join(message.strip().split()))
        tokens = normalized.split()
        if len(tokens) > 5:
            return False
        return any(term in normalized for term in ("explique", "explica", "entendi", "ajuda", "ajude"))

    def _build_effective_question(self, message: str, recent_history: list) -> str:
        if not self._is_follow_up_message(message):
            return message

        previous_user_messages = [
            item.message_text.strip()
            for item in reversed(recent_history)
            if item.sender == "user" and item.message_text.strip()
        ]
        if not previous_user_messages:
            return message

        return previous_user_messages[0]

    def _register_audit(self, user: Usuario, action: str, details: str) -> None:
        self.db.add(AuditLog(usuario_id=user.id, acao=action, detalhes=details, ip=None))
        self.db.commit()

    def _register_interaction(self, user: Usuario, message: str, answer: str, context: dict) -> None:
        aluno = getattr(user, "aluno_perfil", None)
        aluno_id = getattr(aluno, "id", None)
        if not aluno_id:
            return
        self.db.add(
            InteracaoIA(
                aluno_id=aluno_id,
                pergunta=message,
                resposta_ia=answer,
                contexto=str(context)[:2000],
            )
        )
        self.db.commit()

    def list_sessions(self, user: Usuario) -> list:
        """Lista as sessões visíveis para o usuário autenticado."""
        return self.chat_repository.list_user_sessions(user.id)

    def get_history(self, user: Usuario, session_id: str) -> list:
        """Recupera o histórico completo da sessão informada."""
        session = self.chat_repository.get_user_session(session_id, user.id)
        if not session:
            raise HTTPException(status_code=404, detail="Sessão de chat não encontrada")
        return self.chat_repository.get_history(session_id)

    def _ensure_session(self, user: Usuario, payload: ChatMessageRequest, message: str):
        if payload.session_id:
            session = self.chat_repository.get_user_session(payload.session_id, user.id)
            if not session:
                raise HTTPException(status_code=404, detail="Sessão de chat não encontrada")
            if session.status != "ativa":
                raise HTTPException(status_code=409, detail="Sessão de chat encerrada")
            return session
        return self.create_session(user, self._build_session_title(message))

    def _build_suggested_actions(
        self,
        user: Usuario,
        subject: str | None,
        wants_teacher_help: bool = False,
        knowledge_status: str = "grounded",
    ) -> list[dict]:
        actions = [
            {"label": "Falar com o chat", "action": "focus_chat_input", "kind": "chat"},
            {"label": "Sair", "action": "close_chat_panel", "kind": "system"},
        ]

        role = getattr(user.role, "value", user.role)
        if role == "aluno" and subject:
            actions.append(
                {
                    "label": f"Chamar professor de {subject}",
                    "action": "request_teacher_help",
                    "kind": "teacher_help",
                    "disciplina": subject,
                    "endpoint": "/api/v1/live-support/teacher-help-requests",
                }
            )

        if knowledge_status == "training":
            actions.append(
                {
                    "label": "Reformular pergunta",
                    "action": "rephrase_question",
                    "kind": "chat",
                }
            )

        if wants_teacher_help and subject:
            actions.insert(
                0,
                {
                    "label": "Falar com o chat",
                    "action": "focus_chat_input",
                    "kind": "chat",
                }
            )

        return actions

    def _build_main_menu_actions(self, user: Usuario) -> list[dict]:
        actions = [
            {"label": "Falar com o chat", "action": "focus_chat_input", "kind": "chat"},
            {"label": "Sair", "action": "close_chat_panel", "kind": "system"},
        ]
        role = getattr(user.role, "value", user.role)
        if role == "aluno":
            actions.insert(
                1,
                {
                    "label": "Falar com professor",
                    "action": "choose_teacher_subject",
                    "kind": "teacher_help",
                }
            )
        return actions

    def _role_value(self, user: Usuario) -> str:
        return str(getattr(getattr(user, "role", None), "value", getattr(user, "role", "")) or "").strip().lower()

    def _build_profile_scope_actions(self, user: Usuario) -> list[dict]:
        role = self._role_value(user)
        if role == "aluno":
            return [
                {
                    "label": "Ver atividades pendentes",
                    "action": "send_message",
                    "kind": "chat",
                    "message": "Quais atividades estão pendentes para mim?",
                },
                {
                    "label": "Ver próxima aula ao vivo",
                    "action": "send_message",
                    "kind": "chat",
                    "message": "Qual é o horário da minha próxima aula ao vivo?",
                },
                {
                    "label": "Dúvida de Matemática",
                    "action": "send_message",
                    "kind": "chat",
                    "message": "Explique Matemática em passos simples para o ensino fundamental.",
                },
                {
                    "label": "Dúvida de Português",
                    "action": "send_message",
                    "kind": "chat",
                    "message": "Explique Português em linguagem simples para o ensino fundamental.",
                },
                {
                    "label": "Falar com professor",
                    "action": "choose_teacher_subject",
                    "kind": "teacher_help",
                },
            ]
        if role == "professor":
            return [
                {
                    "label": "Resumo das minhas turmas",
                    "action": "send_message",
                    "kind": "chat",
                    "message": "Mostre um resumo das minhas turmas vinculadas.",
                },
                {
                    "label": "Aulas ao vivo agendadas",
                    "action": "send_message",
                    "kind": "chat",
                    "message": "Quais aulas ao vivo estão agendadas para as minhas turmas?",
                },
                {
                    "label": "Apoio em atividades",
                    "action": "send_message",
                    "kind": "chat",
                    "message": "Ajude com orientação para atividades da minha turma.",
                },
            ]
        if role in {"gestor", "coordenador", "admin"}:
            return [
                {
                    "label": "Indicadores institucionais",
                    "action": "send_message",
                    "kind": "chat",
                    "message": "Quais indicadores institucionais posso acompanhar no painel?",
                },
                {
                    "label": "Acompanhamento de turmas",
                    "action": "send_message",
                    "kind": "chat",
                    "message": "Como acompanho desempenho por turma na plataforma?",
                },
                {
                    "label": "Fluxos de gestão",
                    "action": "send_message",
                    "kind": "chat",
                    "message": "Explique os fluxos de gestão disponíveis para o meu perfil.",
                },
            ]
        return [{"label": "Falar com o chat", "action": "focus_chat_input", "kind": "chat"}]

    def _looks_like_basic_math_expression(self, message: str) -> bool:
        return bool(re.search(r"[\d\+\-\*/=()]{3,}", message or ""))

    def _is_ambiguous_question(
        self,
        message: str,
        nlu_result: dict,
        support_topic: str | None,
        subject: str | None,
    ) -> bool:
        if not nlu_result.get("is_question"):
            return False
        if nlu_result.get("wants_teacher_help"):
            return False
        if support_topic or subject:
            return False
        normalized = self._normalize_text(message)
        tokens = [item for item in re.findall(r"[a-z0-9]+", normalized) if item]
        return len(tokens) <= 2

    def _build_clarification_actions(self, user: Usuario) -> list[dict]:
        role = self._role_value(user)
        if role == "aluno":
            return [
                {
                    "label": "Dúvida de Matemática",
                    "action": "send_message",
                    "kind": "chat",
                    "message": "Tenho dúvida de Matemática. Pode explicar em passos curtos?",
                },
                {
                    "label": "Dúvida de Português",
                    "action": "send_message",
                    "kind": "chat",
                    "message": "Tenho dúvida de Português. Pode explicar de forma simples?",
                },
                {
                    "label": "Atividades pendentes",
                    "action": "send_message",
                    "kind": "chat",
                    "message": "Quais atividades estão pendentes para mim?",
                },
                {
                    "label": "Falar com professor",
                    "action": "choose_teacher_subject",
                    "kind": "teacher_help",
                },
            ]
        return self._build_profile_scope_actions(user)

    def _build_out_of_scope_guidance(self, user: Usuario) -> tuple[str, list[dict]]:
        role = self._role_value(user)
        if role == "aluno":
            return (
                "Para alunos do fundamental, este chat atende dúvidas de Matemática e Língua Portuguesa, "
                "atividades, aula ao vivo e uso da plataforma. Escolha uma opção guiada abaixo para eu te ajudar "
                "do jeito certo.",
                self._build_profile_scope_actions(user),
            )
        if role == "professor":
            return (
                "Para o perfil professor, este chat está direcionado a turmas vinculadas, atividades, aulas ao vivo "
                "e orientações pedagógicas da plataforma. Escolha uma opção objetiva abaixo.",
                self._build_profile_scope_actions(user),
            )
        if role in {"gestor", "coordenador", "admin"}:
            return (
                "Para este perfil institucional, o chat está direcionado a indicadores, turmas, relatórios e fluxos "
                "de gestão da plataforma. Escolha uma opção guiada abaixo.",
                self._build_profile_scope_actions(user),
            )
        return (
            "Vamos manter a conversa em perguntas relacionadas ao seu uso da plataforma.",
            self._build_profile_scope_actions(user),
        )

    def _is_within_profile_scope(
        self,
        user: Usuario,
        message: str,
        nlu_result: dict,
        support_topic: str | None,
        subject: str | None,
    ) -> bool:
        if nlu_result.get("is_greeting_only"):
            return True
        if nlu_result.get("wants_teacher_help"):
            return True
        if support_topic in {"atividade", "aula_ao_vivo", "plataforma"}:
            return True
        if subject in {"Matemática", "Língua Portuguesa"}:
            return True
        if self._looks_like_basic_math_expression(message):
            return True
        if self.math_service.try_answer(message):
            return True

        role = self._role_value(user)
        message_type = (nlu_result.get("message_type") or "").strip().lower()
        if role == "aluno":
            return False
        if role == "professor":
            return message_type in {"pedagogical", "institutional", "hybrid"}
        if role in {"gestor", "coordenador", "admin"}:
            return message_type in {"institutional", "hybrid"}
        return True

    def _build_teacher_choice_actions(self) -> list[dict]:
        return [
            {
                "label": "Professor de Matemática",
                "action": "request_teacher_help",
                "kind": "teacher_help",
                "disciplina": "Matemática",
                "endpoint": "/api/v1/live-support/teacher-help-requests",
            },
            {
                "label": "Professor de Português",
                "action": "request_teacher_help",
                "kind": "teacher_help",
                "disciplina": "Língua Portuguesa",
                "endpoint": "/api/v1/live-support/teacher-help-requests",
            },
        ]

    def _build_operational_actions(self, topic: str) -> list[dict]:
        if topic == "atividade":
            return [
                {"label": "Falar com o chat", "action": "focus_chat_input", "kind": "chat"},
                {
                    "label": "Chamar professor de Matemática",
                    "action": "request_teacher_help",
                    "kind": "teacher_help",
                    "disciplina": "Matemática",
                    "endpoint": "/api/v1/live-support/teacher-help-requests",
                },
                {
                    "label": "Chamar professor de Português",
                    "action": "request_teacher_help",
                    "kind": "teacher_help",
                    "disciplina": "Língua Portuguesa",
                    "endpoint": "/api/v1/live-support/teacher-help-requests",
                },
            ]
        if topic == "aula_ao_vivo":
            return [
                {"label": "Falar com o chat", "action": "focus_chat_input", "kind": "chat"},
                {
                    "label": "Falar com professor",
                    "action": "choose_teacher_subject",
                    "kind": "teacher_help",
                },
            ]
        if topic == "plataforma":
            return [{"label": "Falar com o chat", "action": "focus_chat_input", "kind": "chat"}]
        return []

    def _normalize_text(self, text: str) -> str:
        return self.retrieval_service._normalize(text)

    def _get_student(self, user: Usuario) -> Aluno | None:
        return self.db.query(Aluno).filter(Aluno.usuario_id == user.id).first()

    def _format_datetime(self, value: datetime | None) -> str:
        if not value:
            return "data não informada"
        return value.strftime("%d/%m/%Y às %H:%M")

    def _build_live_class_guidance(self, user: Usuario, message: str) -> tuple[str, list[dict]]:
        aluno = self._get_student(user)
        if not aluno or not aluno.turma_id:
            return (
                "Ainda não encontrei uma turma vinculada ao seu perfil para consultar aulas ao vivo.",
                self._build_operational_actions("aula_ao_vivo"),
            )

        upcoming_classes = (
            self.db.query(AulaAoVivo)
            .filter(
                AulaAoVivo.turma_id == aluno.turma_id,
                AulaAoVivo.ativa == True,
                AulaAoVivo.scheduled_at >= datetime.utcnow(),
            )
            .order_by(AulaAoVivo.scheduled_at.asc())
            .limit(3)
            .all()
        )
        if not upcoming_classes:
            return (
                "No momento, não encontrei aula ao vivo agendada para a sua turma. Se precisar, posso encaminhar sua dúvida para o professor.",
                self._build_operational_actions("aula_ao_vivo"),
            )

        next_class = upcoming_classes[0]
        normalized_message = self._normalize_text(message)
        asks_for_link = any(term in normalized_message for term in ("link", "entrar", "acessar", "abrir", "sala"))
        asks_for_time = any(term in normalized_message for term in ("horario", "hora", "quando", "dia", "data"))

        base_message = (
            f"Sua próxima aula ao vivo é {next_class.titulo}, de {next_class.disciplina}, "
            f"marcada para {self._format_datetime(next_class.scheduled_at)}."
        )
        if asks_for_link:
            base_message += f" Para entrar, use o acesso interno em /ao-vivo/{next_class.id}."
        elif asks_for_time:
            base_message += " Quando chegar o horário, ela aparecerá na sua agenda e você poderá entrar pela própria plataforma."
        else:
            base_message += " Se quiser, eu também posso te orientar sobre horário, acesso ou encaminhar sua dúvida para o professor."

        actions = self._build_operational_actions("aula_ao_vivo")
        actions.insert(
            1,
            {
                "label": "Abrir próxima aula",
                "action": "open_live_class",
                "kind": "navigation",
                "path": f"/ao-vivo/{next_class.id}",
            },
        )
        return base_message, actions

    def _build_activity_guidance(self, user: Usuario, message: str) -> tuple[str, list[dict]]:
        aluno = self._get_student(user)
        if not aluno:
            return (
                "Ainda não consegui localizar seu perfil de aluno para consultar atividades.",
                self._build_operational_actions("atividade"),
            )

        trilha_ids = [
            item.id
            for item in self.db.query(Trilha)
            .filter((Trilha.ano_escolar == aluno.ano_escolar) | (Trilha.ano_escolar.is_(None)))
            .all()
        ]

        activity_query = self.db.query(AtividadeH5P).filter(AtividadeH5P.ativo == True)
        if trilha_ids:
            activity_query = activity_query.filter(
                (AtividadeH5P.trilha_id.in_(trilha_ids)) | (AtividadeH5P.trilha_id.is_(None))
            )

        available_activities = activity_query.order_by(AtividadeH5P.ordem.asc(), AtividadeH5P.id.asc()).limit(5).all()
        progress_items = self.db.query(ProgressoH5P).filter(ProgressoH5P.aluno_id == aluno.id).all()
        progress_by_activity = {item.atividade_id: item for item in progress_items}

        completed_count = sum(1 for item in progress_items if item.concluido)
        pending_activity = next(
            (item for item in available_activities if not progress_by_activity.get(item.id) or not progress_by_activity[item.id].concluido),
            None,
        )

        if not available_activities:
            return (
                "Ainda não encontrei atividades liberadas para você no momento. Se achar que deveria haver alguma, posso te orientar ou encaminhar isso ao professor.",
                self._build_operational_actions("atividade"),
            )

        normalized_message = self._normalize_text(message)
        asks_for_status = any(term in normalized_message for term in ("fiz", "conclui", "terminei", "pendente", "resta"))

        if pending_activity:
            response = (
                f"Você tem {len(available_activities)} atividades mapeadas e concluiu {completed_count}. "
                f"A próxima atividade recomendada é {pending_activity.titulo}."
            )
        else:
            response = (
                f"Você já concluiu {completed_count} atividades das {len(available_activities)} que encontrei para o seu ano. "
                "Se quiser, posso te ajudar a revisar o conteúdo ou chamar o professor."
            )

        if asks_for_status and pending_activity:
            response += f" No momento, a que aparece como próxima é {pending_activity.titulo}."

        return response, self._build_operational_actions("atividade")

    def _build_platform_guidance(self, context: dict) -> tuple[str, list[dict]]:
        pedagogical = context.get("pedagogical", {})
        if not pedagogical:
            return (
                "Posso te orientar sobre uso da plataforma, acesso às trilhas, desempenho e agenda.",
                self._build_operational_actions("plataforma"),
            )

        trilhas = pedagogical.get("trilhas_sugeridas") or []
        trilhas_text = ", ".join(trilhas[:2]) if trilhas else "nenhuma trilha sugerida agora"
        response = (
            f"Na plataforma, você pode acompanhar sua turma {pedagogical.get('turma') or 'não informada'}, "
            f"seu aproveitamento atual de {pedagogical.get('aproveitamento_pct', 0)}% "
            f"e suas trilhas sugeridas: {trilhas_text}."
        )
        return response, self._build_operational_actions("plataforma")

    def _store_simple_response(
        self,
        session,
        user_message_text: str,
        assistant_text: str,
        message_type: str,
        moderation_action: str | None = None,
        knowledge_status: str = "grounded",
        suggested_actions: list[dict] | None = None,
    ) -> ChatMessageResponse:
        user_message = self.chat_repository.add_message(
            session_id=session.id,
            sender="user",
            message_text=user_message_text,
            message_type=message_type,
            context_json={},
        )
        assistant_message = self.chat_repository.add_message(
            session_id=session.id,
            sender="assistant",
            message_text=assistant_text,
            message_type=message_type,
            context_json={
                "moderation_action": moderation_action,
                "knowledge_status": knowledge_status,
                "suggested_actions": suggested_actions or [],
            },
        )
        self.chat_repository.touch_session(session)
        return ChatMessageResponse(
            session_id=session.id,
            user_message=user_message.message_text,
            assistant_message=assistant_message.message_text,
            assistant_message_id=assistant_message.id,
            message_type=message_type,
            created_at=assistant_message.created_at,
            used_context=[],
            used_sources=[],
            retrieval_count=0,
            moderation_action=moderation_action,
            knowledge_status=knowledge_status,
            suggested_actions=suggested_actions or [],
            answer_provider="system",
            answer_model=None,
        )

    async def process_message(self, user: Usuario, payload: ChatMessageRequest) -> ChatMessageResponse:
        """Processa a mensagem do usuário, aplica proteções e gera a resposta final."""
        message = payload.message.strip()
        if len(message) > settings.CHAT_MAX_USER_MESSAGE_LENGTH:
            raise HTTPException(status_code=400, detail="Mensagem excede o limite permitido")
        session = self._ensure_session(user, payload, message)

        violation = self.guardrails_service.get_violation_response(message)
        if violation:
            action, response_text = violation
            self._register_audit(user, "chat_bloqueado", response_text)
            return self._store_simple_response(
                session,
                message,
                response_text,
                "moderation",
                moderation_action=action,
                knowledge_status="blocked",
            )

        nlu_result = await self.nlu_service.analyze(message)
        subject = nlu_result.get("subject") or self.router_service.detect_subject(message)
        wants_teacher_help = bool(nlu_result.get("wants_teacher_help"))
        support_topic = self.router_service.detect_support_topic(message)

        if not self._is_within_profile_scope(user, message, nlu_result, support_topic, subject):
            guidance, actions = self._build_out_of_scope_guidance(user)
            self._register_audit(user, "chat_escopo_direcionado", guidance)
            return self._store_simple_response(
                session,
                message,
                guidance,
                "scope_guidance",
                moderation_action="redirected_profile_scope",
                knowledge_status="redirected",
                suggested_actions=actions,
            )

        if self._is_ambiguous_question(message, nlu_result, support_topic, subject):
            clarification = (
                "Quero te responder com precisão, mas sua pergunta ficou muito curta. "
                "Escolha uma opção abaixo ou escreva a dúvida com mais detalhes."
            )
            return self._store_simple_response(
                session,
                message,
                clarification,
                "clarification_guidance",
                knowledge_status="clarification_needed",
                suggested_actions=self._build_clarification_actions(user),
            )

        if nlu_result.get("is_greeting_only"):
            return self._store_simple_response(
                session,
                message,
                "Oi. Escolha uma opção abaixo.",
                "greeting",
                suggested_actions=self._build_main_menu_actions(user),
            )

        if wants_teacher_help and not subject:
            return self._store_simple_response(
                session,
                message,
                "Posso encaminhar sua dúvida para um professor. Escolha a disciplina para eu enviar a solicitação corretamente.",
                "teacher_guidance",
                suggested_actions=self._build_teacher_choice_actions(),
            )

        if wants_teacher_help and subject:
            guidance = (
                f"Entendi que você quer ajuda em {subject}. "
                f"Você pode continuar comigo para uma explicação inicial ou chamar o professor de {subject}. "
                "Se preferir o professor, use a opção de solicitação para eu encaminhar corretamente."
            )
            return self._store_simple_response(
                session,
                message,
                guidance,
                "teacher_guidance",
                suggested_actions=self._build_suggested_actions(
                    user,
                    subject,
                    wants_teacher_help=True,
                ),
            )

        if support_topic == "atividade":
            activity_guidance, actions = self._build_activity_guidance(user, message)
            return self._store_simple_response(
                session,
                message,
                activity_guidance,
                "activity_guidance",
                suggested_actions=actions,
            )

        if support_topic == "aula_ao_vivo":
            live_guidance, actions = self._build_live_class_guidance(user, message)
            return self._store_simple_response(
                session,
                message,
                live_guidance,
                "live_class_guidance",
                suggested_actions=actions,
            )

        if support_topic == "plataforma":
            platform_guidance, actions = self._build_platform_guidance(context=self.context_service.build_context(user, "general"))
            return self._store_simple_response(
                session,
                message,
                platform_guidance,
                "platform_guidance",
                suggested_actions=actions,
            )

        message_type = nlu_result.get("message_type") or self.router_service.classify(message)
        context = self.context_service.build_context(user, message_type)
        recent_history = self.chat_repository.get_recent_history(
            session.id,
            limit=settings.CHAT_MAX_HISTORY_MESSAGES,
        )
        effective_question = self._build_effective_question(message, recent_history)

        math_answer = self.math_service.try_answer(effective_question)
        if math_answer:
            return self._store_simple_response(
                session,
                message,
                math_answer,
                "math_guided",
                suggested_actions=self._build_suggested_actions(user, "Matemática"),
            )

        retrieved_chunks = self.retrieval_service.search(effective_question, context=context)
        memory_summary = self.memory_service.get_memory_summary(session.id)
        system_prompt = self.prompt_builder.build_system_prompt(
            app_name=settings.CHAT_SYSTEM_NAME,
            profile=getattr(user.role, "value", user.role),
            message_type=message_type,
            memory_summary=memory_summary,
            context=context,
            retrieved_chunks=[chunk.model_dump() for chunk in retrieved_chunks],
        )

        user_message = self.chat_repository.add_message(
            session_id=session.id,
            sender="user",
            message_text=message,
            message_type=message_type,
            context_json=context,
        )

        ia_result = await self.ia_service.chat(
            payload={
                "question": effective_question,
                "system_prompt": system_prompt,
                "profile": getattr(user.role, "value", user.role),
                "history": [{"sender": item.sender, "message_text": item.message_text} for item in recent_history],
                "context": context,
                "retrieved_chunks": [chunk.model_dump() for chunk in retrieved_chunks],
            }
        )
        ia_result.answer = self.guardrails_service.sanitize_assistant_message(ia_result.answer)

        knowledge_status = "grounded"
        if nlu_result.get("is_question") and not retrieved_chunks and self.ia_service.is_low_information_answer(ia_result.answer):
            ia_result.answer = self.ia_service.build_guided_training_answer(
                effective_question,
                getattr(user.role, "value", user.role),
            )
            knowledge_status = "training"
        elif "estou em treinamento" in ia_result.answer.lower():
            knowledge_status = "training"

        assistant_message = self.chat_repository.add_message(
            session_id=session.id,
            sender="assistant",
            message_text=ia_result.answer,
            message_type=message_type,
            context_json={
                "used_context": ia_result.used_context,
                "used_sources": [chunk.model_dump() for chunk in retrieved_chunks],
                "retrieval_count": len(retrieved_chunks),
                "knowledge_status": knowledge_status,
            },
        )
        self._register_interaction(user, message, assistant_message.message_text, context)

        full_history = self.chat_repository.get_history(session.id)
        self.memory_service.maybe_update_memory(
            session.id,
            full_history,
            every_n=settings.CHAT_MEMORY_SUMMARY_EVERY,
        )
        self.chat_repository.touch_session(session)

        return ChatMessageResponse(
            session_id=session.id,
            user_message=user_message.message_text,
            assistant_message=assistant_message.message_text,
            assistant_message_id=assistant_message.id,
            message_type=message_type,
            created_at=assistant_message.created_at,
            used_context=ia_result.used_context,
            used_sources=[
                {
                    "source": chunk.source,
                    "title": chunk.title,
                    "metadata": chunk.metadata,
                }
                for chunk in retrieved_chunks
            ],
            retrieval_count=len(retrieved_chunks),
            moderation_action=None,
            knowledge_status=knowledge_status,
            suggested_actions=self._build_suggested_actions(
                user,
                subject,
                knowledge_status=knowledge_status,
            ),
            answer_provider=ia_result.provider,
            answer_model=ia_result.model,
        )

    async def get_runtime_status(self) -> dict:
        return await self.ia_service.runtime_status()

    def add_feedback(
        self,
        user: Usuario,
        session_id: str,
        message_id: str,
        rating: str,
        comment: str | None = None,
    ) -> None:
        """Registra feedback do usuário para uma resposta do assistente."""
        session = self.chat_repository.get_user_session(session_id, user.id)
        if not session:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sessão de chat não encontrada")
        self.chat_repository.add_feedback(
            session_id=session_id,
            message_id=message_id,
            user_id=user.id,
            rating=rating,
            comment=comment,
        )

    def close_session(self, user: Usuario, session_id: str):
        """Encerra a sessão de conversa do usuário."""
        session = self.chat_repository.get_user_session(session_id, user.id)
        if not session:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sessão de chat não encontrada")
        return self.chat_repository.close_session(session)
