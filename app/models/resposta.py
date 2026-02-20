from sqlalchemy import Column, Integer, String, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from app.models.base import Base

class RespostaAluno(Base):
    __tablename__ = "respostas_alunos"
    id = Column(Integer, primary_key=True)
    aluno_id = Column(Integer, ForeignKey("alunos.id"))
    avaliacao_id = Column(Integer, ForeignKey("avaliacoes.id"))
    questao_id = Column(Integer, ForeignKey("questoes_prova.id"))
    resposta_marcada = Column(String(1))
    acertou = Column(Boolean)
    
    avaliacao = relationship("Avaliacao", back_populates="respostas_alunos")