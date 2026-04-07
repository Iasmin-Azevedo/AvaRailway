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

    def _store_simple_response(
        self,
        session,
        user_message_text: str,
        assistant_text: str,
        message_type: str,
        moderation_action: str | None = None,
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
            context_json={"moderation_action": moderation_action} if moderation_action else {},
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
            )

        if self.router_service.is_greeting_only(message):
            greeting = (
                "Oi! Eu sou o assistente do AVA MJ. "
                "Se quiser, posso te ajudar com estudos, atividades, trilhas, desempenho ou uso da plataforma."
            )
            return self._store_simple_response(session, message, greeting, "greeting")

        message_type = self.router_service.classify(message)
        context = self.context_service.build_context(user, message_type)
        math_answer = self.math_service.try_answer(message)
        if math_answer:
            return self._store_simple_response(session, message, math_answer, "math_guided")
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

        assistant_message = self.chat_repository.add_message(
            session_id=session.id,
            sender="assistant",
            message_text=ia_result.answer,
            message_type=message_type,
            context_json={
                "used_context": ia_result.used_context,
                "used_sources": [chunk.model_dump() for chunk in retrieved_chunks],
                "retrieval_count": len(retrieved_chunks),
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
