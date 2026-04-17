"""Matéria (curso) nas atividades H5P do professor para filtrar por jornada LP/MAT.

Revision ID: 009
Revises: 008
Create Date: 2026-04-16
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_names(conn, table_name: str) -> set[str]:
    insp = inspect(conn)
    cols = insp.get_columns(table_name) or []
    return {c["name"] for c in cols}


def upgrade() -> None:
    conn = op.get_bind()
    if "professor_atividades_h5p" not in inspect(conn).get_table_names():
        return
    cols = _column_names(conn, "professor_atividades_h5p")
    if "curso_id" in cols:
        return
    op.add_column(
        "professor_atividades_h5p",
        sa.Column("curso_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_professor_atividades_h5p_curso_id",
        "professor_atividades_h5p",
        "cursos",
        ["curso_id"],
        ["id"],
    )
    op.create_index(
        "ix_professor_atividades_h5p_curso_id",
        "professor_atividades_h5p",
        ["curso_id"],
        unique=False,
    )


def downgrade() -> None:
    conn = op.get_bind()
    if "professor_atividades_h5p" not in inspect(conn).get_table_names():
        return
    cols = _column_names(conn, "professor_atividades_h5p")
    if "curso_id" not in cols:
        return
    op.drop_index("ix_professor_atividades_h5p_curso_id", table_name="professor_atividades_h5p")
    op.drop_constraint("fk_professor_atividades_h5p_curso_id", "professor_atividades_h5p", type_="foreignkey")
    op.drop_column("professor_atividades_h5p", "curso_id")
