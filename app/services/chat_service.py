from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.interacao_ia import InteracaoIA
from app.models.user import AuditLog
from app.models.user import Usuario
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
            raise HTTPException(status_code=404, detail="Sessao de chat nao encontrada")
        return self.chat_repository.get_history(session_id)

    def _ensure_session(self, user: Usuario, payload: ChatMessageRequest, message: str):
        if payload.session_id:
            session = self.chat_repository.get_user_session(payload.session_id, user.id)
            if not session:
                raise HTTPException(status_code=404, detail="Sessao de chat nao encontrada")
            if session.status != "ativa":
                raise HTTPException(status_code=409, detail="Sessao de chat encerrada")
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
            {
                "label": "Falar com o chat",
                "action": "focus_chat_input",
                "kind": "chat",
            },
            {
                "label": "Sair",
                "action": "close_chat_panel",
                "kind": "system",
            },
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
                {
                    "label": "Falar com o chat",
                    "action": "focus_chat_input",
                    "kind": "chat",
                },
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
                {
                    "label": "Falar com o chat",
                    "action": "focus_chat_input",
                    "kind": "chat",
                },
                {
                    "label": "Falar com professor",
                    "action": "choose_teacher_subject",
                    "kind": "teacher_help",
                },
            ]
        if topic == "plataforma":
            return [
                {
                    "label": "Falar com o chat",
                    "action": "focus_chat_input",
                    "kind": "chat",
                },
            ]
        return []

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

        if nlu_result.get("is_greeting_only"):
            greeting = "Oi. Escolha uma opção abaixo."
            return self._store_simple_response(
                session,
                message,
                greeting,
                "greeting",
                suggested_actions=self._build_main_menu_actions(user),
            )

        if wants_teacher_help and not subject:
            guidance = (
                "Posso encaminhar sua dúvida para um professor. "
                "Escolha a disciplina para eu enviar a solicitação corretamente."
            )
            return self._store_simple_response(
                session,
                message,
                guidance,
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
            guidance = (
                "Posso te ajudar com a atividade de duas formas: explicar pelo chat ou encaminhar para o professor da disciplina."
            )
            return self._store_simple_response(
                session,
                message,
                guidance,
                "activity_guidance",
                suggested_actions=self._build_operational_actions("atividade"),
            )

        if support_topic == "aula_ao_vivo":
            guidance = (
                "Para aula ao vivo, você pode consultar sua agenda no painel e entrar pela própria plataforma. "
                "Se quiser, também posso te orientar ou encaminhar sua dúvida ao professor."
            )
            return self._store_simple_response(
                session,
                message,
                guidance,
                "live_class_guidance",
                suggested_actions=self._build_operational_actions("aula_ao_vivo"),
            )

        if support_topic == "plataforma":
            guidance = (
                "Posso te orientar sobre trilhas, desempenho, medalhas e navegação pela plataforma. "
                "Escolha uma opção para eu seguir de forma mais direta."
            )
            return self._store_simple_response(
                session,
                message,
                guidance,
                "platform_guidance",
                suggested_actions=self._build_operational_actions("plataforma"),
            )

        message_type = nlu_result.get("message_type") or self.router_service.classify(message)
        context = self.context_service.build_context(user, message_type)
        math_answer = self.math_service.try_answer(message)
        if math_answer:
            return self._store_simple_response(
                session,
                message,
                math_answer,
                "math_guided",
                suggested_actions=self._build_suggested_actions(user, "Matemática"),
            )

        retrieved_chunks = self.retrieval_service.search(message, context=context)
        recent_history = self.chat_repository.get_recent_history(
            session.id,
            limit=settings.CHAT_MAX_HISTORY_MESSAGES,
        )
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
                "question": message,
                "system_prompt": system_prompt,
                "profile": getattr(user.role, "value", user.role),
                "history": [
                    {"sender": item.sender, "message_text": item.message_text}
                    for item in recent_history
                ],
                "context": context,
                "retrieved_chunks": [chunk.model_dump() for chunk in retrieved_chunks],
            }
        )
        ia_result.answer = self.guardrails_service.sanitize_assistant_message(ia_result.answer)

        knowledge_status = "grounded"
        if (
            nlu_result.get("is_question")
            and not retrieved_chunks
            and self.ia_service.is_low_information_answer(ia_result.answer)
        ):
            ia_result.answer = (
                "Ainda não encontrei base suficiente para responder essa pergunta com segurança. "
                "Estou em treinamento para esse tipo de dúvida e prefiro não improvisar uma resposta sem contexto confiável."
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
        )

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
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sessao de chat nao encontrada")
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
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sessao de chat nao encontrada")
        return self.chat_repository.close_session(session)
