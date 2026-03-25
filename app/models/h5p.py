from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, DateTime, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from app.models.base import Base


class AtividadeH5P(Base):
    __tablename__ = "atividades_h5p"
    id = Column(Integer, primary_key=True, index=True)
    titulo = Column(String(200), nullable=False)
    tipo = Column(String(50), nullable=False)  # quiz, drag-drop, video, flashcards, etc.
    path_ou_json = Column(String(500), nullable=False)  # path para pasta ou JSON
    trilha_id = Column(Integer, ForeignKey("trilhas.id"), nullable=True)
    descritor_id = Column(Integer, ForeignKey("saeb_descritores.id"), nullable=True)
    ordem = Column(Integer, default=0)
    ativo = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    progressos = relationship("ProgressoH5P", back_populates="atividade")


class ProgressoH5P(Base):
    __tablename__ = "progresso_h5p"
    id = Column(Integer, primary_key=True, index=True)
    aluno_id = Column(Integer, ForeignKey("alunos.id"), nullable=False)
    atividade_id = Column(Integer, ForeignKey("atividades_h5p.id"), nullable=False)
    concluido = Column(Boolean, default=False)
    score = Column(Float, nullable=True)
    data_conclusao = Column(DateTime, nullable=True)
    tentativas = Column(Integer, default=0)

    atividade = relationship("AtividadeH5P", back_populates="progressos")
