from sqlalchemy import Column, Integer, String, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from app.models.base import Base


class Escola(Base):
    __tablename__ = "escolas"
    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(200), nullable=False)
    ativo = Column(Boolean, default=True)
    endereco = Column(String(255), nullable=True)

    turmas = relationship("Turma", back_populates="escola")
    gestores = relationship(
        "GestorEscola",
        back_populates="escola",
        cascade="all, delete-orphan",
    )
    coordenadores = relationship(
        "CoordenadorEscola",
        back_populates="escola",
        cascade="all, delete-orphan",
    )


class Turma(Base):
    __tablename__ = "turmas"
    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(100), nullable=False)
    sigla = Column(String(20), nullable=True)
    ano_escolar = Column(Integer, nullable=False)  # 1 a 9
    escola_id = Column(Integer, ForeignKey("escolas.id"), nullable=False)
    ano_letivo = Column(String(20), nullable=True)  # ex: "2025"

    escola = relationship("Escola", back_populates="turmas")
    professores = relationship(
        "ProfessorTurma",
        back_populates="turma",
        cascade="all, delete-orphan",
    )
    # Alunos referenciam turmas via aluno.turma_id


class Curso(Base):
    __tablename__ = "cursos"
    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(100), nullable=False)  # Língua Portuguesa, Matemática

    trilhas = relationship("Trilha", back_populates="curso")


class Trilha(Base):
    __tablename__ = "trilhas"
    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(200), nullable=False)
    curso_id = Column(Integer, ForeignKey("cursos.id"), nullable=False)
    ano_escolar = Column(Integer, nullable=True)  # 1 a 9 ou null para todas
    semestre = Column(String(20), nullable=True)
    ordem = Column(Integer, default=0)

    curso = relationship("Curso", back_populates="trilhas")
    prova = relationship("Avaliacao", back_populates="trilha", uselist=False)
    # atividades H5P referenciam trilha via atividade.trilha_id
