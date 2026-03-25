from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Enum, DateTime, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from app.models.base import Base
import enum

class UserRole(str, enum.Enum):
    ALUNO = "aluno"
    PROFESSOR = "professor"
    COORDENADOR = "coordenador"
    GESTOR = "gestor"
    ADMIN = "admin"

class Usuario(Base):
    __tablename__ = "usuarios"
    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(100))
    email = Column(String(100), unique=True, index=True)
    senha_hash = Column(String(200))
    role = Column(
        Enum(UserRole, values_callable=lambda obj: [e.value for e in obj]),
        default=UserRole.ALUNO,
    )
    ativo = Column(Boolean, default=True)

    aluno_perfil = relationship("Aluno", back_populates="usuario", uselist=False)
    logs = relationship("AuditLog", back_populates="usuario")
    professor_turmas = relationship(
        "ProfessorTurma",
        back_populates="professor",
        cascade="all, delete-orphan",
    )
    gestor_escolas = relationship(
        "GestorEscola",
        back_populates="gestor",
        cascade="all, delete-orphan",
    )
    coordenador_escola = relationship(
        "CoordenadorEscola",
        back_populates="coordenador",
        uselist=False,
        cascade="all, delete-orphan",
    )

class AuditLog(Base):
    __tablename__ = "auditoria_logs"
    id = Column(Integer, primary_key=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    acao = Column(String(50)) 
    detalhes = Column(Text)
    ip = Column(String(50))
    data_hora = Column(DateTime, default=datetime.utcnow)
    usuario = relationship("Usuario", back_populates="logs")