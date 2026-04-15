"""Novas tabelas (escolas, turmas, cursos, trilhas, h5p) e roles (coordenador, admin).

Revision ID: 001
Revises:
Create Date: 2025-01-01 00:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(conn, name: str) -> bool:
    insp = inspect(conn)
    return name in insp.get_table_names()


def upgrade() -> None:
    conn = op.get_bind()
    dialeto = conn.dialect.name

    # 1) Atualizar coluna role na tabela usuarios (MySQL: ENUM ou VARCHAR)
    if dialeto == "mysql":
        r = conn.execute(sa.text(
            "SELECT COLUMN_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'usuarios' AND COLUMN_NAME = 'role'"
        ))
        row = r.fetchone()
        if row and "enum" in (row[0] or "").lower():
            op.execute(
                "ALTER TABLE usuarios MODIFY COLUMN role "
                "ENUM('aluno','professor','coordenador','gestor','admin') NOT NULL DEFAULT 'aluno'"
            )

    if dialeto == "postgresql":
        op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'coordenador'")
        op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'admin'")

    # 2) Criar novas tabelas só se não existirem
    if not _table_exists(conn, "escolas"):
        op.create_table(
            "escolas",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("nome", sa.String(200), nullable=False),
            sa.Column("ativo", sa.Boolean(), default=True),
            sa.Column("endereco", sa.String(255), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_escolas_id"), "escolas", ["id"], unique=False)

    if not _table_exists(conn, "turmas"):
        op.create_table(
            "turmas",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("nome", sa.String(100), nullable=False),
            sa.Column("ano_escolar", sa.Integer(), nullable=False),
            sa.Column("escola_id", sa.Integer(), nullable=False),
            sa.Column("ano_letivo", sa.String(20), nullable=True),
            sa.ForeignKeyConstraint(["escola_id"], ["escolas.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_turmas_id"), "turmas", ["id"], unique=False)

    if not _table_exists(conn, "cursos"):
        op.create_table(
            "cursos",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("nome", sa.String(100), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_cursos_id"), "cursos", ["id"], unique=False)

    if not _table_exists(conn, "trilhas"):
        op.create_table(
            "trilhas",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("nome", sa.String(200), nullable=False),
            sa.Column("curso_id", sa.Integer(), nullable=False),
            sa.Column("ano_escolar", sa.Integer(), nullable=True),
            sa.Column("ordem", sa.Integer(), default=0),
            sa.ForeignKeyConstraint(["curso_id"], ["cursos.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_trilhas_id"), "trilhas", ["id"], unique=False)

    # SAEB descritores: obrigatório antes de atividades_h5p (FK descritor_id).
    if not _table_exists(conn, "saeb_descritores"):
        op.create_table(
            "saeb_descritores",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("codigo", sa.String(10), nullable=True),
            sa.Column("descricao", sa.String(255), nullable=True),
            sa.Column("disciplina", sa.String(50), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_saeb_descritores_id"), "saeb_descritores", ["id"], unique=False)
        op.create_index("ix_saeb_descritores_codigo", "saeb_descritores", ["codigo"], unique=True)

    if not _table_exists(conn, "atividades_h5p"):
        op.create_table(
            "atividades_h5p",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("titulo", sa.String(200), nullable=False),
            sa.Column("tipo", sa.String(50), nullable=False),
            sa.Column("path_ou_json", sa.String(500), nullable=False),
            sa.Column("trilha_id", sa.Integer(), nullable=True),
            sa.Column("descritor_id", sa.Integer(), nullable=True),
            sa.Column("ordem", sa.Integer(), default=0),
            sa.Column("ativo", sa.Boolean(), default=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["descritor_id"], ["saeb_descritores.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["trilha_id"], ["trilhas.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_atividades_h5p_id"), "atividades_h5p", ["id"], unique=False)

    if not _table_exists(conn, "progresso_h5p"):
        op.create_table(
            "progresso_h5p",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("aluno_id", sa.Integer(), nullable=False),
            sa.Column("atividade_id", sa.Integer(), nullable=False),
            sa.Column("concluido", sa.Boolean(), default=False),
            sa.Column("score", sa.Float(), nullable=True),
            sa.Column("data_conclusao", sa.DateTime(), nullable=True),
            sa.Column("tentativas", sa.Integer(), default=0),
            sa.ForeignKeyConstraint(["aluno_id"], ["alunos.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["atividade_id"], ["atividades_h5p.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_progresso_h5p_id"), "progresso_h5p", ["id"], unique=False)

    # 3) Alunos: adicionar FK turma_id -> turmas se ainda não existir
    #    Em MySQL, se a coluna já existe como INT, podemos adicionar a FK.
    try:
        insp = inspect(conn)
        fks = [fk["name"] for fk in insp.get_foreign_keys("alunos") if "turma" in (fk.get("name") or "").lower()]
        if not fks and _table_exists(conn, "turmas"):
            op.create_foreign_key(
                "fk_alunos_turma_id_turmas",
                "alunos",
                "turmas",
                ["turma_id"],
                ["id"],
                ondelete="SET NULL",
            )
    except Exception:
        pass


def downgrade() -> None:
    conn = op.get_bind()
    try:
        op.drop_constraint("fk_alunos_turma_id_turmas", "alunos", type_="foreignkey")
    except Exception:
        pass
    if _table_exists(conn, "progresso_h5p"):
        op.drop_table("progresso_h5p")
    if _table_exists(conn, "atividades_h5p"):
        op.drop_table("atividades_h5p")
    if _table_exists(conn, "saeb_descritores"):
        op.drop_table("saeb_descritores")
    if _table_exists(conn, "trilhas"):
        op.drop_table("trilhas")
    if _table_exists(conn, "cursos"):
        op.drop_table("cursos")
    if _table_exists(conn, "turmas"):
        op.drop_table("turmas")
    if _table_exists(conn, "escolas"):
        op.drop_table("escolas")
