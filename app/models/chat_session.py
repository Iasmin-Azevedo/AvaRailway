import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("usuarios.id"), index=True, nullable=False)
    perfil: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    titulo: Mapped[str] = mapped_column(String(150), default="Nova conversa")
    status: Mapped[str] = mapped_column(String(20), default="ativa", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    messages = relationship("ChatMessage", back_populates="session", cascade="all, delete-orphan")
    memories = relationship("ChatMemory", back_populates="session", cascade="all, delete-orphan")
    feedbacks = relationship("ChatFeedback", back_populates="session", cascade="all, delete-orphan")
