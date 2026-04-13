"""Add image_url to Moodle course catalog.

Revision ID: 006
Revises: 005
Create Date: 2026-04-13
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(conn, table_name: str, column_name: str) -> bool:
    insp = inspect(conn)
    try:
        cols = {c["name"] for c in insp.get_columns(table_name)}
    except Exception:
        return False
    return column_name in cols


def upgrade() -> None:
    conn = op.get_bind()
    if not _has_column(conn, "moodle_course_catalog", "image_url"):
        op.add_column("moodle_course_catalog", sa.Column("image_url", sa.String(length=1024), nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    if _has_column(conn, "moodle_course_catalog", "image_url"):
        op.drop_column("moodle_course_catalog", "image_url")
