from sqlalchemy import Column, Integer, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship

from app.models.base import Base


class ProfessorTurma(Base):
    __tablename__ = "professores_turmas"

    professor_id = Column(Integer, ForeignKey("usuarios.id"), primary_key=True)
    turma_id = Column(Integer, ForeignKey("turmas.id"), primary_key=True)

    professor = relationship("Usuario", back_populates="professor_turmas")
    turma = relationship("Turma", back_populates="professores")


class GestorEscola(Base):
    __tablename__ = "gestores_escolas"

    gestor_id = Column(Integer, ForeignKey("usuarios.id"), primary_key=True)
    escola_id = Column(Integer, ForeignKey("escolas.id"), primary_key=True)

    gestor = relationship("Usuario", back_populates="gestor_escolas")
    escola = relationship("Escola", back_populates="gestores")


class CoordenadorEscola(Base):
    __tablename__ = "coordenadores_escolas"

    coordenador_id = Column(Integer, ForeignKey("usuarios.id"), primary_key=True)
    escola_id = Column(Integer, ForeignKey("escolas.id"), nullable=False)

    __table_args__ = (
        UniqueConstraint("coordenador_id", name="uq_coordenador_escola"),
    )

    coordenador = relationship("Usuario", back_populates="coordenador_escola")
    escola = relationship("Escola", back_populates="coordenadores")

