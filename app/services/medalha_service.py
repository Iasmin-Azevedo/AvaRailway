from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.aluno import Aluno
from app.models.gestao import Curso, Trilha, Turma
from app.models.h5p import AtividadeH5P, ProgressoH5P
from app.models.medalhas import (
    AlunoMedalha,
    AlunoMedalhaAutomatica,
    MedalhaTipo,
    ProfessorMedalhaEnvio,
)
from app.models.professor_h5p import (
    ProfessorAtividadeH5P,
    ProfessorAtividadeH5PAluno,
    ProfessorProgressoH5P,
)
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
        "automatica": False,
    },
    {
        "nome": "Guardião das Letras",
        "slug": "jornada_portugues_100",
        "icone": "fa-solid fa-book-open",
        "cor": "primary",
        "ordem": 110,
        "automatica": True,
    },
    {
        "nome": "Mestre dos Números",
        "slug": "jornada_matematica_100",
        "icone": "fa-solid fa-calculator",
        "cor": "success",
        "ordem": 120,
        "automatica": True,
    },
    {
        "nome": "Companheiro de Turma",
        "slug": "atividades_turma_100",
        "icone": "fa-solid fa-users",
        "cor": "danger",
        "ordem": 130,
        "automatica": True,
    },
    {
        "nome": "Missão de Elite",
        "slug": "missoes_exclusivas_100",
        "icone": "fa-solid fa-bullseye",
        "cor": "warning",
        "ordem": 140,
        "automatica": True,
    },
    {
        "nome": "Lenda Suprema do AVA",
        "slug": "conclusao_total_ava_100",
        "icone": "fa-solid fa-crown",
        "cor": "dark",
        "ordem": 150,
        "automatica": True,
    },
]


class MedalhaService:
    _TZ_FORTALEZA = ZoneInfo("America/Fortaleza")

    _AUTO_MEDAL_DESCRIPTIONS: dict[str, str] = {
        "jornada_portugues_100": "Você dominou toda a jornada de Português com foco, leitura e interpretação de alto nível.",
        "jornada_matematica_100": "Você venceu a jornada de Matemática por completo e mostrou raciocínio afiado em cada desafio.",
        "atividades_turma_100": "Você concluiu todas as atividades da turma e se destacou pelo comprometimento coletivo.",
        "missoes_exclusivas_100": "Você superou todas as missões exclusivas enviadas para o seu perfil, com performance de elite.",
        "conclusao_total_ava_100": "Você atingiu 100% em Português, Matemática, Turma e Exclusivas. Um feito máximo no AVA MJ.",
    }

    def _fmt_fortaleza(self, dt: datetime | None) -> str | None:
        if not dt:
            return None
        aware = dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(self._TZ_FORTALEZA)
        return aware.strftime("%d/%m/%Y %H:%M")

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
                existing.automatica = bool(item.get("automatica", False))
                continue
            db.add(
                MedalhaTipo(
                    nome=item["nome"],
                    slug=item["slug"],
                    icone=item["icone"],
                    cor=item["cor"],
                    ordem=item["ordem"],
                    ativo=True,
                    automatica=bool(item.get("automatica", False)),
                )
            )
            created += 1
        db.commit()
        return created

    def list_tipos_ativos(self, db: Session, *, include_automaticas: bool = False) -> list[MedalhaTipo]:
        q = db.query(MedalhaTipo).filter(MedalhaTipo.ativo.is_(True))
        if not include_automaticas:
            q = q.filter(MedalhaTipo.automatica.is_(False))
        return q.order_by(MedalhaTipo.ordem, MedalhaTipo.nome).all()

    def _curso_ids_por_materia(self, db: Session, like_expr: str) -> set[int]:
        rows = db.query(Curso.id).filter(Curso.nome.ilike(like_expr)).all()
        return {int(r[0]) for r in rows}

    def _atividades_ids_trilha_por_curso_e_ano(
        self, db: Session, *, curso_ids: set[int], ano_escolar: int | None
    ) -> set[int]:
        if not curso_ids:
            return set()
        q = (
            db.query(AtividadeH5P.id)
            .join(Trilha, Trilha.id == AtividadeH5P.trilha_id)
            .filter(
                AtividadeH5P.ativo.is_(True),
                Trilha.curso_id.in_(curso_ids),
            )
        )
        if ano_escolar is not None:
            q = q.filter(Trilha.ano_escolar == ano_escolar)
        return {int(r[0]) for r in q.all()}

    def _concluidas_h5p_trilha(self, db: Session, *, aluno_id: int, atividade_ids: set[int]) -> int:
        if not atividade_ids:
            return 0
        return (
            db.query(func.count(ProgressoH5P.id))
            .filter(
                ProgressoH5P.aluno_id == aluno_id,
                ProgressoH5P.concluido.is_(True),
                ProgressoH5P.atividade_id.in_(atividade_ids),
            )
            .scalar()
            or 0
        )

    def _prof_atividades_categoria_ids(self, db: Session, *, aluno: Aluno) -> tuple[set[int], set[int]]:
        if not aluno.turma_id:
            return set(), set()
        atividades = (
            db.query(ProfessorAtividadeH5P.id)
            .filter(
                ProfessorAtividadeH5P.turma_id == aluno.turma_id,
                ProfessorAtividadeH5P.ativo.is_(True),
            )
            .all()
        )
        all_ids = {int(r[0]) for r in atividades}
        if not all_ids:
            return set(), set()

        target_counts = {
            int(aid): int(cnt)
            for aid, cnt in (
                db.query(
                    ProfessorAtividadeH5PAluno.atividade_id,
                    func.count(ProfessorAtividadeH5PAluno.id),
                )
                .filter(ProfessorAtividadeH5PAluno.atividade_id.in_(all_ids))
                .group_by(ProfessorAtividadeH5PAluno.atividade_id)
                .all()
            )
        }
        turma_ids = {aid for aid in all_ids if target_counts.get(aid, 0) == 0}
        if not target_counts:
            return turma_ids, set()

        targeted_ids = {aid for aid, cnt in target_counts.items() if cnt > 0}
        minhas_exclusivas = {
            int(r[0])
            for r in (
                db.query(ProfessorAtividadeH5PAluno.atividade_id)
                .filter(
                    ProfessorAtividadeH5PAluno.atividade_id.in_(targeted_ids),
                    ProfessorAtividadeH5PAluno.aluno_id == aluno.id,
                )
                .all()
            )
        }
        return turma_ids, minhas_exclusivas

    def _concluidas_h5p_professor(self, db: Session, *, aluno_id: int, atividade_ids: set[int]) -> int:
        if not atividade_ids:
            return 0
        return (
            db.query(func.count(ProfessorProgressoH5P.id))
            .filter(
                ProfessorProgressoH5P.aluno_id == aluno_id,
                ProfessorProgressoH5P.concluido.is_(True),
                ProfessorProgressoH5P.atividade_id.in_(atividade_ids),
            )
            .scalar()
            or 0
        )

    def _pct(self, total: int, concluidas: int) -> int:
        if not total:
            return 0
        return int(round((concluidas / total) * 100))

    def _elegivel(self, total: int, concluidas: int) -> bool:
        return total > 0 and concluidas >= total

    def compute_auto_medalha_status(self, db: Session, aluno_id: int) -> dict[str, dict[str, Any]]:
        aluno = db.query(Aluno).filter(Aluno.id == aluno_id).one_or_none()
        if not aluno:
            return {}

        curso_lp = self._curso_ids_por_materia(db, "%portug%")
        curso_mat = self._curso_ids_por_materia(db, "%matem%")
        ids_lp = self._atividades_ids_trilha_por_curso_e_ano(
            db, curso_ids=curso_lp, ano_escolar=aluno.ano_escolar
        )
        ids_mat = self._atividades_ids_trilha_por_curso_e_ano(
            db, curso_ids=curso_mat, ano_escolar=aluno.ano_escolar
        )
        concl_lp = self._concluidas_h5p_trilha(db, aluno_id=aluno.id, atividade_ids=ids_lp)
        concl_mat = self._concluidas_h5p_trilha(db, aluno_id=aluno.id, atividade_ids=ids_mat)

        turma_ids, exclusivas_ids = self._prof_atividades_categoria_ids(db, aluno=aluno)
        concl_turma = self._concluidas_h5p_professor(
            db, aluno_id=aluno.id, atividade_ids=turma_ids
        )
        concl_exclusivas = self._concluidas_h5p_professor(
            db, aluno_id=aluno.id, atividade_ids=exclusivas_ids
        )

        raw = {
            "jornada_portugues_100": (len(ids_lp), concl_lp),
            "jornada_matematica_100": (len(ids_mat), concl_mat),
            "atividades_turma_100": (len(turma_ids), concl_turma),
            "missoes_exclusivas_100": (len(exclusivas_ids), concl_exclusivas),
        }
        categorias_base = list(raw.values())
        total_cat = len(categorias_base)
        concl_cat = sum(
            1 for total, concluidas in categorias_base if self._elegivel(total, concluidas)
        )
        raw["conclusao_total_ava_100"] = (total_cat, concl_cat)
        out: dict[str, dict[str, Any]] = {}
        for slug, (total, concluidas) in raw.items():
            out[slug] = {
                "slug": slug,
                "total": int(total),
                "concluidas": int(concluidas),
                "pct": self._pct(total, concluidas),
                "elegivel": self._elegivel(total, concluidas),
            }
        return out

    def sync_auto_medalhas_aluno(self, db: Session, aluno_id: int) -> dict[str, dict[str, Any]]:
        status = self.compute_auto_medalha_status(db, aluno_id)
        if not status:
            return status

        tipos = {
            t.slug: t
            for t in (
                db.query(MedalhaTipo)
                .filter(MedalhaTipo.slug.in_(list(status.keys())))
                .all()
            )
        }
        now = datetime.utcnow()
        changed = False
        for slug, info in status.items():
            tipo = tipos.get(slug)
            if not tipo:
                continue
            row = (
                db.query(AlunoMedalhaAutomatica)
                .filter(
                    AlunoMedalhaAutomatica.aluno_id == aluno_id,
                    AlunoMedalhaAutomatica.medalha_tipo_id == tipo.id,
                )
                .one_or_none()
            )
            if not row:
                row = AlunoMedalhaAutomatica(
                    aluno_id=aluno_id,
                    medalha_tipo_id=tipo.id,
                    conquistada=False,
                    concedida_em=None,
                    updated_at=now,
                )
                db.add(row)
                changed = True

            should_have = bool(info["elegivel"])
            if should_have and not row.conquistada:
                row.conquistada = True
                row.concedida_em = now
                row.updated_at = now
                changed = True
            elif not should_have and row.conquistada:
                row.conquistada = False
                row.concedida_em = None
                row.updated_at = now
                changed = True
            info["conquistada"] = bool(row.conquistada)
            info["concedida_em"] = row.concedida_em
            info["medalha_tipo_id"] = tipo.id

        if changed:
            db.commit()
        return status

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
        tipo = (
            db.query(MedalhaTipo)
            .filter(
                MedalhaTipo.id == medalha_tipo_id,
                MedalhaTipo.ativo.is_(True),
                MedalhaTipo.automatica.is_(False),
            )
            .one_or_none()
        )
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
        manual_rows = (
            db.query(AlunoMedalha, MedalhaTipo)
            .join(MedalhaTipo, MedalhaTipo.id == AlunoMedalha.medalha_tipo_id)
            .filter(AlunoMedalha.aluno_id == aluno_id)
            .order_by(AlunoMedalha.concedida_em.desc())
            .all()
        )
        auto_rows = (
            db.query(AlunoMedalhaAutomatica, MedalhaTipo)
            .join(MedalhaTipo, MedalhaTipo.id == AlunoMedalhaAutomatica.medalha_tipo_id)
            .filter(
                AlunoMedalhaAutomatica.aluno_id == aluno_id,
                AlunoMedalhaAutomatica.conquistada.is_(True),
                MedalhaTipo.ativo.is_(True),
            )
            .all()
        )
        out: list[dict[str, Any]] = []
        for item, tipo in manual_rows:
            out.append(
                {
                    "nome": tipo.nome,
                    "icone": tipo.icone,
                    "cor": tipo.cor,
                    "concedida_em": item.concedida_em,
                    "concedida_em_label": self._fmt_fortaleza(item.concedida_em),
                    "automatica": False,
                }
            )
        for item, tipo in auto_rows:
            out.append(
                {
                    "nome": tipo.nome,
                    "icone": tipo.icone,
                    "cor": tipo.cor,
                    "concedida_em": item.concedida_em,
                    "concedida_em_label": self._fmt_fortaleza(item.concedida_em),
                    "automatica": True,
                }
            )
        out.sort(key=lambda x: x.get("concedida_em") or datetime.min, reverse=True)
        if limit > 0:
            out = out[:limit]
        return out

    def count_mural_aluno(self, db: Session, aluno_id: int) -> int:
        manual_count = (
            db.query(func.count(AlunoMedalha.id))
            .filter(AlunoMedalha.aluno_id == aluno_id)
            .scalar()
            or 0
        )
        auto_count = (
            db.query(func.count(AlunoMedalhaAutomatica.id))
            .join(MedalhaTipo, MedalhaTipo.id == AlunoMedalhaAutomatica.medalha_tipo_id)
            .filter(
                AlunoMedalhaAutomatica.aluno_id == aluno_id,
                AlunoMedalhaAutomatica.conquistada.is_(True),
                MedalhaTipo.ativo.is_(True),
            )
            .scalar()
            or 0
        )
        return int(manual_count + auto_count)

    def list_medalhas_aluno_com_status(self, db: Session, aluno_id: int) -> list[dict[str, Any]]:
        auto_status = self.sync_auto_medalhas_aluno(db, aluno_id)
        tipos = (
            db.query(MedalhaTipo)
            .filter(MedalhaTipo.ativo.is_(True))
            .order_by(MedalhaTipo.ordem.asc(), MedalhaTipo.nome.asc())
            .all()
        )

        manual_rows = (
            db.query(AlunoMedalha, MedalhaTipo)
            .join(MedalhaTipo, MedalhaTipo.id == AlunoMedalha.medalha_tipo_id)
            .filter(AlunoMedalha.aluno_id == aluno_id)
            .all()
        )
        manual_latest_by_tipo: dict[int, datetime | None] = {}
        manual_count_by_tipo: dict[int, int] = {}
        for row, tipo in manual_rows:
            manual_count_by_tipo[tipo.id] = manual_count_by_tipo.get(tipo.id, 0) + 1
            prev = manual_latest_by_tipo.get(tipo.id)
            if prev is None or (row.concedida_em and row.concedida_em > prev):
                manual_latest_by_tipo[tipo.id] = row.concedida_em

        auto_rows = (
            db.query(AlunoMedalhaAutomatica)
            .filter(AlunoMedalhaAutomatica.aluno_id == aluno_id)
            .all()
        )
        auto_by_tipo = {r.medalha_tipo_id: r for r in auto_rows}

        out: list[dict[str, Any]] = []
        for tipo in tipos:
            is_auto = bool(getattr(tipo, "automatica", False))
            if is_auto:
                st = auto_status.get(tipo.slug, {})
                auto_row = auto_by_tipo.get(tipo.id)
                conquistada = bool(auto_row and auto_row.conquistada)
                out.append(
                    {
                        "tipo_id": tipo.id,
                        "nome": tipo.nome,
                        "slug": tipo.slug,
                        "icone": tipo.icone,
                        "cor": tipo.cor,
                        "automatica": True,
                        "conquistada": conquistada,
                        "concedida_em": auto_row.concedida_em if auto_row else None,
                        "concedida_em_label": self._fmt_fortaleza(auto_row.concedida_em) if auto_row else None,
                        "total": int(st.get("total") or 0),
                        "concluidas": int(st.get("concluidas") or 0),
                        "pct": int(st.get("pct") or 0),
                        "elegivel": bool(st.get("elegivel")),
                        "count": 1 if conquistada else 0,
                        "descricao": self._AUTO_MEDAL_DESCRIPTIONS.get(
                            tipo.slug, "Medalha automática por conclusão da categoria."
                        ),
                    }
                )
            else:
                count = int(manual_count_by_tipo.get(tipo.id, 0))
                out.append(
                    {
                        "tipo_id": tipo.id,
                        "nome": tipo.nome,
                        "slug": tipo.slug,
                        "icone": tipo.icone,
                        "cor": tipo.cor,
                        "automatica": False,
                        "conquistada": count > 0,
                        "concedida_em": manual_latest_by_tipo.get(tipo.id),
                        "concedida_em_label": self._fmt_fortaleza(manual_latest_by_tipo.get(tipo.id)),
                        "total": 0,
                        "concluidas": 0,
                        "pct": 100 if count > 0 else 0,
                        "elegivel": count > 0,
                        "count": count,
                        "descricao": "Medalha concedida por professor com base em desempenho, participação e evolução.",
                    }
                )
        return out

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
        alunos_scope_rows = (
            db.query(Aluno.id)
            .filter(Aluno.turma_id.in_(turma_ids))
            .all()
        )
        aluno_ids_scope = {int(r[0]) for r in alunos_scope_rows}

        manual_total = (
            db.query(func.count(AlunoMedalha.id)).filter(AlunoMedalha.envio_id.in_(envio_ids)).scalar() or 0
        ) if envio_ids else 0
        manual_impactados_ids = {
            int(r[0])
            for r in (
                db.query(AlunoMedalha.aluno_id)
                .filter(AlunoMedalha.envio_id.in_(envio_ids))
                .distinct()
                .all()
            )
        } if envio_ids else set()
        auto_total = (
            db.query(func.count(AlunoMedalhaAutomatica.id))
            .join(MedalhaTipo, MedalhaTipo.id == AlunoMedalhaAutomatica.medalha_tipo_id)
            .filter(
                AlunoMedalhaAutomatica.aluno_id.in_(aluno_ids_scope) if aluno_ids_scope else False,
                AlunoMedalhaAutomatica.conquistada.is_(True),
                MedalhaTipo.ativo.is_(True),
                MedalhaTipo.automatica.is_(True),
            )
            .scalar()
            or 0
        )
        auto_impactados_ids = {
            int(r[0])
            for r in (
                db.query(AlunoMedalhaAutomatica.aluno_id)
                .join(MedalhaTipo, MedalhaTipo.id == AlunoMedalhaAutomatica.medalha_tipo_id)
                .filter(
                    AlunoMedalhaAutomatica.aluno_id.in_(aluno_ids_scope) if aluno_ids_scope else False,
                    AlunoMedalhaAutomatica.conquistada.is_(True),
                    MedalhaTipo.ativo.is_(True),
                    MedalhaTipo.automatica.is_(True),
                )
                .distinct()
                .all()
            )
        }
        totais = {
            "envios": len(envio_ids),
            "medalhas": int(manual_total + auto_total),
            "alunos_impactados": int(len(manual_impactados_ids | auto_impactados_ids)),
        }

        ranking_map: dict[str, int] = {}
        if envio_ids:
            ranking_rows = (
                db.query(Usuario.nome, func.count(AlunoMedalha.id).label("total"))
                .join(Aluno, Aluno.usuario_id == Usuario.id)
                .join(AlunoMedalha, AlunoMedalha.aluno_id == Aluno.id)
                .filter(AlunoMedalha.envio_id.in_(envio_ids))
                .group_by(Usuario.nome)
                .all()
            )
            for nome, total in ranking_rows:
                ranking_map[nome] = ranking_map.get(nome, 0) + int(total or 0)

        if aluno_ids_scope:
            auto_ranking_rows = (
                db.query(Usuario.nome, func.count(AlunoMedalhaAutomatica.id).label("total"))
                .join(Aluno, Aluno.usuario_id == Usuario.id)
                .join(AlunoMedalhaAutomatica, AlunoMedalhaAutomatica.aluno_id == Aluno.id)
                .join(MedalhaTipo, MedalhaTipo.id == AlunoMedalhaAutomatica.medalha_tipo_id)
                .filter(
                    Aluno.id.in_(aluno_ids_scope),
                    AlunoMedalhaAutomatica.conquistada.is_(True),
                    MedalhaTipo.automatica.is_(True),
                    MedalhaTipo.ativo.is_(True),
                )
                .group_by(Usuario.nome)
                .all()
            )
            for nome, total in auto_ranking_rows:
                ranking_map[nome] = ranking_map.get(nome, 0) + int(total or 0)

        ranking_alunos = [
            {"nome": nome, "total": total}
            for nome, total in sorted(ranking_map.items(), key=lambda it: (-it[1], it[0]))[:10]
        ]

        dist_map: dict[tuple[str, str, str], int] = {}
        if envio_ids:
            dist_rows = (
                db.query(
                    MedalhaTipo.nome,
                    MedalhaTipo.icone,
                    MedalhaTipo.cor,
                    func.count(AlunoMedalha.id).label("total"),
                )
                .join(AlunoMedalha, AlunoMedalha.medalha_tipo_id == MedalhaTipo.id)
                .filter(AlunoMedalha.envio_id.in_(envio_ids))
                .group_by(MedalhaTipo.nome, MedalhaTipo.icone, MedalhaTipo.cor)
                .all()
            )
            for n, i, c, t in dist_rows:
                dist_map[(n, i, c)] = dist_map.get((n, i, c), 0) + int(t or 0)

        if aluno_ids_scope:
            auto_dist_rows = (
                db.query(
                    MedalhaTipo.nome,
                    MedalhaTipo.icone,
                    MedalhaTipo.cor,
                    func.count(AlunoMedalhaAutomatica.id).label("total"),
                )
                .join(AlunoMedalhaAutomatica, AlunoMedalhaAutomatica.medalha_tipo_id == MedalhaTipo.id)
                .filter(
                    AlunoMedalhaAutomatica.aluno_id.in_(aluno_ids_scope),
                    AlunoMedalhaAutomatica.conquistada.is_(True),
                    MedalhaTipo.automatica.is_(True),
                    MedalhaTipo.ativo.is_(True),
                )
                .group_by(MedalhaTipo.nome, MedalhaTipo.icone, MedalhaTipo.cor)
                .all()
            )
            for n, i, c, t in auto_dist_rows:
                dist_map[(n, i, c)] = dist_map.get((n, i, c), 0) + int(t or 0)

        distribuicao_tipos = [
            {"nome": n, "icone": i, "cor": c, "total": total}
            for (n, i, c), total in sorted(dist_map.items(), key=lambda it: (-it[1], it[0][0]))
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
