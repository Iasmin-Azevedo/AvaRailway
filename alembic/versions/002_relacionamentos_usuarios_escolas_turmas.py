"""Relacionamentos entre usuários, escolas e turmas.

Revision ID: 002
Revises: 001
Create Date: 2025-01-02 00:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(conn, name: str) -> bool:
    insp = inspect(conn)
    return name in insp.get_table_names()


def upgrade() -> None:
    conn = op.get_bind()
    # usuarios vem do create_all no startup; primeiro alembic sobre BD vazia não pode criar estas FKs.
    if not _table_exists(conn, "usuarios"):
        return

    if not _table_exists(conn, "professores_turmas") and _table_exists(conn, "turmas"):
        op.create_table(
            "professores_turmas",
            sa.Column("professor_id", sa.Integer(), nullable=False),
            sa.Column("turma_id", sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(["professor_id"], ["usuarios.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["turma_id"], ["turmas.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("professor_id", "turma_id"),
        )

    if not _table_exists(conn, "gestores_escolas") and _table_exists(conn, "escolas"):
        op.create_table(
            "gestores_escolas",
            sa.Column("gestor_id", sa.Integer(), nullable=False),
            sa.Column("escola_id", sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(["gestor_id"], ["usuarios.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["escola_id"], ["escolas.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("gestor_id", "escola_id"),
        )

    if not _table_exists(conn, "coordenadores_escolas") and _table_exists(conn, "escolas"):
        op.create_table(
            "coordenadores_escolas",
            sa.Column("coordenador_id", sa.Integer(), nullable=False),
            sa.Column("escola_id", sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(
                ["coordenador_id"],
                ["usuarios.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(["escola_id"], ["escolas.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("coordenador_id"),
            sa.UniqueConstraint("coordenador_id", name="uq_coordenador_escola"),
        )


def downgrade() -> None:
    conn = op.get_bind()
    if _table_exists(conn, "coordenadores_escolas"):
        op.drop_table("coordenadores_escolas")
    if _table_exists(conn, "gestores_escolas"):
        op.drop_table("gestores_escolas")
    if _table_exists(conn, "professores_turmas"):
        op.drop_table("professores_turmas")
