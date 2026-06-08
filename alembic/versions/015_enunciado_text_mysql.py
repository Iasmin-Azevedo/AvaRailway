"""Ajusta enunciados para TEXT em questoes e banco.

Revision ID: 015
Revises: 014
Create Date: 2026-05-26
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "015"
down_revision: Union[str, None] = "014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "mysql":
        with op.batch_alter_table("questoes_prova") as batch_op:
            batch_op.alter_column("enunciado", existing_type=sa.String(length=500), type_=sa.Text())
        with op.batch_alter_table("banco_questoes") as batch_op:
            batch_op.alter_column("enunciado", existing_type=sa.Text(), type_=sa.Text())


def downgrade() -> None:
    pass
