from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from app.models.base import Base

class RespostaAluno(Base):
    __tablename__ = "respostas_alunos"
    id = Column(Integer, primary_key=True)
    aluno_id = Column(Integer, ForeignKey("alunos.id"))
    avaliacao_id = Column(Integer, ForeignKey("avaliacoes.id"))
    aplicacao_id = Column(Integer, ForeignKey("aplicacoes_prova.id"), nullable=True)
    participacao_id = Column(Integer, ForeignKey("participacoes_aplicacao_prova.id"), nullable=True)
    questao_id = Column(Integer, ForeignKey("questoes_prova.id"))
    lote_importacao_id = Column(Integer, ForeignKey("lotes_importacao_gabarito.id"), nullable=True)
    resposta_marcada = Column(String(1))
    acertou = Column(Boolean)
    pontuacao = Column(Float, nullable=True)
    processado_em = Column(DateTime, default=datetime.utcnow, nullable=False)

    avaliacao = relationship("Avaliacao", back_populates="respostas_alunos")
    aplicacao = relationship("app.models.avaliacao.AplicacaoProva")
    participacao = relationship("app.models.avaliacao.ParticipacaoAplicacaoProva")
    lote_importacao = relationship("app.models.avaliacao.LoteImportacaoGabarito", back_populates="respostas")
    questao = relationship("app.models.avaliacao.Questao")


class RespostaAvaliacaoInstitucional(Base):
    __tablename__ = "respostas_avaliacao_institucional"

    id = Column(Integer, primary_key=True, index=True)
    aplicacao_id = Column(Integer, ForeignKey("aplicacoes_avaliacao_institucional.id"), nullable=False)
    criterio_id = Column(Integer, ForeignKey("criterios_avaliacao_institucional.id"), nullable=False)
    nota = Column(Float, nullable=False)
    comentario = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    aplicacao = relationship("app.models.avaliacao.AplicacaoAvaliacaoInstitucional", back_populates="respostas")
    criterio = relationship("app.models.avaliacao.CriterioAvaliacaoInstitucional", back_populates="respostas")