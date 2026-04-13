"""Catálogo Moodle + atribuições de cursos a professores (gestor)."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import distinct
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.gestao import Turma
from app.models.moodle_gestao import GestorProfessorMoodleCourse, MoodleCourseCatalog
from app.models.relacoes import GestorEscola, ProfessorTurma
from app.models.user import UserRole, Usuario
from app.services.moodle_ws_service import MoodleWsService

logger = logging.getLogger("ava_mj_backend.moodle_assignment")


def gestor_escola_ids(db: Session, gestor_user_id: int) -> list[int]:
    rows = db.query(GestorEscola.escola_id).filter(GestorEscola.gestor_id == gestor_user_id).all()
    return [r[0] for r in rows]


def professor_usuario_ids_in_scope(db: Session, escola_ids: list[int]) -> list[int]:
    """Professores com pelo menos uma turma numa escola do âmbito; se escola_ids vazio, todos com turma."""
    q = (
        db.query(distinct(ProfessorTurma.professor_id))
        .join(Turma, Turma.id == ProfessorTurma.turma_id)
        .join(Usuario, Usuario.id == ProfessorTurma.professor_id)
        .filter(Usuario.role == UserRole.PROFESSOR, Usuario.ativo.is_(True))
    )
    if escola_ids:
        q = q.filter(Turma.escola_id.in_(escola_ids))
    return [r[0] for r in q.all()]


def professor_in_gestor_scope(db: Session, escola_ids: list[int], professor_usuario_id: int) -> bool:
    allowed = professor_usuario_ids_in_scope(db, escola_ids)
    return professor_usuario_id in allowed


def sync_catalog_from_moodle(db: Session) -> tuple[int, str | None]:
    """
    Sincroniza tabela moodle_course_catalog a partir do webservice.
    Devolve (número de cursos gravados, mensagem de erro ou None).
    """
    try:
        rows = MoodleWsService().fetch_courses_for_catalog()
    except Exception as exc:
        logger.warning("sync_catalog_from_moodle: %s", exc)
        return 0, str(exc) or "Falha ao contactar o Moodle"

    now = datetime.utcnow()
    n = 0
    for row in rows:
        mid = row["moodle_course_id"]
        existing = (
            db.query(MoodleCourseCatalog).filter(MoodleCourseCatalog.moodle_course_id == mid).one_or_none()
        )
        if existing:
            existing.fullname = row["fullname"]
            existing.shortname = row["shortname"]
            if row.get("image_url"):
                existing.image_url = row.get("image_url")
            existing.category_id = row.get("category_id")
            existing.visible = row.get("visible", True)
            existing.synced_at = now
        else:
            db.add(
                MoodleCourseCatalog(
                    moodle_course_id=mid,
                    fullname=row["fullname"],
                    shortname=row["shortname"],
                    image_url=row.get("image_url"),
                    category_id=row.get("category_id"),
                    visible=row.get("visible", True),
                    synced_at=now,
                )
            )
        n += 1
    db.commit()
    return n, None


def list_courses_catalog(db: Session) -> list[MoodleCourseCatalog]:
    return (
        db.query(MoodleCourseCatalog)
        .filter(MoodleCourseCatalog.visible.is_(True))
        .order_by(MoodleCourseCatalog.fullname)
        .all()
    )


def list_assignments_for_professor(db: Session, professor_usuario_id: int) -> list[dict[str, Any]]:
    rows = (
        db.query(GestorProfessorMoodleCourse, MoodleCourseCatalog)
        .outerjoin(
            MoodleCourseCatalog,
            MoodleCourseCatalog.moodle_course_id == GestorProfessorMoodleCourse.moodle_course_id,
        )
        .filter(
            GestorProfessorMoodleCourse.professor_usuario_id == professor_usuario_id,
            GestorProfessorMoodleCourse.ativo.is_(True),
        )
        .order_by(MoodleCourseCatalog.fullname, GestorProfessorMoodleCourse.moodle_course_id)
        .all()
    )
    out: list[dict[str, Any]] = []
    for asg, cat in rows:
        cid = asg.moodle_course_id
        if cat:
            out.append(
                {
                    "id": cid,
                    "fullname": cat.fullname,
                    "shortname": cat.shortname or "",
                    "image_url": cat.image_url or "",
                }
            )
        else:
            out.append({"id": cid, "fullname": f"Curso Moodle #{cid}", "shortname": "", "image_url": ""})
    return out


def list_assignments_for_gestor_view(
    db: Session, escola_ids: list[int]
) -> list[dict[str, Any]]:
    prof_ids = professor_usuario_ids_in_scope(db, escola_ids)
    if not prof_ids:
        return []
    q = (
        db.query(GestorProfessorMoodleCourse, Usuario, MoodleCourseCatalog)
        .join(Usuario, Usuario.id == GestorProfessorMoodleCourse.professor_usuario_id)
        .outerjoin(
            MoodleCourseCatalog,
            MoodleCourseCatalog.moodle_course_id == GestorProfessorMoodleCourse.moodle_course_id,
        )
        .filter(
            GestorProfessorMoodleCourse.professor_usuario_id.in_(prof_ids),
            GestorProfessorMoodleCourse.ativo.is_(True),
        )
        .order_by(Usuario.nome, GestorProfessorMoodleCourse.moodle_course_id)
    )
    out = []
    for asg, prof, cat in q.all():
        out.append(
            {
                "assignment_id": asg.id,
                "professor_id": prof.id,
                "professor_nome": prof.nome,
                "moodle_course_id": asg.moodle_course_id,
                "fullname": cat.fullname if cat else f"Curso Moodle #{asg.moodle_course_id}",
                "shortname": cat.shortname if cat else "",
                "image_url": (cat.image_url or "") if cat else "",
                "created_at": asg.created_at,
                "observacao": asg.observacao or "",
            }
        )
    return out


def create_assignment(
    db: Session,
    *,
    gestor: Usuario,
    professor_usuario_id: int,
    moodle_course_id: int,
    observacao: str | None = None,
) -> tuple[bool, str]:
    escolas = gestor_escola_ids(db, gestor.id)
    if not professor_in_gestor_scope(db, escolas, professor_usuario_id):
        return False, "Professor fora do seu âmbito ou sem turmas vinculadas."

    prof = db.query(Usuario).filter(Usuario.id == professor_usuario_id).one_or_none()
    if not prof or prof.role != UserRole.PROFESSOR:
        return False, "Utilizador não é professor."

    cat = (
        db.query(MoodleCourseCatalog)
        .filter(MoodleCourseCatalog.moodle_course_id == moodle_course_id)
        .one_or_none()
    )
    if not cat:
        return False, "Curso não está no catálogo. Sincronize os cursos do Moodle primeiro."

    existing = (
        db.query(GestorProfessorMoodleCourse)
        .filter(
            GestorProfessorMoodleCourse.professor_usuario_id == professor_usuario_id,
            GestorProfessorMoodleCourse.moodle_course_id == moodle_course_id,
        )
        .one_or_none()
    )
    now = datetime.utcnow()
    if existing:
        if existing.ativo:
            return False, "Esta atribuição já existe."
        existing.ativo = True
        existing.gestor_usuario_id = gestor.id
        existing.observacao = observacao
        existing.created_at = now
    else:
        db.add(
            GestorProfessorMoodleCourse(
                professor_usuario_id=professor_usuario_id,
                moodle_course_id=moodle_course_id,
                gestor_usuario_id=gestor.id,
                ativo=True,
                observacao=observacao,
                created_at=now,
            )
        )
    db.commit()

    if settings.MOODLE_AUTO_ENROL_ON_ASSIGN:
        mid = (getattr(prof, "moodle_user_id", None) or "").strip()
        if mid:
            MoodleWsService().try_enrol_user_as_student(
                moodle_course_id, int(mid), settings.MOODLE_STUDENT_ROLE_ID
            )
        else:
            logger.info(
                "MOODLE_AUTO_ENROL_ON_ASSIGN ativo mas professor id=%s sem moodle_user_id",
                professor_usuario_id,
            )

    return True, ""


def revoke_assignment(db: Session, *, gestor: Usuario, assignment_id: int) -> tuple[bool, str]:
    escolas = gestor_escola_ids(db, gestor.id)
    asg = db.query(GestorProfessorMoodleCourse).filter(GestorProfessorMoodleCourse.id == assignment_id).one_or_none()
    if not asg:
        return False, "Atribuição não encontrada."
    if not professor_in_gestor_scope(db, escolas, asg.professor_usuario_id):
        return False, "Sem permissão para revogar esta atribuição."
    if not asg.ativo:
        return False, "Já estava revogada."
    asg.ativo = False
    db.commit()
    return True, ""


def catalog_never_synced(db: Session) -> bool:
    return db.query(MoodleCourseCatalog.id).limit(1).first() is None
