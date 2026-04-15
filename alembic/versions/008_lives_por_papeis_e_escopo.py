"""Expand live classes to role-based scheduling scopes.

Revision ID: 008
Revises: 007
Create Date: 2026-04-15 00:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(conn, name: str) -> bool:
    insp = inspect(conn)
    return name in insp.get_table_names()


def _column_names(conn, table_name: str) -> set[str]:
    insp = inspect(conn)
    return {c["name"] for c in insp.get_columns(table_name)}


def _index_names(conn, table_name: str) -> set[str]:
    insp = inspect(conn)
    return {idx["name"] for idx in insp.get_indexes(table_name)}


def _foreign_key_names(conn, table_name: str) -> set[str]:
    insp = inspect(conn)
    return {fk["name"] for fk in insp.get_foreign_keys(table_name) if fk.get("name")}


def upgrade() -> None:
    conn = op.get_bind()
    if not _table_exists(conn, "aulas_ao_vivo"):
        return
    cols = _column_names(conn, "aulas_ao_vivo")

    with op.batch_alter_table("aulas_ao_vivo") as batch_op:
        if "organizador_user_id" not in cols:
            batch_op.add_column(sa.Column("organizador_user_id", sa.Integer(), nullable=True))
        if "escola_id" not in cols:
            batch_op.add_column(sa.Column("escola_id", sa.Integer(), nullable=True))
        if "audience_role" not in cols:
            batch_op.add_column(
                sa.Column("audience_role", sa.String(length=30), server_default="aluno", nullable=False)
            )
        if "audience_scope" not in cols:
            batch_op.add_column(
                sa.Column("audience_scope", sa.String(length=30), server_default="turma", nullable=False)
            )
        if "target_label" not in cols:
            batch_op.add_column(sa.Column("target_label", sa.String(length=200), nullable=True))

    op.execute("UPDATE aulas_ao_vivo SET organizador_user_id = professor_id WHERE organizador_user_id IS NULL")
    op.execute("UPDATE aulas_ao_vivo SET audience_role = 'aluno' WHERE audience_role IS NULL")
    op.execute("UPDATE aulas_ao_vivo SET audience_scope = 'turma' WHERE audience_scope IS NULL")

    cols = _column_names(conn, "aulas_ao_vivo")
    index_names = _index_names(conn, "aulas_ao_vivo")
    fk_names = _foreign_key_names(conn, "aulas_ao_vivo")

    with op.batch_alter_table("aulas_ao_vivo") as batch_op:
        if "organizador_user_id" in cols:
            batch_op.alter_column(
                "organizador_user_id",
                existing_type=sa.Integer(),
                nullable=False,
            )
        if "professor_id" in cols:
            batch_op.alter_column(
                "professor_id",
                existing_type=sa.Integer(),
                nullable=True,
            )
        if "turma_id" in cols:
            batch_op.alter_column(
                "turma_id",
                existing_type=sa.Integer(),
                nullable=True,
            )
        if (
            _table_exists(conn, "usuarios")
            and "organizador_user_id" in cols
            and "fk_aulas_ao_vivo_organizador_user_id" not in fk_names
        ):
            batch_op.create_foreign_key(
                "fk_aulas_ao_vivo_organizador_user_id",
                "usuarios",
                ["organizador_user_id"],
                ["id"],
            )
        if (
            _table_exists(conn, "escolas")
            and "escola_id" in cols
            and "fk_aulas_ao_vivo_escola_id" not in fk_names
        ):
            batch_op.create_foreign_key(
                "fk_aulas_ao_vivo_escola_id",
                "escolas",
                ["escola_id"],
                ["id"],
            )
        if "organizador_user_id" in cols and "ix_aulas_ao_vivo_organizador_user_id" not in index_names:
            batch_op.create_index("ix_aulas_ao_vivo_organizador_user_id", ["organizador_user_id"], unique=False)
        if "escola_id" in cols and "ix_aulas_ao_vivo_escola_id" not in index_names:
            batch_op.create_index("ix_aulas_ao_vivo_escola_id", ["escola_id"], unique=False)
        if "audience_role" in cols and "ix_aulas_ao_vivo_audience_role" not in index_names:
            batch_op.create_index("ix_aulas_ao_vivo_audience_role", ["audience_role"], unique=False)
        if "audience_scope" in cols and "ix_aulas_ao_vivo_audience_scope" not in index_names:
            batch_op.create_index("ix_aulas_ao_vivo_audience_scope", ["audience_scope"], unique=False)


def downgrade() -> None:
    conn = op.get_bind()
    if not _table_exists(conn, "aulas_ao_vivo"):
        return
    cols = _column_names(conn, "aulas_ao_vivo")
    index_names = _index_names(conn, "aulas_ao_vivo")
    fk_names = _foreign_key_names(conn, "aulas_ao_vivo")

    with op.batch_alter_table("aulas_ao_vivo") as batch_op:
        if "ix_aulas_ao_vivo_audience_scope" in index_names:
            batch_op.drop_index("ix_aulas_ao_vivo_audience_scope")
        if "ix_aulas_ao_vivo_audience_role" in index_names:
            batch_op.drop_index("ix_aulas_ao_vivo_audience_role")
        if "ix_aulas_ao_vivo_escola_id" in index_names:
            batch_op.drop_index("ix_aulas_ao_vivo_escola_id")
        if "ix_aulas_ao_vivo_organizador_user_id" in index_names:
            batch_op.drop_index("ix_aulas_ao_vivo_organizador_user_id")
        if "fk_aulas_ao_vivo_escola_id" in fk_names:
            batch_op.drop_constraint("fk_aulas_ao_vivo_escola_id", type_="foreignkey")
        if "fk_aulas_ao_vivo_organizador_user_id" in fk_names:
            batch_op.drop_constraint("fk_aulas_ao_vivo_organizador_user_id", type_="foreignkey")
        if "professor_id" in cols:
            batch_op.alter_column("professor_id", existing_type=sa.Integer(), nullable=False)
        if "turma_id" in cols:
            batch_op.alter_column("turma_id", existing_type=sa.Integer(), nullable=False)
        if "target_label" in cols:
            batch_op.drop_column("target_label")
        if "audience_scope" in cols:
            batch_op.drop_column("audience_scope")
        if "audience_role" in cols:
            batch_op.drop_column("audience_role")
        if "escola_id" in cols:
            batch_op.drop_column("escola_id")
        if "organizador_user_id" in cols:
            batch_op.drop_column("organizador_user_id")
