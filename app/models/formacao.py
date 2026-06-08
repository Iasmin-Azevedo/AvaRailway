from __future__ import annotations

from datetime import datetime
import enum

from sqlalchemy import Boolean, Column, DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.models.base import Base


class PapelParticipanteFormacao(str, enum.Enum):
    PROFESSOR = "professor"
    COORDENADOR = "coordenador"
    TECNICO_SME = "tecnico_sme"
    GESTOR = "gestor"


class StatusParticipacaoFormacao(str, enum.Enum):
    INSCRITO = "inscrito"
    EM_ANDAMENTO = "em_andamento"
    CONCLUIDO = "concluido"


class TipoRecursoFormacao(str, enum.Enum):
    TRILHA_H5P = "trilha_h5p"
    CURSO_MOODLE = "curso_moodle"
    MATERIAL_APOIO = "material_apoio"


class ProgramaFormacaoBNCC(Base):
    __tablename__ = "programas_formacao_bncc"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(180), nullable=False)
    descricao = Column(Text, nullable=True)
    tema = Column(String(180), nullable=False, default="BNCC Computacao")
    carga_horaria_total = Column(Integer, nullable=False, default=80)
    carga_horaria_presencial = Column(Integer, nullable=False, default=40)
    carga_horaria_remota = Column(Integer, nullable=False, default=40)
    publico_alvo = Column(String(255), nullable=True)
    ativo = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    turmas = relationship("TurmaFormacaoBNCC", back_populates="programa", cascade="all, delete-orphan")
    recursos = relationship("ProgramaFormacaoRecurso", back_populates="programa", cascade="all, delete-orphan")


class ProgramaFormacaoRecurso(Base):
    __tablename__ = "programas_formacao_recursos"

    id = Column(Integer, primary_key=True, index=True)
    programa_id = Column(Integer, ForeignKey("programas_formacao_bncc.id"), nullable=False, index=True)
    tipo_recurso = Column(
        Enum(TipoRecursoFormacao, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
    )
    trilha_id = Column(Integer, ForeignKey("trilhas.id"), nullable=True)
    moodle_course_id = Column(Integer, nullable=True)
    titulo = Column(String(180), nullable=False)
    descricao = Column(Text, nullable=True)

    programa = relationship("ProgramaFormacaoBNCC", back_populates="recursos")


class TurmaFormacaoBNCC(Base):
    __tablename__ = "turmas_formacao_bncc"

    id = Column(Integer, primary_key=True, index=True)
    programa_id = Column(Integer, ForeignKey("programas_formacao_bncc.id"), nullable=False, index=True)
    nome = Column(String(160), nullable=False)
    escola_id = Column(Integer, ForeignKey("escolas.id"), nullable=True)
    limite_participantes = Column(Integer, nullable=False, default=30)
    data_inicio = Column(DateTime, nullable=True)
    data_fim = Column(DateTime, nullable=True)
    observacoes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    programa = relationship("ProgramaFormacaoBNCC", back_populates="turmas")
    escola = relationship("Escola")
    participantes = relationship(
        "ParticipanteTurmaFormacaoBNCC",
        back_populates="turma",
        cascade="all, delete-orphan",
    )
    encontros = relationship(
        "EncontroPresencialFormacaoBNCC",
        back_populates="turma",
        cascade="all, delete-orphan",
    )


class ParticipanteTurmaFormacaoBNCC(Base):
    __tablename__ = "participantes_turma_formacao_bncc"

    id = Column(Integer, primary_key=True, index=True)
    turma_id = Column(Integer, ForeignKey("turmas_formacao_bncc.id"), nullable=False, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False, index=True)
    papel_participante = Column(
        Enum(PapelParticipanteFormacao, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
    )
    status = Column(
        Enum(StatusParticipacaoFormacao, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
        default=StatusParticipacaoFormacao.INSCRITO,
    )
    carga_horaria_remota_realizada = Column(Float, nullable=False, default=0.0)
    carga_horaria_presencial_realizada = Column(Float, nullable=False, default=0.0)
    devolutiva = Column(Text, nullable=True)
    certificado_emitido = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    turma = relationship("TurmaFormacaoBNCC", back_populates="participantes")
    usuario = relationship("Usuario")


class EncontroPresencialFormacaoBNCC(Base):
    __tablename__ = "encontros_presenciais_formacao_bncc"

    id = Column(Integer, primary_key=True, index=True)
    turma_id = Column(Integer, ForeignKey("turmas_formacao_bncc.id"), nullable=False, index=True)
    titulo = Column(String(180), nullable=False)
    data_encontro = Column(DateTime, nullable=False)
    carga_horaria = Column(Float, nullable=False, default=4.0)
    local = Column(String(255), nullable=True)
    descricao = Column(Text, nullable=True)

    turma = relationship("TurmaFormacaoBNCC", back_populates="encontros")
