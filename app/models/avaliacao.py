from __future__ import annotations

from datetime import datetime
import enum

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.models.base import Base


class TipoAvaliacao(str, enum.Enum):
    OBJETIVA = "objetiva"
    SIMULADO = "simulado"
    INSTITUCIONAL = "institucional"


class StatusAvaliacao(str, enum.Enum):
    RASCUNHO = "rascunho"
    ATIVA = "ativa"
    ENCERRADA = "encerrada"


class OrigemBancoQuestao(str, enum.Enum):
    MANUAL = "manual"
    IMPORTADO = "importado"
    H5P = "h5p"


class StatusAplicacaoProva(str, enum.Enum):
    PLANEJADA = "planejada"
    EM_ANDAMENTO = "em_andamento"
    CORRIGIDA = "corrigida"
    ENCERRADA = "encerrada"


class PerfilAvaliadoInstitucional(str, enum.Enum):
    GESTOR = "gestor"
    COORDENADOR = "coordenador"
    PDT = "professor_diretor_turma"


class StatusCicloAvaliacao(str, enum.Enum):
    PLANEJADO = "planejado"
    ATIVO = "ativo"
    ENCERRADO = "encerrado"


class StatusAplicacaoInstitucional(str, enum.Enum):
    ABERTA = "aberta"
    CONCLUIDA = "concluida"


class Avaliacao(Base):
    __tablename__ = "avaliacoes"

    id = Column(Integer, primary_key=True, index=True)
    codigo = Column(String(40), nullable=True, unique=True)
    titulo = Column(String(100))
    descricao = Column(String(255))
    tipo = Column(
        Enum(TipoAvaliacao, values_callable=lambda obj: [e.value for e in obj]),
        default=TipoAvaliacao.OBJETIVA,
        nullable=False,
    )
    status = Column(
        Enum(StatusAvaliacao, values_callable=lambda obj: [e.value for e in obj]),
        default=StatusAvaliacao.RASCUNHO,
        nullable=False,
    )
    ano_letivo = Column(String(20), nullable=True)
    escopo = Column(String(40), nullable=True)
    curso_id = Column(Integer, ForeignKey("cursos.id"), nullable=True, index=True)
    trilha_id = Column(Integer, ForeignKey("trilhas.id"), nullable=True, unique=True, index=True)
    ano_escolar = Column(Integer, nullable=True)
    criado_por_usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True, index=True)
    data_aplicacao = Column(DateTime, default=datetime.utcnow)

    curso = relationship("Curso", foreign_keys=[curso_id])
    trilha = relationship("Trilha", back_populates="prova", foreign_keys=[trilha_id])
    questoes = relationship(
        "app.models.avaliacao.Questao",
        back_populates="avaliacao",
        cascade="all, delete-orphan",
    )
    respostas_alunos = relationship(
        "RespostaAluno",
        back_populates="avaliacao",
        cascade="all, delete-orphan",
    )
    lotes_importacao = relationship(
        "app.models.avaliacao.LoteImportacaoGabarito",
        back_populates="avaliacao",
        cascade="all, delete-orphan",
    )
    aplicacoes = relationship(
        "app.models.avaliacao.AplicacaoProva",
        back_populates="avaliacao",
        cascade="all, delete-orphan",
    )


class BancoQuestao(Base):
    __tablename__ = "banco_questoes"

    id = Column(Integer, primary_key=True, index=True)
    codigo_referencia = Column(String(40), nullable=True, unique=True)
    autor_usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True, index=True)
    curso_id = Column(Integer, ForeignKey("cursos.id"), nullable=True, index=True)
    ano_escolar = Column(Integer, nullable=True)
    descritor_id = Column(Integer, ForeignKey("saeb_descritores.id"), nullable=True, index=True)
    conteudo = Column(String(180), nullable=True)
    tipo_questao = Column(String(50), nullable=False, default="multipla_escolha")
    origem = Column(
        Enum(OrigemBancoQuestao, values_callable=lambda obj: [e.value for e in obj]),
        default=OrigemBancoQuestao.MANUAL,
        nullable=False,
    )
    enunciado = Column(Text, nullable=False)
    alternativa_a = Column(String(200), nullable=False)
    alternativa_b = Column(String(200), nullable=False)
    alternativa_c = Column(String(200), nullable=False)
    alternativa_d = Column(String(200), nullable=False)
    alternativa_e = Column(String(200), nullable=False)
    gabarito = Column(String(1), nullable=False)
    habilidade_saeb = Column(String(10), nullable=True)
    observacoes = Column(Text, nullable=True)
    ativo = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    autor = relationship("Usuario", foreign_keys=[autor_usuario_id])
    curso = relationship("Curso", foreign_keys=[curso_id])
    descritor = relationship("Descritor", foreign_keys=[descritor_id])
    questoes_prova = relationship("app.models.avaliacao.Questao", back_populates="banco_questao")


class Questao(Base):
    __tablename__ = "questoes_prova"

    id = Column(Integer, primary_key=True)
    avaliacao_id = Column(Integer, ForeignKey("avaliacoes.id"), index=True)
    banco_questao_id = Column(Integer, ForeignKey("banco_questoes.id"), nullable=True, index=True)
    codigo = Column(String(40), nullable=True)
    numero = Column(Integer, nullable=True)
    curso_id = Column(Integer, ForeignKey("cursos.id"), nullable=True, index=True)
    ano_escolar = Column(Integer, nullable=True)
    descritor_id = Column(Integer, ForeignKey("saeb_descritores.id"), nullable=True, index=True)
    conteudo = Column(String(180), nullable=True)
    tipo_questao = Column(String(50), nullable=False, default="multipla_escolha")
    origem = Column(String(40), nullable=True)
    enunciado = Column(Text)
    alternativa_a = Column(String(200))
    alternativa_b = Column(String(200))
    alternativa_c = Column(String(200))
    alternativa_d = Column(String(200))
    alternativa_e = Column(String(200))
    gabarito = Column(String(1))  # A, B, C, D ou E
    habilidade_saeb = Column(String(10))  # Ex: D12
    disciplina = Column(String(50), nullable=True)
    peso = Column(Float, default=1.0)
    ativa = Column(Boolean, default=True)

    avaliacao = relationship("Avaliacao", back_populates="questoes")
    banco_questao = relationship("app.models.avaliacao.BancoQuestao", back_populates="questoes_prova")
    curso = relationship("Curso", foreign_keys=[curso_id])
    descritor = relationship("Descritor", foreign_keys=[descritor_id])


class AplicacaoProva(Base):
    __tablename__ = "aplicacoes_prova"

    id = Column(Integer, primary_key=True, index=True)
    avaliacao_id = Column(Integer, ForeignKey("avaliacoes.id"), nullable=False, index=True)
    titulo = Column(String(160), nullable=True)
    escopo = Column(String(40), nullable=False, default="turma")
    ano_letivo = Column(String(20), nullable=True)
    periodo_referencia = Column(String(40), nullable=True)
    turma_id = Column(Integer, ForeignKey("turmas.id"), nullable=True, index=True)
    escola_id = Column(Integer, ForeignKey("escolas.id"), nullable=True, index=True)
    status = Column(
        Enum(StatusAplicacaoProva, values_callable=lambda obj: [e.value for e in obj]),
        default=StatusAplicacaoProva.PLANEJADA,
        nullable=False,
    )
    data_aplicacao = Column(DateTime, nullable=True)
    observacoes = Column(Text, nullable=True)
    criado_por_usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    avaliacao = relationship("app.models.avaliacao.Avaliacao", back_populates="aplicacoes")
    turma = relationship("Turma", foreign_keys=[turma_id])
    escola = relationship("Escola", foreign_keys=[escola_id])
    participacoes = relationship(
        "app.models.avaliacao.ParticipacaoAplicacaoProva",
        back_populates="aplicacao",
        cascade="all, delete-orphan",
    )
    lotes_importacao = relationship(
        "app.models.avaliacao.LoteImportacaoGabarito",
        back_populates="aplicacao",
    )


class ParticipacaoAplicacaoProva(Base):
    __tablename__ = "participacoes_aplicacao_prova"
    __table_args__ = (
        UniqueConstraint("aplicacao_id", "aluno_id", name="uq_participacao_aplicacao_aluno"),
    )

    id = Column(Integer, primary_key=True, index=True)
    aplicacao_id = Column(Integer, ForeignKey("aplicacoes_prova.id"), nullable=False, index=True)
    aluno_id = Column(Integer, ForeignKey("alunos.id"), nullable=False, index=True)
    turma_id_snapshot = Column(Integer, ForeignKey("turmas.id"), nullable=True, index=True)
    escola_id_snapshot = Column(Integer, ForeignKey("escolas.id"), nullable=True, index=True)
    presente = Column(Boolean, default=False, nullable=False)
    total_questoes = Column(Integer, default=0, nullable=False)
    total_acertos = Column(Integer, default=0, nullable=False)
    nota = Column(Float, nullable=True)
    processado_em = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    aplicacao = relationship("app.models.avaliacao.AplicacaoProva", back_populates="participacoes")
    aluno = relationship("Aluno")
    turma = relationship("Turma", foreign_keys=[turma_id_snapshot])
    escola = relationship("Escola", foreign_keys=[escola_id_snapshot])


class LoteImportacaoGabarito(Base):
    __tablename__ = "lotes_importacao_gabarito"

    id = Column(Integer, primary_key=True, index=True)
    avaliacao_id = Column(Integer, ForeignKey("avaliacoes.id"), nullable=False, index=True)
    aplicacao_id = Column(Integer, ForeignKey("aplicacoes_prova.id"), nullable=True, index=True)
    arquivo_nome = Column(String(255), nullable=False)
    linhas_processadas = Column(Integer, default=0)
    linhas_com_erro = Column(Integer, default=0)
    resumo_processamento = Column(Text, nullable=True)
    criado_por_usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    avaliacao = relationship("Avaliacao", back_populates="lotes_importacao")
    aplicacao = relationship("app.models.avaliacao.AplicacaoProva", back_populates="lotes_importacao")
    respostas = relationship("RespostaAluno", back_populates="lote_importacao")


# Legado em transição: mantido apenas para migração controlada do conceito antigo.
class CicloAvaliacaoSemestral(Base):
    __tablename__ = "ciclos_avaliacao_semestral"

    id = Column(Integer, primary_key=True, index=True)
    titulo = Column(String(160), nullable=False)
    ano_letivo = Column(String(20), nullable=False)
    semestre = Column(String(20), nullable=False)
    status = Column(
        Enum(StatusCicloAvaliacao, values_callable=lambda obj: [e.value for e in obj]),
        default=StatusCicloAvaliacao.PLANEJADO,
        nullable=False,
    )
    data_inicio = Column(DateTime, nullable=True)
    data_fim = Column(DateTime, nullable=True)
    criado_por_usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    instrumentos = relationship("InstrumentoAvaliacaoInstitucional", back_populates="ciclo")
    aplicacoes = relationship("AplicacaoAvaliacaoInstitucional", back_populates="ciclo")


class InstrumentoAvaliacaoInstitucional(Base):
    __tablename__ = "instrumentos_avaliacao_institucional"

    id = Column(Integer, primary_key=True, index=True)
    ciclo_id = Column(Integer, ForeignKey("ciclos_avaliacao_semestral.id"), nullable=True)
    nome = Column(String(160), nullable=False)
    descricao = Column(Text, nullable=True)
    perfil_avaliado = Column(
        Enum(PerfilAvaliadoInstitucional, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
    )
    ativo = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    ciclo = relationship("CicloAvaliacaoSemestral", back_populates="instrumentos")
    criterios = relationship("CriterioAvaliacaoInstitucional", back_populates="instrumento")
    aplicacoes = relationship("AplicacaoAvaliacaoInstitucional", back_populates="instrumento")


class CriterioAvaliacaoInstitucional(Base):
    __tablename__ = "criterios_avaliacao_institucional"

    id = Column(Integer, primary_key=True, index=True)
    instrumento_id = Column(Integer, ForeignKey("instrumentos_avaliacao_institucional.id"), nullable=False)
    titulo = Column(String(160), nullable=False)
    descricao = Column(Text, nullable=True)
    peso = Column(Float, default=1.0, nullable=False)
    ordem = Column(Integer, default=0, nullable=False)

    instrumento = relationship("InstrumentoAvaliacaoInstitucional", back_populates="criterios")
    respostas = relationship("RespostaAvaliacaoInstitucional", back_populates="criterio")


class AplicacaoAvaliacaoInstitucional(Base):
    __tablename__ = "aplicacoes_avaliacao_institucional"

    id = Column(Integer, primary_key=True, index=True)
    ciclo_id = Column(Integer, ForeignKey("ciclos_avaliacao_semestral.id"), nullable=False)
    instrumento_id = Column(Integer, ForeignKey("instrumentos_avaliacao_institucional.id"), nullable=False)
    escola_id = Column(Integer, ForeignKey("escolas.id"), nullable=True)
    avaliado_usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    respondente_usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    status = Column(
        Enum(StatusAplicacaoInstitucional, values_callable=lambda obj: [e.value for e in obj]),
        default=StatusAplicacaoInstitucional.ABERTA,
        nullable=False,
    )
    nota_final = Column(Float, nullable=True)
    devolutiva_resumo = Column(Text, nullable=True)
    observacoes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    ciclo = relationship("CicloAvaliacaoSemestral", back_populates="aplicacoes")
    instrumento = relationship("InstrumentoAvaliacaoInstitucional", back_populates="aplicacoes")
    avaliado = relationship("Usuario", foreign_keys=[avaliado_usuario_id])
    respondente = relationship("Usuario", foreign_keys=[respondente_usuario_id])
    escola = relationship("Escola")
    respostas = relationship("RespostaAvaliacaoInstitucional", back_populates="aplicacao")