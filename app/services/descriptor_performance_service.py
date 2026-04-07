"""
Agrega desempenho por descritor SAEB a partir de ProgressoH5P e AtividadeH5P.
"""
from __future__ import annotations

from typing import Any, Sequence

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.aluno import Aluno
from app.models.h5p import AtividadeH5P, ProgressoH5P
from app.models.saeb import Descritor


class DescriptorPerformanceService:
    def aluno_ids_for_turma(self, db: Session, turma_id: int | None) -> list[int]:
        if turma_id is None:
            return []
        rows = db.query(Aluno.id).filter(Aluno.turma_id == turma_id).all()
        return [r[0] for r in rows]

    def aluno_ids_all(self, db: Session) -> list[int]:
        rows = db.query(Aluno.id).all()
        return [r[0] for r in rows]

    def aluno_ids_for_escolas(self, db: Session, escola_ids: Sequence[int]) -> list[int]:
        if not escola_ids:
            return []
        from app.models.gestao import Turma

        rows = (
            db.query(Aluno.id)
            .join(Turma, Aluno.turma_id == Turma.id)
            .filter(Turma.escola_id.in_(list(escola_ids)))
            .all()
        )
        return [r[0] for r in rows]

    def aggregates_for_alunos(
        self, db: Session, aluno_ids: list[int]
    ) -> list[dict[str, Any]]:
        if not aluno_ids:
            return []

        n_alunos = len(aluno_ids)
        descritores = db.query(Descritor).order_by(Descritor.codigo).all()
        out: list[dict[str, Any]] = []

        for d in descritores:
            act_ids = [
                r[0]
                for r in db.query(AtividadeH5P.id)
                .filter(
                    AtividadeH5P.descritor_id == d.id,
                    AtividadeH5P.ativo == True,
                )
                .all()
            ]
            if not act_ids:
                continue

            alunos_com_conclusao = (
                db.query(func.count(func.distinct(ProgressoH5P.aluno_id)))
                .filter(
                    ProgressoH5P.atividade_id.in_(act_ids),
                    ProgressoH5P.concluido == True,
                    ProgressoH5P.aluno_id.in_(aluno_ids),
                )
                .scalar()
                or 0
            )

            avg_score = (
                db.query(func.avg(ProgressoH5P.score))
                .filter(
                    ProgressoH5P.atividade_id.in_(act_ids),
                    ProgressoH5P.concluido == True,
                    ProgressoH5P.score.isnot(None),
                    ProgressoH5P.aluno_id.in_(aluno_ids),
                )
                .scalar()
            )

            taxa_pct = round((alunos_com_conclusao / n_alunos) * 100, 1) if n_alunos else 0.0

            out.append(
                {
                    "descritor_id": d.id,
                    "codigo": d.codigo,
                    "descricao": d.descricao or "",
                    "disciplina": d.disciplina or "",
                    "taxa_pct": taxa_pct,
                    "alunos_com_conclusao": int(alunos_com_conclusao),
                    "alunos_elegiveis": n_alunos,
                    "score_medio": round(float(avg_score), 1) if avg_score is not None else None,
                    "score_maximo": 10.0,
                    "score_medio_10": round(float(avg_score) / 10.0, 1) if avg_score is not None else None,
                }
            )

        out.sort(key=lambda x: x["taxa_pct"])
        return out

    def radar_alunos_turma(self, db: Session, turma_id: int | None) -> list[dict[str, Any]]:
        """Resumo por aluno: conclusões H5P e nível de risco."""
        if turma_id is None:
            return []

        from app.models.user import Usuario

        rows = (
            db.query(Aluno, Usuario.nome)
            .join(Usuario, Aluno.usuario_id == Usuario.id)
            .filter(Aluno.turma_id == turma_id)
            .order_by(Usuario.nome)
            .all()
        )

        total_atividades = (
            db.query(func.count(AtividadeH5P.id))
            .filter(AtividadeH5P.ativo == True)
            .scalar()
            or 0
        )

        result = []
        for aluno, nome in rows:
            concluidas = (
                db.query(func.count(ProgressoH5P.id))
                .filter(
                    ProgressoH5P.aluno_id == aluno.id,
                    ProgressoH5P.concluido == True,
                )
                .scalar()
                or 0
            )
            denom = max(1, int(total_atividades))
            pct = min(100, round((concluidas / denom) * 100, 1))
            risco = (aluno.nivel_risco or "BAIXO").upper()
            result.append(
                {
                    "aluno_id": aluno.id,
                    "nome": nome or "Aluno",
                    "concluidas": int(concluidas),
                    "total_atividades": int(total_atividades),
                    "progresso_pct": pct,
                    "nivel_risco": risco,
                }
            )
        return result

    def top_chat_questions_for_turma(
        self, db: Session, turma_id: int | None, limit: int = 8
    ) -> list[dict[str, Any]]:
        if turma_id is None:
            return []

        from app.models.chat_session import ChatSession
        from app.models.chat_message import ChatMessage

        aluno_user_ids = (
            db.query(Aluno.usuario_id).filter(Aluno.turma_id == turma_id).all()
        )
        uids = [r[0] for r in aluno_user_ids if r[0]]
        if not uids:
            return []

        q = (
            db.query(ChatMessage.message_text, func.count(ChatMessage.id).label("cnt"))
            .join(ChatSession, ChatMessage.session_id == ChatSession.id)
            .filter(
                ChatSession.user_id.in_(uids),
                ChatMessage.sender == "user",
            )
            .group_by(ChatMessage.message_text)
            .order_by(func.count(ChatMessage.id).desc())
            .limit(limit)
        )
        return [{"texto": row[0][:200], "vezes": int(row[1])} for row in q.all()]

    def escolas_engajamento(self, db: Session, escola_ids: Sequence[int] | None) -> list[dict[str, Any]]:
        """Por escola: média de progresso H5P (concluídas / atividades ativas) entre seus alunos."""
        from app.models.gestao import Escola, Turma

        total_atividades = (
            db.query(func.count(AtividadeH5P.id))
            .filter(AtividadeH5P.ativo == True)
            .scalar()
            or 0
        )
        denom = max(1, int(total_atividades))

        q_escolas = db.query(Escola)
        if escola_ids is not None:
            q_escolas = q_escolas.filter(Escola.id.in_(list(escola_ids)))
        escolas = q_escolas.filter(Escola.ativo == True).all()

        out = []
        for esc in escolas:
            aluno_ids = self.aluno_ids_for_escolas(db, [esc.id])
            if not aluno_ids:
                out.append(
                    {
                        "escola_id": esc.id,
                        "escola_nome": esc.nome,
                        "engajamento_pct": 0.0,
                        "n_alunos": 0,
                        "media_concluidas": 0.0,
                    }
                )
                continue
            total_done = (
                db.query(func.count(ProgressoH5P.id))
                .filter(
                    ProgressoH5P.aluno_id.in_(aluno_ids),
                    ProgressoH5P.concluido == True,
                )
                .scalar()
                or 0
            )
            media = float(total_done) / len(aluno_ids)
            eng = min(100.0, round((media / denom) * 100, 1))
            out.append(
                {
                    "escola_id": esc.id,
                    "escola_nome": esc.nome,
                    "engajamento_pct": eng,
                    "n_alunos": len(aluno_ids),
                    "media_concluidas": round(media, 2),
                }
            )
        out.sort(key=lambda x: x["engajamento_pct"])
        return out
