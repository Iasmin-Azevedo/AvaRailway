"""Banco de questoes com 5 alternativas e vinculo da prova com trilha.

Revision ID: 013
Revises: 012
Create Date: 2026-05-26
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(conn, name: str) -> bool:
    return name in inspect(conn).get_table_names()


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    if not _table_exists(conn, table_name):
        return False
    return any(col["name"] == column_name for col in inspect(conn).get_columns(table_name))


def upgrade() -> None:
    conn = op.get_bind()

    if _table_exists(conn, "trilhas"):
        with op.batch_alter_table("trilhas") as batch_op:
            if not _column_exists(conn, "trilhas", "semestre"):
                batch_op.add_column(sa.Column("semestre", sa.String(length=20), nullable=True))

    if _table_exists(conn, "avaliacoes"):
        with op.batch_alter_table("avaliacoes") as batch_op:
            if not _column_exists(conn, "avaliacoes", "trilha_id"):
                batch_op.add_column(sa.Column("trilha_id", sa.Integer(), nullable=True))

    if _table_exists(conn, "banco_questoes"):
        with op.batch_alter_table("banco_questoes") as batch_op:
            if not _column_exists(conn, "banco_questoes", "conteudo"):
                batch_op.add_column(sa.Column("conteudo", sa.String(length=180), nullable=True))
            if not _column_exists(conn, "banco_questoes", "tipo_questao"):
                batch_op.add_column(sa.Column("tipo_questao", sa.String(length=50), nullable=False, server_default="multipla_escolha"))
            if not _column_exists(conn, "banco_questoes", "alternativa_e"):
                batch_op.add_column(sa.Column("alternativa_e", sa.String(length=200), nullable=True))

    if _table_exists(conn, "questoes_prova"):
        with op.batch_alter_table("questoes_prova") as batch_op:
            if not _column_exists(conn, "questoes_prova", "conteudo"):
                batch_op.add_column(sa.Column("conteudo", sa.String(length=180), nullable=True))
            if not _column_exists(conn, "questoes_prova", "tipo_questao"):
                batch_op.add_column(sa.Column("tipo_questao", sa.String(length=50), nullable=False, server_default="multipla_escolha"))
            if not _column_exists(conn, "questoes_prova", "alternativa_e"):
                batch_op.add_column(sa.Column("alternativa_e", sa.String(length=200), nullable=True))


def downgrade() -> None:
    pass
