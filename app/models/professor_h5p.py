from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship

from app.models.base import Base


class ProfessorAtividadeH5P(Base):
    __tablename__ = "professor_atividades_h5p"

    id = Column(Integer, primary_key=True, index=True)
    professor_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False, index=True)
    turma_id = Column(Integer, ForeignKey("turmas.id"), nullable=False, index=True)
    # Língua Portuguesa / Matemática: define em que jornada (/aluno/portugues vs /aluno/matematica) a atividade aparece.
    # NULL = legado (mostrada nas duas jornadas).
    curso_id = Column(Integer, ForeignKey("cursos.id"), nullable=True, index=True)
    titulo = Column(String(200), nullable=False)
    tipo = Column(String(50), nullable=False, default="outro")
    path_ou_json = Column(String(500), nullable=False)
    descritor_id = Column(Integer, ForeignKey("saeb_descritores.id"), nullable=True)
    ativo = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    progressos = relationship("ProfessorProgressoH5P", back_populates="atividade")
    alvos_alunos = relationship(
        "ProfessorAtividadeH5PAluno",
        back_populates="atividade",
        cascade="all, delete-orphan",
    )
    curso = relationship("Curso", foreign_keys=[curso_id])


class ProfessorAtividadeH5PAluno(Base):
    """Se vazio para uma atividade, toda a turma vê; se preenchido, só os alunos listados."""

    __tablename__ = "professor_atividade_h5p_alunos"
    __table_args__ = (
        UniqueConstraint("atividade_id", "aluno_id", name="uq_prof_atividade_aluno"),
    )

    id = Column(Integer, primary_key=True, index=True)
    atividade_id = Column(
        Integer, ForeignKey("professor_atividades_h5p.id"), nullable=False, index=True
    )
    aluno_id = Column(Integer, ForeignKey("alunos.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    atividade = relationship("ProfessorAtividadeH5P", back_populates="alvos_alunos")


class ProfessorProgressoH5P(Base):
    __tablename__ = "professor_progresso_h5p"

    id = Column(Integer, primary_key=True, index=True)
    aluno_id = Column(Integer, ForeignKey("alunos.id"), nullable=False, index=True)
    atividade_id = Column(Integer, ForeignKey("professor_atividades_h5p.id"), nullable=False, index=True)
    concluido = Column(Boolean, default=False)
    score = Column(Float, nullable=True)
    data_conclusao = Column(DateTime, nullable=True)
    tentativas = Column(Integer, default=0)

    atividade = relationship("ProfessorAtividadeH5P", back_populates="progressos")
