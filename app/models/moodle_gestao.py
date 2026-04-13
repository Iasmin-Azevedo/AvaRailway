from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.models.base import Base


class MoodleCourseCatalog(Base):
    """Cópia local dos cursos Moodle (sincronizada via webservice)."""

    __tablename__ = "moodle_course_catalog"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    moodle_course_id = Column(Integer, unique=True, nullable=False, index=True)
    fullname = Column(String(255), nullable=False)
    shortname = Column(String(100), nullable=False, default="")
    image_url = Column(String(1024), nullable=True)
    category_id = Column(Integer, nullable=True)
    visible = Column(Boolean, nullable=False, default=True)
    synced_at = Column(DateTime, nullable=True)


class GestorProfessorMoodleCourse(Base):
    """Liberação de curso Moodle para professor (definida pelo gestor)."""

    __tablename__ = "gestor_professor_moodle_course"
    __table_args__ = (
        UniqueConstraint(
            "professor_usuario_id",
            "moodle_course_id",
            name="uq_gestor_prof_moodle_prof_course",
        ),
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    professor_usuario_id = Column(Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False, index=True)
    moodle_course_id = Column(Integer, nullable=False, index=True)
    gestor_usuario_id = Column(Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False)
    ativo = Column(Boolean, nullable=False, default=True, index=True)
    observacao = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    professor = relationship("Usuario", foreign_keys=[professor_usuario_id])
    gestor = relationship("Usuario", foreign_keys=[gestor_usuario_id])
