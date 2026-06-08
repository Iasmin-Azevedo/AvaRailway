"""
Agrega desempenho por descritor SAEB a partir de ProgressoH5P e AtividadeH5P.
"""
from __future__ import annotations

from typing import Any, Sequence

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.models.aluno import Aluno
from app.models.avaliacao import Questao
from app.models.h5p import AtividadeH5P, ProgressoH5P
from app.models.resposta import RespostaAluno
from app.models.saeb import Descritor


class DescriptorPerformanceService:
    def notas_provas_por_aluno(self, db: Session, aluno_ids: Sequence[int]) -> dict[int, float]:
        if not aluno_ids:
            return {}
        rows = (
            db.query(
                RespostaAluno.aluno_id,
                func.count(RespostaAluno.id).label("total"),
                func.sum(case((RespostaAluno.acertou.is_(True), 1), else_=0)).label("acertos"),
            )
            .filter(RespostaAluno.aluno_id.in_(list(aluno_ids)))
            .group_by(RespostaAluno.aluno_id)
            .all()
        )
        out: dict[int, float] = {}
        for aluno_id, total, acertos in rows:
            total_n = int(total or 0)
            acertos_n = int(acertos or 0)
            out[int(aluno_id)] = round((acertos_n / total_n) * 10, 2) if total_n else 0.0
        return out

    def aluno_ids_for_turma(self, db: Session, turma_id: int | None) -> list[int]:
        if turma_id is None:
            return []
        rows = db.query(Aluno.id).filter(Aluno.turma_id == turma_id).all()
        return [r[0] for r in rows]

    def aluno_ids_for_turmas(self, db: Session, turma_ids: Sequence[int]) -> list[int]:
        if not turma_ids:
            return []
        rows = db.query(Aluno.id).filter(Aluno.turma_id.in_(list(turma_ids))).distinct().all()
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

    def prova_aggregates_for_alunos(
        self,
        db: Session,
        aluno_ids: list[int],
        *,
        aplicacao_id: int | None = None,
    ) -> list[dict[str, Any]]:
        if not aluno_ids:
            return []
        from sqlalchemy.orm import joinedload

        q = (
            db.query(RespostaAluno, Questao)
            .join(Questao, RespostaAluno.questao_id == Questao.id)
            .options(joinedload(Questao.descritor))
            .filter(RespostaAluno.aluno_id.in_(aluno_ids))
        )
        if aplicacao_id:
            q = q.filter(RespostaAluno.aplicacao_id == aplicacao_id)
        rows = q.all()
        if not rows:
            return []

        descritores_map = {d.id: d for d in db.query(Descritor).all()}
        out_map: dict[str, dict[str, Any]] = {}
        for resposta, questao in rows:
            descritor = descritores_map.get(questao.descritor_id) if questao.descritor_id else None
            codigo = (
                (descritor.codigo if descritor else "")
                or (questao.habilidade_saeb or "").strip()
                or "Sem descritor"
            )
            item = out_map.setdefault(
                codigo,
                {
                    "codigo": codigo,
                    "descricao": (descritor.descricao if descritor else "") or "",
                    "disciplina": (descritor.disciplina if descritor else "") or (questao.disciplina or ""),
                    "respostas": 0,
                    "acertos": 0,
                },
            )
            if not item["descricao"] and descritor:
                item["descricao"] = descritor.descricao or ""
            item["respostas"] += 1
            item["acertos"] += int(bool(resposta.acertou))

        out = []
        for item in out_map.values():
            taxa = round((item["acertos"] / item["respostas"]) * 100, 1) if item["respostas"] else 0
            score_10 = round((item["acertos"] / item["respostas"]) * 10, 2) if item["respostas"] else 0
            out.append(
                {
                    "codigo": item["codigo"],
                    "descricao": item["descricao"],
                    "disciplina": item["disciplina"],
                    "taxa_pct": taxa,
                    "desempenho_pct": taxa,
                    "alunos_com_conclusao": item["acertos"],
                    "alunos_elegiveis": item["respostas"],
                    "score_medio": score_10,
                    "score_maximo": 10.0,
                    "score_medio_10": score_10,
                    "desempenho_score_10": score_10,
                    "fonte": "prova",
                }
            )
        out.sort(key=lambda x: x["codigo"])
        return out

    def combined_aggregates_for_alunos(
        self,
        db: Session,
        aluno_ids: list[int],
        *,
        aplicacao_id: int | None = None,
    ) -> list[dict[str, Any]]:
        h5p_rows = self.aggregates_for_alunos(db, aluno_ids)
        prova_rows = self.prova_aggregates_for_alunos(db, aluno_ids, aplicacao_id=aplicacao_id)
        merged: dict[str, dict[str, Any]] = {}
        for row in h5p_rows:
            codigo = row["codigo"]
            engajamento_pct = row.get("taxa_pct")
            merged[codigo] = {
                "codigo": codigo,
                "descricao": row.get("descricao") or "",
                "disciplina": row.get("disciplina") or "",
                "engajamento_pct": engajamento_pct,
                "engajamento_label": f"{engajamento_pct}%" if engajamento_pct is not None else "—",
                "h5p_taxa_pct": engajamento_pct,
                "h5p_score_10": row.get("score_medio_10"),
                "desempenho_pct": None,
                "desempenho_score_10": None,
                "prova_taxa_pct": None,
                "prova_score_10": None,
                "alunos_h5p_conclusao": row.get("alunos_com_conclusao"),
                "alunos_h5p_elegiveis": row.get("alunos_elegiveis"),
            }
        for row in prova_rows:
            codigo = row["codigo"]
            desempenho_pct = row.get("desempenho_pct")
            desempenho_score = row.get("desempenho_score_10")
            base = merged.setdefault(
                codigo,
                {
                    "codigo": codigo,
                    "descricao": row.get("descricao") or "",
                    "disciplina": row.get("disciplina") or "",
                    "engajamento_pct": None,
                    "engajamento_label": "—",
                    "h5p_taxa_pct": None,
                    "h5p_score_10": None,
                    "desempenho_pct": None,
                    "desempenho_score_10": None,
                    "prova_taxa_pct": None,
                    "prova_score_10": None,
                    "alunos_h5p_conclusao": None,
                    "alunos_h5p_elegiveis": None,
                },
            )
            if not base["descricao"]:
                base["descricao"] = row.get("descricao") or ""
            if not base["disciplina"]:
                base["disciplina"] = row.get("disciplina") or ""
            base["desempenho_pct"] = desempenho_pct
            base["desempenho_score_10"] = desempenho_score
            base["prova_taxa_pct"] = desempenho_pct
            base["prova_score_10"] = desempenho_score
        return sorted(merged.values(), key=lambda item: item["codigo"])

    def contagem_atividades_acessiveis_aluno(self, db: Session, aluno_id: int) -> tuple[int, int]:
        """Concluídas e total de atividades H5P de trilha + extras do professor visíveis ao aluno."""
        from app.models.gestao import Curso, Trilha
        from app.models.professor_h5p import (
            ProfessorAtividadeH5P,
            ProfessorAtividadeH5PAluno,
            ProfessorProgressoH5P,
        )
        from app.repositories.h5p_repository import AtividadeH5PRepository

        aluno = db.query(Aluno).filter(Aluno.id == aluno_id).first()
        if not aluno:
            return 0, 0

        h5p_ids: set[int] = set()
        curso_ids = {row[0] for row in db.query(Curso.id).all()}
        if curso_ids:
            trilhas_q = db.query(Trilha.id).filter(Trilha.curso_id.in_(curso_ids))
            if aluno.ano_escolar is not None:
                trilhas_q = trilhas_q.filter(Trilha.ano_escolar == aluno.ano_escolar)
            for (trilha_id,) in trilhas_q.all():
                for act in AtividadeH5PRepository().listar(db, trilha_id=trilha_id, ativo_only=True):
                    h5p_ids.add(act.id)

        prof_ids: set[int] = set()
        if aluno.turma_id:
            acts_prof = (
                db.query(ProfessorAtividadeH5P)
                .filter(
                    ProfessorAtividadeH5P.turma_id == aluno.turma_id,
                    ProfessorAtividadeH5P.ativo.is_(True),
                )
                .all()
            )
            for ap in acts_prof:
                n_alvo = (
                    db.query(ProfessorAtividadeH5PAluno)
                    .filter(ProfessorAtividadeH5PAluno.atividade_id == ap.id)
                    .count()
                )
                if n_alvo == 0:
                    prof_ids.add(ap.id)
                elif (
                    db.query(ProfessorAtividadeH5PAluno)
                    .filter(
                        ProfessorAtividadeH5PAluno.atividade_id == ap.id,
                        ProfessorAtividadeH5PAluno.aluno_id == aluno.id,
                    )
                    .first()
                ):
                    prof_ids.add(ap.id)

        total = len(h5p_ids) + len(prof_ids)
        if not total:
            return 0, 0

        concl_h5p = 0
        if h5p_ids:
            concl_h5p = (
                db.query(func.count(ProgressoH5P.id))
                .filter(
                    ProgressoH5P.aluno_id == aluno.id,
                    ProgressoH5P.atividade_id.in_(list(h5p_ids)),
                    ProgressoH5P.concluido.is_(True),
                )
                .scalar()
                or 0
            )
        concl_prof = 0
        if prof_ids:
            concl_prof = (
                db.query(func.count(ProfessorProgressoH5P.id))
                .filter(
                    ProfessorProgressoH5P.aluno_id == aluno.id,
                    ProfessorProgressoH5P.atividade_id.in_(list(prof_ids)),
                    ProfessorProgressoH5P.concluido.is_(True),
                )
                .scalar()
                or 0
            )
        return int(concl_h5p + concl_prof), int(total)

    @staticmethod
    def _iniciais_nome(nome: str | None) -> str:
        label = (nome or "").strip()
        partes = label.split()
        if len(partes) >= 2:
            return (partes[0][0] + partes[-1][0]).upper()
        if len(partes) == 1 and len(partes[0]) >= 2:
            return partes[0][:2].upper()
        return "AL"

    def radar_alunos_turma(self, db: Session, turma_id: int | None) -> list[dict[str, Any]]:
        """Resumo por aluno: conclusões nas atividades que ele pode acessar."""
        if turma_id is None:
            return []

        from app.models.user import Usuario

        rows = (
            db.query(Aluno, Usuario.nome, Usuario.avatar_url)
            .join(Usuario, Aluno.usuario_id == Usuario.id)
            .filter(Aluno.turma_id == turma_id)
            .order_by(Usuario.nome)
            .all()
        )

        result = []
        for aluno, nome, avatar in rows:
            label = nome or "Aluno"
            concluidas, total_atividades = self.contagem_atividades_acessiveis_aluno(db, aluno.id)
            denom = max(1, int(total_atividades))
            pct = min(100, round((concluidas / denom) * 100, 1)) if total_atividades else 0.0
            risco = (aluno.nivel_risco or "BAIXO").upper()
            result.append(
                {
                    "aluno_id": aluno.id,
                    "nome": label,
                    "avatar_url": (avatar or "").strip(),
                    "iniciais": self._iniciais_nome(label),
                    "concluidas": int(concluidas),
                    "total_atividades": int(total_atividades),
                    "progresso_pct": pct,
                    "nivel_risco": risco,
                }
            )
        return result

    def radar_alunos_turmas(self, db: Session, turma_ids: Sequence[int]) -> list[dict[str, Any]]:
        """Radar agregando várias turmas; cada linha inclui nome da turma."""
        if not turma_ids:
            return []

        from app.models.gestao import Turma
        from app.models.user import Usuario

        rows = (
            db.query(Aluno, Usuario.nome, Usuario.avatar_url, Turma.nome)
            .join(Usuario, Aluno.usuario_id == Usuario.id)
            .join(Turma, Aluno.turma_id == Turma.id)
            .filter(Aluno.turma_id.in_(list(turma_ids)))
            .order_by(Turma.nome, Usuario.nome)
            .all()
        )

        result: list[dict[str, Any]] = []
        for aluno, nome, avatar, turma_nome in rows:
            label = nome or "Aluno"
            concluidas, total_atividades = self.contagem_atividades_acessiveis_aluno(db, aluno.id)
            denom = max(1, int(total_atividades))
            pct = min(100, round((concluidas / denom) * 100, 1)) if total_atividades else 0.0
            risco = (aluno.nivel_risco or "BAIXO").upper()
            result.append(
                {
                    "aluno_id": aluno.id,
                    "nome": label,
                    "avatar_url": (avatar or "").strip(),
                    "iniciais": self._iniciais_nome(label),
                    "turma_nome": turma_nome or "",
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

    def top_chat_questions_for_turmas(
        self, db: Session, turma_ids: Sequence[int], limit: int = 8
    ) -> list[dict[str, Any]]:
        if not turma_ids:
            return []

        from app.models.chat_session import ChatSession
        from app.models.chat_message import ChatMessage

        aluno_user_ids = (
            db.query(Aluno.usuario_id).filter(Aluno.turma_id.in_(list(turma_ids))).all()
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
