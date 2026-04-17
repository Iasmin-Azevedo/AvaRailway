from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.models.base import Base


class MedalhaTipo(Base):
    __tablename__ = "medalha_tipos"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    nome = Column(String(120), nullable=False)
    slug = Column(String(120), nullable=False, unique=True, index=True)
    icone = Column(String(80), nullable=False, default="fa-solid fa-medal")
    cor = Column(String(30), nullable=False, default="warning")
    ativo = Column(Boolean, nullable=False, default=True, index=True)
    automatica = Column(Boolean, nullable=False, default=False, index=True)
    ordem = Column(Integer, nullable=False, default=100, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class ProfessorMedalhaEnvio(Base):
    __tablename__ = "professor_medalha_envios"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    professor_usuario_id = Column(Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False, index=True)
    turma_id = Column(Integer, ForeignKey("turmas.id", ondelete="SET NULL"), nullable=True, index=True)
    medalha_tipo_id = Column(Integer, ForeignKey("medalha_tipos.id", ondelete="RESTRICT"), nullable=False, index=True)
    mensagem = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    professor = relationship("Usuario", foreign_keys=[professor_usuario_id])
    turma = relationship("Turma")
    medalha_tipo = relationship("MedalhaTipo")


class AlunoMedalha(Base):
    __tablename__ = "aluno_medalhas"
    __table_args__ = (
        UniqueConstraint("aluno_id", "envio_id", name="uq_aluno_medalha_aluno_envio"),
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    aluno_id = Column(Integer, ForeignKey("alunos.id", ondelete="CASCADE"), nullable=False, index=True)
    envio_id = Column(Integer, ForeignKey("professor_medalha_envios.id", ondelete="CASCADE"), nullable=False, index=True)
    medalha_tipo_id = Column(Integer, ForeignKey("medalha_tipos.id", ondelete="RESTRICT"), nullable=False, index=True)
    concedida_em = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    aluno = relationship("Aluno")
    envio = relationship("ProfessorMedalhaEnvio")
    medalha_tipo = relationship("MedalhaTipo")


class AlunoMedalhaAutomatica(Base):
    __tablename__ = "aluno_medalhas_automaticas"
    __table_args__ = (
        UniqueConstraint("aluno_id", "medalha_tipo_id", name="uq_aluno_medalha_auto_aluno_tipo"),
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    aluno_id = Column(Integer, ForeignKey("alunos.id", ondelete="CASCADE"), nullable=False, index=True)
    medalha_tipo_id = Column(Integer, ForeignKey("medalha_tipos.id", ondelete="CASCADE"), nullable=False, index=True)
    conquistada = Column(Boolean, nullable=False, default=False, index=True)
    concedida_em = Column(DateTime, nullable=True, index=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    aluno = relationship("Aluno")
    medalha_tipo = relationship("MedalhaTipo")
