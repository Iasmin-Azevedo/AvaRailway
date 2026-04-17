"""Medalhas automáticas do aluno com estado recalculável.

Revision ID: 010
Revises: 009
Create Date: 2026-04-16
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(conn, name: str) -> bool:
    insp = inspect(conn)
    return name in insp.get_table_names()


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    insp = inspect(conn)
    if table_name not in insp.get_table_names():
        return False
    return any(col["name"] == column_name for col in insp.get_columns(table_name))


def upgrade() -> None:
    conn = op.get_bind()

    if _table_exists(conn, "medalha_tipos") and not _column_exists(conn, "medalha_tipos", "automatica"):
        op.add_column(
            "medalha_tipos",
            sa.Column("automatica", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        )
        op.create_index("ix_medalha_tipos_automatica", "medalha_tipos", ["automatica"], unique=False)

    if (
        not _table_exists(conn, "aluno_medalhas_automaticas")
        and _table_exists(conn, "alunos")
        and _table_exists(conn, "medalha_tipos")
    ):
        op.create_table(
            "aluno_medalhas_automaticas",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("aluno_id", sa.Integer(), nullable=False),
            sa.Column("medalha_tipo_id", sa.Integer(), nullable=False),
            sa.Column("conquistada", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("concedida_em", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["aluno_id"], ["alunos.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["medalha_tipo_id"], ["medalha_tipos.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("aluno_id", "medalha_tipo_id", name="uq_aluno_medalha_auto_aluno_tipo"),
        )
        op.create_index(
            "ix_aluno_medalhas_auto_aluno",
            "aluno_medalhas_automaticas",
            ["aluno_id"],
            unique=False,
        )
        op.create_index(
            "ix_aluno_medalhas_auto_tipo",
            "aluno_medalhas_automaticas",
            ["medalha_tipo_id"],
            unique=False,
        )
        op.create_index(
            "ix_aluno_medalhas_auto_conquistada",
            "aluno_medalhas_automaticas",
            ["conquistada"],
            unique=False,
        )
        op.create_index(
            "ix_aluno_medalhas_auto_concedida",
            "aluno_medalhas_automaticas",
            ["concedida_em"],
            unique=False,
        )


def downgrade() -> None:
    conn = op.get_bind()
    if _table_exists(conn, "aluno_medalhas_automaticas"):
        op.drop_table("aluno_medalhas_automaticas")
    if _column_exists(conn, "medalha_tipos", "automatica"):
        op.drop_index("ix_medalha_tipos_automatica", table_name="medalha_tipos")
        op.drop_column("medalha_tipos", "automatica")
