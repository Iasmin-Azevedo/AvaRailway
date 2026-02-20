from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Float
from sqlalchemy.orm import relationship
from datetime import datetime
from app.models.base import Base

class Avaliacao(Base):
    __tablename__ = "avaliacoes"
    id = Column(Integer, primary_key=True, index=True)
    titulo = Column(String(100))
    descricao = Column(String(255))
    data_aplicacao = Column(DateTime, default=datetime.utcnow)
    
    questoes = relationship("app.models.avaliacao.Questao", back_populates="avaliacao")
    respostas_alunos = relationship("RespostaAluno", back_populates="avaliacao")

class Questao(Base):
    __tablename__ = "questoes_prova"
    id = Column(Integer, primary_key=True)
    avaliacao_id = Column(Integer, ForeignKey("avaliacoes.id"))
    enunciado = Column(String(500))
    alternativa_a = Column(String(200))
    alternativa_b = Column(String(200))
    alternativa_c = Column(String(200))
    alternativa_d = Column(String(200))
    gabarito = Column(String(1)) # A, B, C ou D
    habilidade_saeb = Column(String(10)) # Ex: D12
    
    avaliacao = relationship("Avaliacao", back_populates="questoes")