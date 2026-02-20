from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Enum, DateTime, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from app.models.base import Base
import enum

class UserRole(str, enum.Enum):
    ALUNO = "aluno"
    PROFESSOR = "professor"
    GESTOR = "gestor"

class Usuario(Base):
    __tablename__ = "usuarios"
    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(100))
    email = Column(String(100), unique=True, index=True)
    senha_hash = Column(String(200))
    role = Column(Enum(UserRole), default=UserRole.ALUNO)
    ativo = Column(Boolean, default=True)
    
    aluno_perfil = relationship("Aluno", back_populates="usuario", uselist=False)
    logs = relationship("AuditLog", back_populates="usuario")

class AuditLog(Base):
    __tablename__ = "auditoria_logs"
    id = Column(Integer, primary_key=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    acao = Column(String(50)) 
    detalhes = Column(Text)
    ip = Column(String(50))
    data_hora = Column(DateTime, default=datetime.utcnow)
    usuario = relationship("Usuario", back_populates="logs")