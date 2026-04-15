"""Moodle course catalog and gestor professor assignments.

Revision ID: 005
Revises: 004
Create Date: 2026-04-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(conn, name: str) -> bool:
    insp = inspect(conn)
    return name in insp.get_table_names()


def upgrade() -> None:
    conn = op.get_bind()

    if not _table_exists(conn, "moodle_course_catalog"):
        op.create_table(
            "moodle_course_catalog",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("moodle_course_id", sa.Integer(), nullable=False),
            sa.Column("fullname", sa.String(length=255), nullable=False),
            sa.Column("shortname", sa.String(length=100), nullable=False, server_default=""),
            sa.Column("category_id", sa.Integer(), nullable=True),
            sa.Column("visible", sa.Boolean(), nullable=False, server_default=sa.text("1")),
            sa.Column("synced_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("moodle_course_id", name="uq_moodle_course_catalog_moodle_id"),
        )

    if not _table_exists(conn, "gestor_professor_moodle_course") and _table_exists(conn, "usuarios"):
        op.create_table(
            "gestor_professor_moodle_course",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("professor_usuario_id", sa.Integer(), nullable=False),
            sa.Column("moodle_course_id", sa.Integer(), nullable=False),
            sa.Column("gestor_usuario_id", sa.Integer(), nullable=False),
            sa.Column("ativo", sa.Boolean(), nullable=False, server_default=sa.text("1")),
            sa.Column("observacao", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["gestor_usuario_id"], ["usuarios.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["professor_usuario_id"], ["usuarios.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "professor_usuario_id",
                "moodle_course_id",
                name="uq_gestor_prof_moodle_prof_course",
            ),
        )
        op.create_index(
            "ix_gpmc_professor_usuario_id",
            "gestor_professor_moodle_course",
            ["professor_usuario_id"],
            unique=False,
        )
        op.create_index(
            "ix_gpmc_moodle_course_id",
            "gestor_professor_moodle_course",
            ["moodle_course_id"],
            unique=False,
        )
        op.create_index(
            "ix_gpmc_ativo",
            "gestor_professor_moodle_course",
            ["ativo"],
            unique=False,
        )


def downgrade() -> None:
    conn = op.get_bind()
    if _table_exists(conn, "gestor_professor_moodle_course"):
        op.drop_table("gestor_professor_moodle_course")
    if _table_exists(conn, "moodle_course_catalog"):
        op.drop_table("moodle_course_catalog")
