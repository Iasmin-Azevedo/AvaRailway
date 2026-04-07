from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.models.base import Base


class AulaAoVivo(Base):
    __tablename__ = "aulas_ao_vivo"

    id = Column(Integer, primary_key=True, index=True)
    professor_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False, index=True)
    turma_id = Column(Integer, ForeignKey("turmas.id"), nullable=False, index=True)
    disciplina = Column(String(50), nullable=False)
    titulo = Column(String(150), nullable=False)
    descricao = Column(Text, nullable=True)
    meeting_provider = Column(String(30), default="jitsi", nullable=False)
    room_name = Column(String(150), nullable=False, index=True)
    meeting_url = Column(String(500), nullable=False)
    scheduled_at = Column(DateTime, nullable=False, index=True)
    duration_minutes = Column(Integer, default=50, nullable=False)
    ativa = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    professor = relationship("Usuario", foreign_keys=[professor_id])
    turma = relationship("Turma")


class SolicitacaoProfessor(Base):
    __tablename__ = "solicitacoes_professor"

    id = Column(Integer, primary_key=True, index=True)
    requester_user_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False, index=True)
    professor_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True, index=True)
    turma_id = Column(Integer, ForeignKey("turmas.id"), nullable=True, index=True)
    disciplina = Column(String(50), nullable=False)
    assunto = Column(String(255), nullable=False)
    requester_role = Column(String(30), nullable=False)
    session_id = Column(String(36), nullable=True)
    status = Column(String(20), default="pendente", nullable=False, index=True)
    origem = Column(String(30), default="chatbot", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    responded_at = Column(DateTime, nullable=True)

    requester = relationship("Usuario", foreign_keys=[requester_user_id])
    professor = relationship("Usuario", foreign_keys=[professor_id])
    turma = relationship("Turma")
