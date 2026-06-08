"""Adiciona sigla em turmas e ano escolar em descritores.

Revision ID: 014
Revises: 013
Create Date: 2026-05-26
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "014"
down_revision: Union[str, None] = "013"
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

    if _table_exists(conn, "turmas") and not _column_exists(conn, "turmas", "sigla"):
        with op.batch_alter_table("turmas") as batch_op:
            batch_op.add_column(sa.Column("sigla", sa.String(length=20), nullable=True))

    if _table_exists(conn, "saeb_descritores") and not _column_exists(conn, "saeb_descritores", "ano_escolar"):
        with op.batch_alter_table("saeb_descritores") as batch_op:
            batch_op.add_column(sa.Column("ano_escolar", sa.Integer(), nullable=True))


def downgrade() -> None:
    pass
