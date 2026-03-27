from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models.chat_feedback import ChatFeedback
from app.models.chat_memory import ChatMemory
from app.models.chat_message import ChatMessage
from app.models.chat_session import ChatSession


class ChatRepository:
    def __init__(self, db: Session):
        self.db = db

    def create_session(self, user_id: int, perfil: str, titulo: str = "Nova conversa") -> ChatSession:
        session = ChatSession(user_id=user_id, perfil=perfil, titulo=titulo)
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session

    def get_session_by_id(self, session_id: str) -> ChatSession | None:
        stmt = select(ChatSession).where(ChatSession.id == session_id)
        return self.db.scalar(stmt)

    def get_user_session(self, session_id: str, user_id: int) -> ChatSession | None:
        stmt = select(ChatSession).where(ChatSession.id == session_id, ChatSession.user_id == user_id)
        return self.db.scalar(stmt)

    def list_user_sessions(self, user_id: int) -> list[ChatSession]:
        stmt = select(ChatSession).where(ChatSession.user_id == user_id).order_by(desc(ChatSession.updated_at))
        return list(self.db.scalars(stmt).all())

    def add_message(
        self,
        session_id: str,
        sender: str,
        message_text: str,
        message_type: str = "general",
        context_json: dict | None = None,
    ) -> ChatMessage:
        message = ChatMessage(
            session_id=session_id,
            sender=sender,
            message_text=message_text,
            message_type=message_type,
            context_json=context_json,
        )
        self.db.add(message)
        self.db.commit()
        self.db.refresh(message)
        return message

    def get_history(self, session_id: str, limit: int = 50) -> list[ChatMessage]:
        stmt = select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.created_at.asc())
        items = list(self.db.scalars(stmt).all())
        return items[-limit:]

    def get_recent_history(self, session_id: str, limit: int = 10) -> list[ChatMessage]:
        stmt = select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(desc(ChatMessage.created_at))
        items = list(self.db.scalars(stmt).all())
        return list(reversed(items[:limit]))

    def upsert_memory(self, session_id: str, summary_text: str) -> ChatMemory:
        stmt = select(ChatMemory).where(ChatMemory.session_id == session_id)
        memory = self.db.scalar(stmt)
        if memory:
            memory.summary_text = summary_text
        else:
            memory = ChatMemory(session_id=session_id, summary_text=summary_text)
            self.db.add(memory)
        self.db.commit()
        self.db.refresh(memory)
        return memory

    def get_memory(self, session_id: str) -> ChatMemory | None:
        stmt = select(ChatMemory).where(ChatMemory.session_id == session_id)
        return self.db.scalar(stmt)

    def add_feedback(
        self,
        session_id: str,
        message_id: str,
        user_id: int,
        rating: str,
        comment: str | None = None,
    ) -> ChatFeedback:
        feedback = ChatFeedback(
            session_id=session_id,
            message_id=message_id,
            user_id=user_id,
            rating=rating,
            comment=comment,
        )
        self.db.add(feedback)
        self.db.commit()
        self.db.refresh(feedback)
        return feedback

    def close_session(self, session: ChatSession) -> ChatSession:
        session.status = "encerrada"
        self.db.commit()
        self.db.refresh(session)
        return session

    def touch_session(self, session: ChatSession) -> None:
        self.db.add(session)
        self.db.commit()
