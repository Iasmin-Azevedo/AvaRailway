from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.aluno import Aluno
from app.models.gestao import Turma
from app.models.medalhas import AlunoMedalha, MedalhaTipo, ProfessorMedalhaEnvio
from app.models.user import Usuario

DEFAULT_MEDALHA_TIPOS = [
    {
        "nome": "Esforço e Persistência",
        "slug": "esforco_persistencia",
        "icone": "fa-solid fa-dumbbell",
        "cor": "primary",
        "ordem": 10,
    },
    {
        "nome": "Participação Ativa",
        "slug": "participacao_ativa",
        "icone": "fa-solid fa-hands-clapping",
        "cor": "success",
        "ordem": 20,
    },
    {
        "nome": "Destaque da Turma",
        "slug": "destaque_turma",
        "icone": "fa-solid fa-star",
        "cor": "warning",
        "ordem": 30,
    },
    {
        "nome": "Evolução Contínua",
        "slug": "evolucao_continua",
        "icone": "fa-solid fa-chart-line",
        "cor": "info",
        "ordem": 40,
    },
]


class MedalhaService:
    def ensure_default_tipos(self, db: Session) -> int:
        created = 0
        for item in DEFAULT_MEDALHA_TIPOS:
            existing = db.query(MedalhaTipo).filter(MedalhaTipo.slug == item["slug"]).one_or_none()
            if existing:
                existing.nome = item["nome"]
                existing.icone = item["icone"]
                existing.cor = item["cor"]
                existing.ordem = item["ordem"]
                existing.ativo = True
                continue
            db.add(
                MedalhaTipo(
                    nome=item["nome"],
                    slug=item["slug"],
                    icone=item["icone"],
                    cor=item["cor"],
                    ordem=item["ordem"],
                    ativo=True,
                )
            )
            created += 1
        db.commit()
        return created

    def list_tipos_ativos(self, db: Session) -> list[MedalhaTipo]:
        return (
            db.query(MedalhaTipo)
            .filter(MedalhaTipo.ativo.is_(True))
            .order_by(MedalhaTipo.ordem, MedalhaTipo.nome)
            .all()
        )

    def enviar_medalha(
        self,
        db: Session,
        *,
        professor_usuario_id: int,
        medalha_tipo_id: int,
        turma_ids_alvo: list[int],
        aluno_id: int | None,
        mensagem: str | None,
    ) -> tuple[bool, str, int]:
        if not turma_ids_alvo:
            return False, "Nenhuma turma válida no seu escopo.", 0
        tipo = db.query(MedalhaTipo).filter(MedalhaTipo.id == medalha_tipo_id, MedalhaTipo.ativo.is_(True)).one_or_none()
        if not tipo:
            return False, "Tipo de medalha inválido ou inativo.", 0

        alunos_q = db.query(Aluno).filter(Aluno.turma_id.in_(turma_ids_alvo))
        if aluno_id:
            alunos_q = alunos_q.filter(Aluno.id == aluno_id)
        alunos = alunos_q.all()
        if not alunos:
            return False, "Nenhum aluno elegível encontrado para este envio.", 0

        turma_id = alunos[0].turma_id if len(turma_ids_alvo) == 1 else None
        envio = ProfessorMedalhaEnvio(
            professor_usuario_id=professor_usuario_id,
            turma_id=turma_id,
            medalha_tipo_id=medalha_tipo_id,
            mensagem=(mensagem or "").strip() or None,
            created_at=datetime.utcnow(),
        )
        db.add(envio)
        db.flush()

        count = 0
        now = datetime.utcnow()
        for a in alunos:
            db.add(
                AlunoMedalha(
                    aluno_id=a.id,
                    envio_id=envio.id,
                    medalha_tipo_id=medalha_tipo_id,
                    concedida_em=now,
                )
            )
            count += 1
        db.commit()
        return True, "", count

    def list_alunos_para_turmas(self, db: Session, turma_ids: list[int]) -> list[dict[str, Any]]:
        if not turma_ids:
            return []
        rows = (
            db.query(Aluno, Usuario, Turma)
            .join(Usuario, Usuario.id == Aluno.usuario_id)
            .join(Turma, Turma.id == Aluno.turma_id)
            .filter(Aluno.turma_id.in_(turma_ids))
            .order_by(Usuario.nome)
            .all()
        )
        out: list[dict[str, Any]] = []
        for a, u, t in rows:
            out.append(
                {
                    "aluno_id": a.id,
                    "nome": u.nome,
                    "turma_id": t.id,
                    "turma_nome": t.nome,
                }
            )
        return out

    def list_mural_aluno(self, db: Session, aluno_id: int, limit: int = 9) -> list[dict[str, Any]]:
        rows = (
            db.query(AlunoMedalha, MedalhaTipo)
            .join(MedalhaTipo, MedalhaTipo.id == AlunoMedalha.medalha_tipo_id)
            .filter(AlunoMedalha.aluno_id == aluno_id)
            .order_by(AlunoMedalha.concedida_em.desc())
            .limit(limit)
            .all()
        )
        out: list[dict[str, Any]] = []
        for item, tipo in rows:
            out.append(
                {
                    "nome": tipo.nome,
                    "icone": tipo.icone,
                    "cor": tipo.cor,
                    "concedida_em": item.concedida_em,
                }
            )
        return out

    def count_mural_aluno(self, db: Session, aluno_id: int) -> int:
        return db.query(func.count(AlunoMedalha.id)).filter(AlunoMedalha.aluno_id == aluno_id).scalar() or 0

    def dashboard_completo_professor(
        self, db: Session, *, professor_usuario_id: int, turma_ids: list[int]
    ) -> dict[str, Any]:
        if not turma_ids:
            return {
                "totais": {"envios": 0, "medalhas": 0, "alunos_impactados": 0},
                "ranking_alunos": [],
                "distribuicao_tipos": [],
                "historico_envios": [],
            }

        envios_query = (
            db.query(ProfessorMedalhaEnvio)
            .filter(
                ProfessorMedalhaEnvio.professor_usuario_id == professor_usuario_id,
                func.coalesce(ProfessorMedalhaEnvio.turma_id, 0).in_([0] + turma_ids),
            )
        )
        envio_ids = [e.id for e in envios_query.all()]
        if not envio_ids:
            return {
                "totais": {"envios": 0, "medalhas": 0, "alunos_impactados": 0},
                "ranking_alunos": [],
                "distribuicao_tipos": [],
                "historico_envios": [],
            }

        totais = {
            "envios": len(envio_ids),
            "medalhas": db.query(func.count(AlunoMedalha.id)).filter(AlunoMedalha.envio_id.in_(envio_ids)).scalar() or 0,
            "alunos_impactados": db.query(func.count(func.distinct(AlunoMedalha.aluno_id)))
            .filter(AlunoMedalha.envio_id.in_(envio_ids))
            .scalar()
            or 0,
        }

        ranking_rows = (
            db.query(Usuario.nome, func.count(AlunoMedalha.id).label("total"))
            .join(Aluno, Aluno.usuario_id == Usuario.id)
            .join(AlunoMedalha, AlunoMedalha.aluno_id == Aluno.id)
            .filter(AlunoMedalha.envio_id.in_(envio_ids))
            .group_by(Usuario.nome)
            .order_by(func.count(AlunoMedalha.id).desc(), Usuario.nome.asc())
            .limit(10)
            .all()
        )
        ranking_alunos = [{"nome": n, "total": int(t)} for n, t in ranking_rows]

        dist_rows = (
            db.query(MedalhaTipo.nome, MedalhaTipo.icone, MedalhaTipo.cor, func.count(AlunoMedalha.id).label("total"))
            .join(AlunoMedalha, AlunoMedalha.medalha_tipo_id == MedalhaTipo.id)
            .filter(AlunoMedalha.envio_id.in_(envio_ids))
            .group_by(MedalhaTipo.nome, MedalhaTipo.icone, MedalhaTipo.cor)
            .order_by(func.count(AlunoMedalha.id).desc(), MedalhaTipo.nome.asc())
            .all()
        )
        distribuicao_tipos = [
            {"nome": n, "icone": i, "cor": c, "total": int(t)} for n, i, c, t in dist_rows
        ]

        hist_rows = (
            db.query(ProfessorMedalhaEnvio, MedalhaTipo, Turma)
            .join(MedalhaTipo, MedalhaTipo.id == ProfessorMedalhaEnvio.medalha_tipo_id)
            .outerjoin(Turma, Turma.id == ProfessorMedalhaEnvio.turma_id)
            .filter(ProfessorMedalhaEnvio.id.in_(envio_ids))
            .order_by(ProfessorMedalhaEnvio.created_at.desc())
            .limit(15)
            .all()
        )
        historico_envios: list[dict[str, Any]] = []
        for envio, tipo, turma in hist_rows:
            total_envio = (
                db.query(func.count(AlunoMedalha.id))
                .filter(AlunoMedalha.envio_id == envio.id)
                .scalar()
                or 0
            )
            historico_envios.append(
                {
                    "envio_id": envio.id,
                    "tipo_nome": tipo.nome,
                    "tipo_icone": tipo.icone,
                    "tipo_cor": tipo.cor,
                    "turma_nome": turma.nome if turma else "Escopo múltiplo",
                    "mensagem": envio.mensagem or "",
                    "created_at": envio.created_at,
                    "total_alunos": int(total_envio),
                }
            )

        return {
            "totais": totais,
            "ranking_alunos": ranking_alunos,
            "distribuicao_tipos": distribuicao_tipos,
            "historico_envios": historico_envios,
        }
