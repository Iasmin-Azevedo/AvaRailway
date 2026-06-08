from __future__ import annotations

import csv
import io
import re
import unicodedata
from datetime import datetime
from typing import Any

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.aluno import Aluno
from app.models.avaliacao import (
    Avaliacao,
    AplicacaoProva,
    BancoQuestao,
    LoteImportacaoGabarito,
    OrigemBancoQuestao,
    ParticipacaoAplicacaoProva,
    Questao,
    StatusAplicacaoProva,
    StatusAvaliacao,
    TipoAvaliacao,
)
from app.models.gestao import Curso, Escola, Trilha, Turma
from app.models.relacoes import ProfessorTurma
from app.models.resposta import RespostaAluno
from app.models.saeb import Descritor
from app.models.user import Usuario
from app.repositories.avaliacao_repository import AvaliacaoRepository
from app.services.ia_service import IAService
from app.services.gamificacao_service import GamificacaoService


def _iniciais_nome(nome: str | None) -> str:
    label = (nome or "").strip()
    partes = label.split()
    if len(partes) >= 2:
        return (partes[0][0] + partes[-1][0]).upper()
    if len(partes) == 1 and len(partes[0]) >= 2:
        return partes[0][:2].upper()
    return "AL"


class AvaliacaoService:
    def __init__(self):
        self.repo = AvaliacaoRepository()
        self.ia = IAService()
        self.gamificacao = GamificacaoService()

    @staticmethod
    def _slug_csv_key(value: str | None) -> str:
        raw = (value or "").strip().lower()
        if not raw:
            return ""
        normalized = unicodedata.normalize("NFKD", raw)
        ascii_only = "".join(ch for ch in normalized if not unicodedata.combining(ch))
        ascii_only = ascii_only.replace("ç", "c")
        return re.sub(r"[^a-z0-9]+", "_", ascii_only).strip("_")

    def _normalizar_row_csv(self, row: dict[str, Any]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for key, value in row.items():
            normalized[self._slug_csv_key(str(key))] = (str(value) if value is not None else "").strip()
        return normalized

    def _parse_linhas_csv_largo(
        self,
        *,
        row: dict[str, str],
        idx: int,
        questoes_by_numero: dict[str, Any],
    ) -> tuple[list[dict[str, str]], list[str]]:
        linhas: list[dict[str, str]] = []
        erros: list[str] = []
        aluno_id = row.get("aluno_id") or row.get("id") or ""
        aluno_nome = row.get("aluno_nome") or row.get("nome") or ""
        aluno_email = row.get("aluno_email") or row.get("email") or ""
        for col, value in row.items():
            if not col.startswith("questao_"):
                continue
            sufixo = col.replace("questao_", "", 1).strip("_")
            q_numero = "".join(ch for ch in sufixo if ch.isdigit())
            if not q_numero:
                continue
            marcada = (value or "").strip().upper()[:1]
            if not marcada:
                continue
            if marcada not in {"A", "B", "C", "D", "E"}:
                erros.append(f"Linha {idx}: resposta inválida na coluna {col}.")
                continue
            if q_numero not in questoes_by_numero:
                erros.append(f"Linha {idx}: questão {q_numero} não existe na prova.")
                continue
            linhas.append(
                {
                    "aluno_id": aluno_id,
                    "aluno_nome": aluno_nome,
                    "aluno_email": aluno_email,
                    "questao_numero": q_numero,
                    "resposta_marcada": marcada,
                }
            )
        return linhas, erros

    def gerar_modelo_importacao_aplicacao_csv(self, db: Session, *, aplicacao_id: int) -> tuple[str, str]:
        aplicacao = self.repo.get_aplicacao_prova(db, aplicacao_id)
        if not aplicacao:
            raise ValueError("Aplicação não encontrada.")
        questoes = (
            db.query(Questao)
            .filter(Questao.avaliacao_id == aplicacao.avaliacao_id)
            .order_by(Questao.numero.asc(), Questao.id.asc())
            .all()
        )
        participacoes = (
            db.query(ParticipacaoAplicacaoProva, Usuario.nome)
            .join(Aluno, Aluno.id == ParticipacaoAplicacaoProva.aluno_id)
            .join(Usuario, Usuario.id == Aluno.usuario_id)
            .filter(ParticipacaoAplicacaoProva.aplicacao_id == aplicacao_id)
            .order_by(Usuario.nome.asc())
            .all()
        )
        headers = ["ID", "NOME"] + [f"QUESTAO {q.numero or i}" for i, q in enumerate(questoes, start=1)]
        output = io.StringIO()
        writer = csv.writer(output, delimiter=";", quoting=csv.QUOTE_MINIMAL)
        writer.writerow(headers)
        for p, nome in participacoes:
            writer.writerow([p.aluno_id, nome or ""] + [""] * len(questoes))
        if not participacoes:
            writer.writerow(["1", "Aluno Exemplo"] + [""] * len(questoes))
        return output.getvalue(), f"modelo_importacao_aplicacao_{aplicacao_id}.csv"

    async def processar_prova(self, db: Session, aluno_id: int, dados):
        avaliacao = self.repo.get_avaliacao(db, dados.avaliacao_id)
        if not avaliacao:
            raise ValueError("Prova não encontrada.")

        aluno = db.query(Aluno).filter(Aluno.id == aluno_id).first()
        if not aluno:
            raise ValueError("Aluno não encontrado.")

        aplicacao = None
        participacao = None
        if getattr(dados, "aplicacao_id", None):
            aplicacao = self.repo.get_aplicacao_prova(db, dados.aplicacao_id)
            if not aplicacao or aplicacao.avaliacao_id != avaliacao.id:
                raise ValueError("Aplicação de prova inválida.")
            participacao = self.repo.get_or_create_participacao(
                db,
                aplicacao_id=aplicacao.id,
                aluno_id=aluno.id,
                turma_id_snapshot=aluno.turma_id,
                escola_id_snapshot=self._escola_id_do_aluno(db, aluno),
            )

        acertos = 0
        total = len(avaliacao.questoes or [])

        for resp in dados.respostas:
            questao = next((q for q in avaliacao.questoes if q.id == resp.questao_id), None)
            if not questao:
                continue

            e_correto = False
            resposta_marcada = (resp.alternativa_escolhida or "").strip().upper()[:1]
            if questao.gabarito == resposta_marcada:
                acertos += 1
                e_correto = True

            self.repo.upsert_resposta_importada(
                db,
                aluno_id=aluno_id,
                avaliacao_id=dados.avaliacao_id,
                aplicacao_id=getattr(aplicacao, "id", None),
                participacao_id=getattr(participacao, "id", None),
                questao_id=resp.questao_id,
                marcada=resposta_marcada,
                correta=e_correto,
                pontuacao=float(getattr(questao, "peso", 1.0) or 1.0) if e_correto and questao else 0.0,
                lote_importacao_id=None,
            )

        if participacao:
            self._recalcular_participacao(db, participacao_id=participacao.id, total_questoes=total)
            if aplicacao and getattr(aplicacao, "status", None) == StatusAplicacaoProva.PLANEJADA:
                aplicacao.status = StatusAplicacaoProva.EM_ANDAMENTO
            db.commit()

        feedback = self.ia.gerar_feedback(acertos, total)
        await self.gamificacao.processar_xp({"aluno_id": aluno_id, "acertos": acertos}, db)

        return {
            "total_questoes": total,
            "acertos": acertos,
            "nota": (acertos / total) * 10 if total else 0,
            "mensagem_ia": feedback,
        }

    def criar_avaliacao_objetiva(
        self,
        db: Session,
        *,
        titulo: str,
        descricao: str,
        codigo: str | None,
        ano_letivo: str | None,
        curso_id: int | None = None,
        trilha_id: int | None = None,
        ano_escolar: int | None = None,
        criado_por_usuario_id: int | None = None,
        escopo: str | None = "rede",
        status: StatusAvaliacao = StatusAvaliacao.ATIVA,
    ) -> Avaliacao:
        if trilha_id:
            existente = db.query(Avaliacao).filter(Avaliacao.trilha_id == trilha_id).first()
            if existente:
                raise ValueError("Essa trilha já possui uma prova vinculada.")
        obj = Avaliacao(
            titulo=titulo,
            descricao=descricao,
            codigo=(codigo or "").strip() or None,
            ano_letivo=(ano_letivo or "").strip() or None,
            escopo=(escopo or "").strip() or None,
            tipo=TipoAvaliacao.OBJETIVA,
            status=status,
            curso_id=curso_id,
            trilha_id=trilha_id,
            ano_escolar=ano_escolar,
            criado_por_usuario_id=criado_por_usuario_id,
        )
        db.add(obj)
        db.commit()
        db.refresh(obj)
        return obj

    def criar_banco_questao(
        self,
        db: Session,
        *,
        autor_usuario_id: int | None,
        curso_id: int | None,
        ano_escolar: int | None,
        descritor_id: int | None,
        conteudo: str | None = None,
        tipo_questao: str = "multipla_escolha",
        enunciado: str,
        gabarito: str,
        alternativa_a: str,
        alternativa_b: str,
        alternativa_c: str,
        alternativa_d: str,
        alternativa_e: str,
        origem: OrigemBancoQuestao = OrigemBancoQuestao.MANUAL,
        habilidade_saeb: str | None = None,
        codigo_referencia: str | None = None,
        observacoes: str | None = None,
    ) -> BancoQuestao:
        habilidade_final = (habilidade_saeb or "").strip() or None
        if descritor_id and not habilidade_final:
            habilidade_final = self._descritor_codigo(db, descritor_id)
        return self.repo.create_banco_questao(
            db,
            autor_usuario_id=autor_usuario_id,
            curso_id=curso_id,
            ano_escolar=ano_escolar,
            descritor_id=descritor_id,
            conteudo=(conteudo or "").strip() or None,
            tipo_questao=(tipo_questao or "").strip() or "multipla_escolha",
            origem=origem,
            enunciado=enunciado,
            alternativa_a=alternativa_a,
            alternativa_b=alternativa_b,
            alternativa_c=alternativa_c,
            alternativa_d=alternativa_d,
            alternativa_e=alternativa_e,
            gabarito=(gabarito or "").strip().upper()[:1],
            habilidade_saeb=habilidade_final,
            codigo_referencia=(codigo_referencia or "").strip() or None,
            observacoes=(observacoes or "").strip() or None,
        )

    def listar_banco_questoes(
        self,
        db: Session,
        *,
        autor_usuario_id: int | None = None,
        curso_id: int | None = None,
        ano_escolar: int | None = None,
        descritor_id: int | None = None,
        conteudo: str | None = None,
        termo: str | None = None,
        tipo_questao: str | None = None,
    ) -> list[BancoQuestao]:
        q = db.query(BancoQuestao).filter(BancoQuestao.ativo.is_(True))
        if autor_usuario_id:
            q = q.filter(BancoQuestao.autor_usuario_id == autor_usuario_id)
        if curso_id:
            q = q.filter(BancoQuestao.curso_id == curso_id)
        if ano_escolar:
            q = q.filter(BancoQuestao.ano_escolar == ano_escolar)
        if descritor_id:
            q = q.filter(BancoQuestao.descritor_id == descritor_id)
        if conteudo:
            q = q.filter(func.lower(BancoQuestao.conteudo).like(f"%{conteudo.strip().lower()}%"))
        if termo:
            termo_like = f"%{termo.strip().lower()}%"
            q = q.filter(
                func.lower(BancoQuestao.enunciado).like(termo_like)
                | func.lower(BancoQuestao.codigo_referencia).like(termo_like)
            )
        if tipo_questao:
            q = q.filter(BancoQuestao.tipo_questao == tipo_questao)
        return q.order_by(BancoQuestao.id.desc()).all()

    def get_banco_questao(self, db: Session, banco_questao_id: int) -> BancoQuestao | None:
        return self.repo.get_banco_questao(db, banco_questao_id)

    def atualizar_banco_questao(
        self,
        db: Session,
        *,
        banco_questao_id: int,
        curso_id: int | None,
        ano_escolar: int | None,
        descritor_id: int | None,
        conteudo: str | None,
        tipo_questao: str,
        enunciado: str,
        gabarito: str,
        alternativa_a: str,
        alternativa_b: str,
        alternativa_c: str,
        alternativa_d: str,
        alternativa_e: str,
        observacoes: str | None = None,
    ) -> BancoQuestao | None:
        habilidade_final = self._descritor_codigo(db, descritor_id) if descritor_id else None
        return self.repo.update_banco_questao(
            db,
            banco_questao_id=banco_questao_id,
            curso_id=curso_id,
            ano_escolar=ano_escolar,
            descritor_id=descritor_id,
            conteudo=(conteudo or "").strip() or None,
            tipo_questao=(tipo_questao or "").strip() or "multipla_escolha",
            enunciado=enunciado,
            alternativa_a=alternativa_a,
            alternativa_b=alternativa_b,
            alternativa_c=alternativa_c,
            alternativa_d=alternativa_d,
            alternativa_e=alternativa_e,
            gabarito=(gabarito or "").strip().upper()[:1],
            habilidade_saeb=habilidade_final,
            observacoes=(observacoes or "").strip() or None,
        )

    def excluir_banco_questao(self, db: Session, banco_questao_id: int) -> bool:
        return self.repo.soft_delete_banco_questao(db, banco_questao_id)

    def anexar_questao_banco(
        self,
        db: Session,
        *,
        avaliacao_id: int,
        banco_questao_id: int,
        numero: int | None = None,
        peso: float = 1.0,
    ) -> Questao:
        avaliacao = self.repo.get_avaliacao(db, avaliacao_id)
        if not avaliacao:
            raise ValueError("Prova não encontrada.")
        banco_questao = db.query(BancoQuestao).filter(BancoQuestao.id == banco_questao_id).first()
        if not banco_questao:
            raise ValueError("Questão do banco não encontrada.")
        disciplina = self._curso_nome(db, banco_questao.curso_id)
        numero_final = numero or (len(avaliacao.questoes) + 1)
        return self.repo.create_questao_from_bank(
            db,
            avaliacao_id=avaliacao_id,
            banco_questao=banco_questao,
            numero=numero_final,
            peso=max(0.0, float(peso or 1.0)),
            disciplina=disciplina,
            codigo=(banco_questao.codigo_referencia or "").strip() or None,
        )

    def criar_prova_com_questoes(
        self,
        db: Session,
        *,
        titulo: str,
        descricao: str,
        codigo: str | None,
        ano_letivo: str | None,
        curso_id: int | None = None,
        trilha_id: int | None = None,
        ano_escolar: int | None = None,
        criado_por_usuario_id: int | None = None,
        escopo: str | None = "turma",
        banco_questao_ids: list[int] | None = None,
    ) -> Avaliacao:
        avaliacao = self.criar_avaliacao_objetiva(
            db,
            titulo=titulo,
            descricao=descricao,
            codigo=codigo,
            ano_letivo=ano_letivo,
            curso_id=curso_id,
            trilha_id=trilha_id,
            ano_escolar=ano_escolar,
            criado_por_usuario_id=criado_por_usuario_id,
            escopo=escopo,
        )
        for index, banco_questao_id in enumerate(banco_questao_ids or [], start=1):
            self.anexar_questao_banco(
                db,
                avaliacao_id=avaliacao.id,
                banco_questao_id=banco_questao_id,
                numero=index,
            )
        return self.repo.get_avaliacao(db, avaliacao.id) or avaliacao

    def atualizar_prova_com_questoes(
        self,
        db: Session,
        *,
        avaliacao_id: int,
        titulo: str,
        descricao: str,
        ano_letivo: str | None,
        curso_id: int | None = None,
        trilha_id: int | None = None,
        ano_escolar: int | None = None,
        banco_questao_ids: list[int] | None = None,
    ) -> Avaliacao:
        avaliacao = self.repo.get_avaliacao(db, avaliacao_id)
        if not avaliacao:
            raise ValueError("Prova não encontrada.")
        if avaliacao.aplicacoes:
            app_ids = [a.id for a in avaliacao.aplicacoes]
            tem_respostas = (
                db.query(func.count(RespostaAluno.id))
                .filter(RespostaAluno.aplicacao_id.in_(app_ids))
                .scalar()
                or 0
            ) > 0
            if tem_respostas:
                raise ValueError("Não é possível editar uma prova que já possui respostas lançadas.")
        if trilha_id:
            existente = db.query(Avaliacao).filter(Avaliacao.trilha_id == trilha_id, Avaliacao.id != avaliacao_id).first()
            if existente:
                raise ValueError("Essa trilha já possui uma prova vinculada.")
        atualizada = self.repo.update_avaliacao(
            db,
            avaliacao_id=avaliacao_id,
            titulo=titulo,
            descricao=descricao,
            ano_letivo=ano_letivo,
            curso_id=curso_id,
            trilha_id=trilha_id,
            ano_escolar=ano_escolar,
        )
        banco_questoes = []
        for banco_questao_id in banco_questao_ids or []:
            banco = self.repo.get_banco_questao(db, banco_questao_id)
            if banco:
                banco_questoes.append(banco)
        self.repo.replace_questoes_da_avaliacao(
            db,
            avaliacao_id=avaliacao_id,
            banco_questoes=banco_questoes,
        )
        return self.repo.get_avaliacao(db, avaliacao_id) or atualizada

    def atualizar_aplicacao_prova(
        self,
        db: Session,
        *,
        aplicacao_id: int,
        titulo: str | None = None,
        ano_letivo: str | None = None,
        periodo_referencia: str | None = None,
        data_aplicacao: datetime | None = None,
        observacoes: str | None = None,
        status: str | StatusAplicacaoProva | None = None,
    ) -> AplicacaoProva:
        aplicacao = self.repo.get_aplicacao_prova(db, aplicacao_id)
        if not aplicacao:
            raise ValueError("Aplicação não encontrada.")
        if status:
            try:
                status_final = status if isinstance(status, StatusAplicacaoProva) else StatusAplicacaoProva(str(status))
            except Exception:
                raise ValueError("Status da aplicação inválido.")
            aplicacao.status = status_final
        aplicacao.titulo = (titulo or "").strip() or None
        aplicacao.ano_letivo = (ano_letivo or "").strip() or None
        aplicacao.periodo_referencia = (periodo_referencia or "").strip() or None
        aplicacao.data_aplicacao = data_aplicacao
        aplicacao.observacoes = (observacoes or "").strip() or None
        db.add(aplicacao)
        db.commit()
        db.refresh(aplicacao)
        return aplicacao

    def excluir_aplicacao_prova(self, db: Session, aplicacao_id: int) -> bool:
        aplicacao = self.repo.get_aplicacao_prova(db, aplicacao_id)
        if not aplicacao:
            return False
        db.query(RespostaAluno).filter(RespostaAluno.aplicacao_id == aplicacao_id).delete(synchronize_session=False)
        db.query(LoteImportacaoGabarito).filter(LoteImportacaoGabarito.aplicacao_id == aplicacao_id).delete(
            synchronize_session=False
        )
        db.delete(aplicacao)
        db.commit()
        return True

    def excluir_prova(self, db: Session, avaliacao_id: int) -> bool:
        avaliacao = self.repo.get_avaliacao(db, avaliacao_id)
        if not avaliacao:
            return False
        return self.repo.delete_avaliacao(db, avaliacao_id)

    def adicionar_questao(
        self,
        db: Session,
        *,
        avaliacao_id: int,
        enunciado: str,
        gabarito: str,
        habilidade_saeb: str | None,
        alternativa_a: str,
        alternativa_b: str,
        alternativa_c: str,
        alternativa_d: str,
        alternativa_e: str,
        numero: int | None = None,
        codigo: str | None = None,
        disciplina: str | None = None,
        conteudo: str | None = None,
        tipo_questao: str = "multipla_escolha",
        descritor_id: int | None = None,
        autor_usuario_id: int | None = None,
        peso: float = 1.0,
    ) -> Questao:
        banco = self.criar_banco_questao(
            db,
            autor_usuario_id=autor_usuario_id,
            curso_id=self._curso_id_by_nome(db, disciplina),
            ano_escolar=None,
            descritor_id=descritor_id,
            conteudo=conteudo,
            tipo_questao=tipo_questao,
            enunciado=enunciado,
            gabarito=gabarito,
            habilidade_saeb=habilidade_saeb,
            alternativa_a=alternativa_a,
            alternativa_b=alternativa_b,
            alternativa_c=alternativa_c,
            alternativa_d=alternativa_d,
            alternativa_e=alternativa_e,
            codigo_referencia=codigo,
        )
        return self.anexar_questao_banco(
            db,
            avaliacao_id=avaliacao_id,
            banco_questao_id=banco.id,
            numero=numero,
            peso=peso,
        )

    def criar_aplicacao_prova(
        self,
        db: Session,
        *,
        avaliacao_id: int,
        titulo: str | None = None,
        escopo: str = "turma",
        turma_id: int | None = None,
        escola_id: int | None = None,
        ano_letivo: str | None = None,
        periodo_referencia: str | None = None,
        data_aplicacao: datetime | None = None,
        observacoes: str | None = None,
        criado_por_usuario_id: int | None = None,
    ) -> AplicacaoProva:
        avaliacao = self.repo.get_avaliacao(db, avaliacao_id)
        if not avaliacao:
            raise ValueError("Prova não encontrada.")
        escopo_final = self._normalizar_escopo(escopo, turma_id=turma_id, escola_id=escola_id)
        aplicacao = self.repo.create_aplicacao_prova(
            db,
            avaliacao_id=avaliacao_id,
            titulo=(titulo or "").strip() or None,
            escopo=escopo_final,
            ano_letivo=(ano_letivo or "").strip() or getattr(avaliacao, "ano_letivo", None),
            periodo_referencia=(periodo_referencia or "").strip() or None,
            turma_id=turma_id,
            escola_id=escola_id,
            status=StatusAplicacaoProva.PLANEJADA,
            data_aplicacao=data_aplicacao,
            observacoes=(observacoes or "").strip() or None,
            criado_por_usuario_id=criado_por_usuario_id,
        )
        for aluno in self._alunos_para_escopo(db, escopo_final, turma_id=turma_id, escola_id=escola_id):
            escola_snapshot = self._escola_id_do_aluno(db, aluno)
            self.repo.get_or_create_participacao(
                db,
                aplicacao_id=aplicacao.id,
                aluno_id=aluno.id,
                turma_id_snapshot=aluno.turma_id,
                escola_id_snapshot=escola_snapshot,
            )
        db.commit()
        db.refresh(aplicacao)
        return aplicacao

    def alunos_elegiveis_trilha(
        self,
        db: Session,
        *,
        avaliacao_id: int,
    ) -> list[dict[str, Any]]:
        avaliacao = self.repo.get_avaliacao(db, avaliacao_id)
        if not avaliacao:
            raise ValueError("Prova não encontrada.")
        ano_alvo = avaliacao.ano_escolar
        if not ano_alvo and avaliacao.trilha_id:
            trilha = self.get_trilha(db, avaliacao.trilha_id)
            ano_alvo = trilha.ano_escolar if trilha else None
        if not ano_alvo:
            raise ValueError("Prova da trilha sem ano escolar definido.")

        rows = (
            db.query(
                Aluno.id,
                Aluno.turma_id,
                Turma.nome,
                Turma.ano_escolar,
                Turma.escola_id,
                Escola.nome,
                Usuario.nome,
            )
            .join(Usuario, Usuario.id == Aluno.usuario_id)
            .join(Turma, Turma.id == Aluno.turma_id)
            .join(Escola, Escola.id == Turma.escola_id)
            .filter(
                Aluno.turma_id.isnot(None),
                Turma.ano_escolar == int(ano_alvo),
                Usuario.ativo.is_(True),
            )
            .order_by(Usuario.nome.asc())
            .all()
        )
        return [
            {
                "aluno_id": aluno_id,
                "aluno_nome": aluno_nome or f"Aluno #{aluno_id}",
                "turma_id": turma_id,
                "turma_nome": turma_nome or "Sem turma",
                "ano_escolar": ano_escolar,
                "escola_id": escola_id,
                "escola_nome": escola_nome or "Sem escola",
            }
            for aluno_id, turma_id, turma_nome, ano_escolar, escola_id, escola_nome, aluno_nome in rows
        ]

    def importar_respostas_csv(
        self,
        db: Session,
        *,
        avaliacao_id: int | None = None,
        aplicacao_id: int | None = None,
        csv_bytes: bytes,
        arquivo_nome: str,
        criado_por_usuario_id: int | None,
    ) -> dict:
        aplicacao = self._resolver_aplicacao_importacao(db, aplicacao_id=aplicacao_id, avaliacao_id=avaliacao_id)
        if aplicacao:
            avaliacao = self.repo.get_avaliacao(db, aplicacao.avaliacao_id)
        else:
            avaliacao = self.repo.get_avaliacao(db, int(avaliacao_id or 0))
        if not avaliacao:
            raise ValueError("Prova objetiva não encontrada.")

        lote = self.repo.create_lote_importacao(
            db,
            avaliacao_id=avaliacao.id,
            aplicacao_id=aplicacao.id if aplicacao else None,
            arquivo_nome=arquivo_nome or "importacao.csv",
            criado_por_usuario_id=criado_por_usuario_id,
            linhas_processadas=0,
            linhas_com_erro=0,
            resumo_processamento="Importação iniciada.",
        )

        decoded = csv_bytes.decode("utf-8-sig")
        delimiter = ";" if decoded.splitlines() and decoded.splitlines()[0].count(";") >= decoded.splitlines()[0].count(",") else ","
        reader = csv.DictReader(io.StringIO(decoded), delimiter=delimiter)

        questoes = db.query(Questao).filter(Questao.avaliacao_id == avaliacao.id).all()
        questoes_by_id = {str(q.id): q for q in questoes}
        questoes_by_codigo = {(q.codigo or "").strip().lower(): q for q in questoes if (q.codigo or "").strip()}
        questoes_by_numero = {str(q.numero): q for q in questoes if q.numero is not None}

        processadas = 0
        erros = 0
        ignoradas = 0
        detalhes: list[str] = []
        touched_participations: set[int] = set()
        total_questoes_avaliacao = len(questoes)
        concluidas_cache: dict[int, bool] = {}

        raw_rows = list(reader)
        linhas_csv: list[tuple[int, dict[str, str]]] = []
        for idx, raw in enumerate(raw_rows, start=2):
            row = self._normalizar_row_csv(raw)
            headers = set(row.keys())
            formato_largo = any(h.startswith("questao_") for h in headers) and "resposta_marcada" not in headers
            if formato_largo:
                expanded, erros_linha = self._parse_linhas_csv_largo(
                    row=row,
                    idx=idx,
                    questoes_by_numero=questoes_by_numero,
                )
                for erro in erros_linha:
                    erros += 1
                    detalhes.append(erro)
                for exp_row in expanded:
                    linhas_csv.append((idx, exp_row))
            else:
                linhas_csv.append((idx, row))

        for idx, row in linhas_csv:
            resposta_marcada = (row.get("resposta_marcada") or row.get("resposta") or "").strip().upper()[:1]
            questao = None
            if row.get("questao_id"):
                questao = questoes_by_id.get((row.get("questao_id") or "").strip())
            if questao is None and row.get("questao_codigo"):
                questao = questoes_by_codigo.get((row.get("questao_codigo") or "").strip().lower())
            if questao is None and row.get("questao_numero"):
                questao = questoes_by_numero.get((row.get("questao_numero") or "").strip())
            if not questao or resposta_marcada not in {"A", "B", "C", "D", "E"}:
                erros += 1
                detalhes.append(f"Linha {idx}: dados insuficientes para importação.")
                continue

            aluno = self._resolver_aluno_no_csv(db, row)
            if not aluno:
                erros += 1
                detalhes.append(f"Linha {idx}: aluno não encontrado.")
                continue

            participacao = None
            if aplicacao:
                participacao = self.repo.get_or_create_participacao(
                    db,
                    aplicacao_id=aplicacao.id,
                    aluno_id=aluno.id,
                    turma_id_snapshot=aluno.turma_id,
                    escola_id_snapshot=self._escola_id_do_aluno(db, aluno),
                )
                if participacao.id not in concluidas_cache:
                    concluidas_cache[participacao.id] = self._participacao_ja_concluida(
                        db,
                        participacao_id=participacao.id,
                        aluno_id=aluno.id,
                        aplicacao_id=aplicacao.id,
                        avaliacao_id=avaliacao.id,
                        total_questoes=total_questoes_avaliacao,
                    )
                if concluidas_cache[participacao.id]:
                    ignoradas += 1
                    detalhes.append(f"Linha {idx}: aluno já concluiu a prova — resposta ignorada.")
                    continue
            correta = resposta_marcada == (questao.gabarito or "").strip().upper()
            pontuacao = float(questao.peso or 1.0) if correta else 0.0
            self.repo.upsert_resposta_importada(
                db,
                aluno_id=aluno.id,
                avaliacao_id=avaliacao.id,
                aplicacao_id=aplicacao.id if aplicacao else None,
                participacao_id=participacao.id if participacao else None,
                questao_id=questao.id,
                marcada=resposta_marcada,
                correta=correta,
                pontuacao=pontuacao,
                lote_importacao_id=lote.id,
            )
            if participacao:
                touched_participations.add(participacao.id)
            processadas += 1

        total_questoes = len(questoes)
        for participacao_id in touched_participations:
            self._recalcular_participacao(db, participacao_id=participacao_id, total_questoes=total_questoes)

        lote.linhas_processadas = processadas
        lote.linhas_com_erro = erros
        resumo_parts = []
        if processadas:
            resumo_parts.append(f"{processadas} linha(s) importada(s).")
        if ignoradas:
            resumo_parts.append(f"{ignoradas} ignorada(s) (aluno já havia concluído).")
        if detalhes:
            resumo_parts.append("\n".join(detalhes[:15]))
        lote.resumo_processamento = " ".join(resumo_parts) if resumo_parts else "Importação concluída sem inconsistências."
        if aplicacao:
            aplicacao.status = StatusAplicacaoProva.CORRIGIDA if processadas else StatusAplicacaoProva.EM_ANDAMENTO
        db.commit()

        return {
            "avaliacao_id": avaliacao.id,
            "aplicacao_id": aplicacao.id if aplicacao else None,
            "lote_id": lote.id,
            "linhas_processadas": processadas,
            "linhas_com_erro": erros,
            "linhas_ignoradas": ignoradas,
            "resumo": lote.resumo_processamento,
        }

    def _participacao_ja_concluida(
        self,
        db: Session,
        *,
        participacao_id: int,
        aluno_id: int,
        aplicacao_id: int,
        avaliacao_id: int,
        total_questoes: int,
    ) -> bool:
        if total_questoes <= 0:
            return False
        n = (
            db.query(RespostaAluno)
            .filter(
                RespostaAluno.aplicacao_id == aplicacao_id,
                RespostaAluno.avaliacao_id == avaliacao_id,
                RespostaAluno.aluno_id == aluno_id,
                or_(
                    RespostaAluno.participacao_id == participacao_id,
                    RespostaAluno.participacao_id.is_(None),
                ),
            )
            .count()
        )
        return n >= total_questoes

    def importar_respostas_ocr(
        self,
        db: Session,
        *,
        aplicacao_id: int,
        folhas: list[dict[str, Any]],
        criado_por_usuario_id: int | None,
    ) -> dict:
        """folhas: [{participacao_id, respostas: [{questao_numero, resposta_marcada}]}]"""
        aplicacao = self.repo.get_aplicacao_prova(db, aplicacao_id)
        if not aplicacao:
            raise ValueError("Aplicação não encontrada.")
        avaliacao = self.repo.get_avaliacao(db, aplicacao.avaliacao_id)
        if not avaliacao:
            raise ValueError("Prova não encontrada.")

        questoes = db.query(Questao).filter(Questao.avaliacao_id == avaliacao.id).all()
        questoes_by_numero = {int(q.numero): q for q in questoes if q.numero is not None}
        for idx, q in enumerate(sorted(questoes, key=lambda x: (x.numero or 9999, x.id)), start=1):
            questoes_by_numero.setdefault(idx, q)

        rows: list[dict[str, str]] = []
        erros: list[str] = []
        for folha in folhas:
            pid = folha.get("participacao_id")
            if not pid:
                erros.append(f"{folha.get('arquivo', 'folha')}: sem participação identificada.")
                continue
            participacao = (
                db.query(ParticipacaoAplicacaoProva)
                .filter(
                    ParticipacaoAplicacaoProva.id == int(pid),
                    ParticipacaoAplicacaoProva.aplicacao_id == aplicacao.id,
                )
                .first()
            )
            if not participacao:
                erros.append(f"Participação {pid} inválida para esta aplicação.")
                continue
            if self._participacao_ja_concluida(
                db,
                participacao_id=participacao.id,
                aluno_id=participacao.aluno_id,
                aplicacao_id=aplicacao.id,
                avaliacao_id=avaliacao.id,
                total_questoes=len(questoes),
            ):
                erros.append(
                    f"{folha.get('arquivo', 'folha')}: aluno já concluiu a prova — importação ignorada."
                )
                continue
            for resp in folha.get("respostas") or []:
                num = int(resp.get("questao_numero") or 0)
                marcada = (resp.get("resposta_marcada") or "").strip().upper()[:1]
                if marcada not in {"A", "B", "C", "D", "E"}:
                    continue
                questao = questoes_by_numero.get(num)
                if not questao:
                    continue
                rows.append(
                    {
                        "aluno_id": str(participacao.aluno_id),
                        "questao_numero": str(num),
                        "resposta_marcada": marcada,
                    }
                )

        if not rows:
            raise ValueError("Nenhuma resposta válida para importar. " + "; ".join(erros[:5]))

        import csv as csv_mod

        buf = io.StringIO()
        writer = csv_mod.DictWriter(buf, fieldnames=["aluno_id", "questao_numero", "resposta_marcada"])
        writer.writeheader()
        writer.writerows(rows)
        resultado = self.importar_respostas_csv(
            db,
            aplicacao_id=aplicacao_id,
            csv_bytes=buf.getvalue().encode("utf-8-sig"),
            arquivo_nome="ocr_importacao.csv",
            criado_por_usuario_id=criado_por_usuario_id,
        )
        if erros:
            resultado["resumo"] = (resultado.get("resumo") or "") + " Avisos OCR: " + "; ".join(erros[:10])
        return resultado

    def export_por_aluno_csv_rows(
        self,
        db: Session,
        *,
        aplicacao_id: int | None = None,
        avaliacao_id: int | None = None,
    ) -> tuple[list[str], list[list]]:
        resumo = self.resumo_avaliacao_objetiva(db, aplicacao_id=aplicacao_id, avaliacao_id=avaliacao_id)
        headers = ["aluno", "turma", "escola", "respostas", "acertos", "nota", "presente"]
        rows = [
            [
                row.get("aluno", ""),
                row.get("turma", ""),
                row.get("escola", ""),
                row.get("respostas", 0),
                row.get("acertos", 0),
                row.get("nota", 0),
                "sim" if row.get("presente") else "nao",
            ]
            for row in resumo.get("por_aluno") or []
        ]
        return headers, rows

    def resumo_avaliacao_objetiva(
        self,
        db: Session,
        avaliacao_id: int | None = None,
        aplicacao_id: int | None = None,
    ) -> dict:
        participacoes = self._participacoes_query(db, avaliacao_id=avaliacao_id, aplicacao_id=aplicacao_id).all()
        if participacoes:
            return self._resumo_participacoes(db, participacoes, aplicacao_id=aplicacao_id, avaliacao_id=avaliacao_id)
        return self._resumo_legado(db, avaliacao_id=avaliacao_id)

    def consolidado_desempenho(
        self,
        db: Session,
        *,
        escola_ids: list[int] | None = None,
        turma_ids: list[int] | None = None,
        professor_user_id: int | None = None,
        aplicacao_id: int | None = None,
    ) -> dict:
        if escola_ids is not None and not escola_ids:
            resumo = self._empty_resumo()
            resumo["mapa_migracao_legado"] = self.mapa_migracao_legado()
            resumo["fontes_externas"] = self.estrategia_fontes_externas()
            resumo["descritores_combinados"] = []
            return resumo
        turma_ids_filter = list(turma_ids or [])
        if professor_user_id and not turma_ids_filter:
            turma_ids_filter = [
                row[0]
                for row in db.query(ProfessorTurma.turma_id).filter(ProfessorTurma.professor_id == professor_user_id).all()
            ]
            if not turma_ids_filter:
                resumo = self._empty_resumo()
                resumo["mapa_migracao_legado"] = self.mapa_migracao_legado()
                resumo["fontes_externas"] = self.estrategia_fontes_externas()
                resumo["descritores_combinados"] = []
                return resumo
        elif turma_ids is not None and not turma_ids_filter:
            resumo = self._empty_resumo()
            resumo["mapa_migracao_legado"] = self.mapa_migracao_legado()
            resumo["fontes_externas"] = self.estrategia_fontes_externas()
            resumo["descritores_combinados"] = []
            return resumo
        q = self._participacoes_query(db, aplicacao_id=aplicacao_id)
        if escola_ids:
            q = q.filter(ParticipacaoAplicacaoProva.escola_id_snapshot.in_(escola_ids))
        if turma_ids_filter:
            q = q.filter(ParticipacaoAplicacaoProva.turma_id_snapshot.in_(turma_ids_filter))
        participacoes = q.all()
        resumo = self._resumo_participacoes(db, participacoes, aplicacao_id=aplicacao_id)
        aluno_ids = sorted({p.aluno_id for p in participacoes})
        from app.services.descriptor_performance_service import DescriptorPerformanceService

        resumo["descritores_combinados"] = DescriptorPerformanceService().combined_aggregates_for_alunos(
            db,
            aluno_ids,
            aplicacao_id=aplicacao_id,
        )
        resumo["mapa_migracao_legado"] = self.mapa_migracao_legado()
        resumo["fontes_externas"] = self.estrategia_fontes_externas()
        return resumo

    def resumo_institucional(
        self,
        db: Session,
        *,
        escola_id: int | None = None,
        perfil_avaliado: str | None = None,
    ) -> list[dict]:
        _ = perfil_avaliado
        consolidado = self.consolidado_desempenho(db, escola_ids=[escola_id] if escola_id else None)
        return consolidado["aplicacoes"]

    def mapa_migracao_legado(self) -> dict[str, list[dict[str, str]]]:
        return {
            "manter": [
                {"nome": "Avaliacao", "motivo": "Permanece como prova/caderno."},
                {"nome": "Questao", "motivo": "Permanece como snapshot histórico da prova aplicada."},
                {"nome": "RespostaAluno", "motivo": "Permanece como base de correção e consolidação."},
                {"nome": "LoteImportacaoGabarito", "motivo": "Permanece como trilha de auditoria da importação CSV."},
            ],
            "adaptar": [
                {"nome": "BancoQuestao", "motivo": "Novo domínio oficial para autoria e reaproveitamento."},
                {"nome": "AplicacaoProva", "motivo": "Nova camada operacional por turma, escola ou rede."},
                {"nome": "ParticipacaoAplicacaoProva", "motivo": "Registra elegibilidade, presença e nota por estudante."},
            ],
            "aposentar": [
                {"nome": "CicloAvaliacaoSemestral", "motivo": "Modelo legado de avaliação de pessoas."},
                {"nome": "InstrumentoAvaliacaoInstitucional", "motivo": "Modelo legado de formulários por perfil."},
                {"nome": "AplicacaoAvaliacaoInstitucional", "motivo": "Substituída por aplicação concreta de prova."},
            ],
        }

    def estrategia_fontes_externas(self) -> dict:
        return {
            "fonte_oficial": "Banco local do AVA MJ",
            "fontes_complementares": [
                "INEP/SAEB para matrizes e descritores",
                "API BNCC para habilidades e organização curricular",
            ],
            "politica": [
                "Não depender de API externa como fonte primária de itens.",
                "Permitir importação estruturada futura para enriquecer o banco local.",
                "Priorizar descritor local vinculado ao item e snapshot na prova.",
            ],
        }

    def _curso_nome(self, db: Session, curso_id: int | None) -> str | None:
        if not curso_id:
            return None
        curso = db.query(Curso).filter(Curso.id == curso_id).first()
        return curso.nome if curso else None

    def _curso_id_by_nome(self, db: Session, nome: str | None) -> int | None:
        if not nome:
            return None
        curso = db.query(Curso).filter(func.lower(Curso.nome) == (nome or "").strip().lower()).first()
        return curso.id if curso else None

    def _descritor_codigo(self, db: Session, descritor_id: int | None) -> str | None:
        if not descritor_id:
            return None
        descritor = db.query(Descritor).filter(Descritor.id == descritor_id).first()
        return descritor.codigo if descritor else None

    def get_trilha(self, db: Session, trilha_id: int | None) -> Trilha | None:
        if not trilha_id:
            return None
        return db.query(Trilha).filter(Trilha.id == trilha_id).first()

    def _normalizar_escopo(self, escopo: str | None, *, turma_id: int | None, escola_id: int | None) -> str:
        if turma_id:
            return "turma"
        if escola_id:
            return "escola"
        escopo_limpo = (escopo or "").strip().lower()
        return escopo_limpo if escopo_limpo in {"turma", "escola", "rede"} else "rede"

    def _alunos_para_escopo(
        self,
        db: Session,
        escopo: str,
        *,
        turma_id: int | None,
        escola_id: int | None,
    ) -> list[Aluno]:
        q = db.query(Aluno)
        if escopo == "turma" and turma_id:
            q = q.filter(Aluno.turma_id == turma_id)
        elif escopo == "escola" and escola_id:
            q = q.join(Turma, Aluno.turma_id == Turma.id).filter(Turma.escola_id == escola_id)
        elif escopo == "rede":
            q = q
        return q.order_by(Aluno.id.asc()).all()

    def _escola_id_do_aluno(self, db: Session, aluno: Aluno) -> int | None:
        if not aluno or not aluno.turma_id:
            return None
        turma = db.query(Turma).filter(Turma.id == aluno.turma_id).first()
        return turma.escola_id if turma else None

    def _resolver_aplicacao_importacao(
        self,
        db: Session,
        *,
        aplicacao_id: int | None,
        avaliacao_id: int | None,
    ) -> AplicacaoProva | None:
        if aplicacao_id:
            return self.repo.get_aplicacao_prova(db, aplicacao_id)
        if not avaliacao_id:
            return None
        apps = (
            db.query(AplicacaoProva)
            .filter(AplicacaoProva.avaliacao_id == avaliacao_id)
            .order_by(AplicacaoProva.id.desc())
            .all()
        )
        if len(apps) == 1:
            return apps[0]
        return None

    def _resolver_aluno_no_csv(self, db: Session, row: dict) -> Aluno | None:
        aluno_id_raw = (row.get("aluno_id") or row.get("id") or "").strip()
        if aluno_id_raw.isdigit():
            aluno = db.query(Aluno).filter(Aluno.id == int(aluno_id_raw)).first()
            if aluno:
                return aluno
        aluno_email = (row.get("aluno_email") or row.get("email") or "").strip().lower()
        if aluno_email:
            aluno = (
                db.query(Aluno)
                .join(Usuario, Aluno.usuario_id == Usuario.id)
                .filter(func.lower(Usuario.email) == aluno_email)
                .first()
            )
            if aluno:
                return aluno
        aluno_nome = (row.get("aluno_nome") or row.get("nome") or "").strip().lower()
        if not aluno_nome:
            return None
        return (
            db.query(Aluno)
            .join(Usuario, Aluno.usuario_id == Usuario.id)
            .filter(func.lower(Usuario.nome) == aluno_nome)
            .first()
        )

    def _recalcular_participacao(self, db: Session, *, participacao_id: int, total_questoes: int) -> None:
        respostas = (
            db.query(RespostaAluno)
            .filter(RespostaAluno.participacao_id == participacao_id)
            .all()
        )
        total_acertos = sum(1 for resposta in respostas if resposta.acertou)
        nota = round((total_acertos / total_questoes) * 10, 2) if total_questoes else 0.0
        self.repo.atualizar_participacao(
            db,
            participacao_id=participacao_id,
            total_questoes=total_questoes,
            total_acertos=total_acertos,
            nota=nota,
        )

    def _participacoes_query(
        self,
        db: Session,
        *,
        avaliacao_id: int | None = None,
        aplicacao_id: int | None = None,
    ):
        q = db.query(ParticipacaoAplicacaoProva).join(
            AplicacaoProva,
            ParticipacaoAplicacaoProva.aplicacao_id == AplicacaoProva.id,
        )
        if avaliacao_id:
            q = q.filter(AplicacaoProva.avaliacao_id == avaliacao_id)
        if aplicacao_id:
            q = q.filter(ParticipacaoAplicacaoProva.aplicacao_id == aplicacao_id)
        return q

    def _resumo_legado(self, db: Session, *, avaliacao_id: int | None = None) -> dict:
        q = (
            db.query(
                RespostaAluno,
                Usuario.nome,
                Usuario.avatar_url,
                Turma.nome,
                Escola.nome,
                Avaliacao.titulo,
            )
            .join(Aluno, RespostaAluno.aluno_id == Aluno.id)
            .join(Usuario, Aluno.usuario_id == Usuario.id)
            .outerjoin(Turma, Aluno.turma_id == Turma.id)
            .outerjoin(Escola, Turma.escola_id == Escola.id)
            .join(Avaliacao, RespostaAluno.avaliacao_id == Avaliacao.id)
        )
        if avaliacao_id:
            q = q.filter(RespostaAluno.avaliacao_id == avaliacao_id)
        rows = q.all()
        por_aluno: dict[str, dict] = {}
        por_turma: dict[str, dict] = {}
        por_escola: dict[str, dict] = {}
        for resp, nome, avatar, turma_nome, escola_nome, avaliacao_titulo in rows:
            aluno_key = nome or f"Aluno {resp.aluno_id}"
            turma_key = turma_nome or "Sem turma"
            escola_key = escola_nome or "Sem escola"
            por_aluno.setdefault(
                aluno_key,
                {
                    "aluno_id": resp.aluno_id,
                    "aluno": aluno_key,
                    "avatar_url": (avatar or "").strip(),
                    "iniciais": _iniciais_nome(aluno_key),
                    "avaliacao": avaliacao_titulo,
                    "respostas": 0,
                    "acertos": 0,
                    "turma": turma_key,
                    "escola": escola_key,
                },
            )
            por_aluno[aluno_key]["respostas"] += 1
            por_aluno[aluno_key]["acertos"] += int(bool(resp.acertou))
            por_turma.setdefault(turma_key, {"turma": turma_key, "escola": escola_key, "participantes": set(), "respostas": 0, "acertos": 0})
            por_turma[turma_key]["respostas"] += 1
            por_turma[turma_key]["acertos"] += int(bool(resp.acertou))
            por_turma[turma_key]["participantes"].add(aluno_key)
            por_escola.setdefault(escola_key, {"escola": escola_key, "respostas": 0, "acertos": 0})
            por_escola[escola_key]["respostas"] += 1
            por_escola[escola_key]["acertos"] += int(bool(resp.acertou))
        for row in por_aluno.values():
            row["nota"] = round((row["acertos"] / row["respostas"]) * 10, 2) if row["respostas"] else 0
        por_turma_rows = []
        for row in por_turma.values():
            por_turma_rows.append(
                {
                    "turma": row["turma"],
                    "escola": row["escola"],
                    "participantes": len(row["participantes"]),
                    "respostas": row["respostas"],
                    "acertos": row["acertos"],
                    "nota_media": round((row["acertos"] / row["respostas"]) * 10, 2) if row["respostas"] else 0,
                }
            )
        por_escola_rows = [
            {
                "escola": row["escola"],
                "respostas": row["respostas"],
                "acertos": row["acertos"],
                "nota_media": round((row["acertos"] / row["respostas"]) * 10, 2) if row["respostas"] else 0,
            }
            for row in por_escola.values()
        ]
        total_respostas = len(rows)
        total_acertos = sum(1 for resp, *_ in rows if resp.acertou)
        return {
            "total_respostas": total_respostas,
            "total_acertos": total_acertos,
            "nota_geral": round((total_acertos / total_respostas) * 10, 2) if total_respostas else 0,
            "participantes": len(por_aluno),
            "elegiveis": len(por_aluno),
            "participacao_pct": 100 if por_aluno else 0,
            "por_aluno": sorted(por_aluno.values(), key=lambda item: item["aluno"].lower()),
            "por_turma": sorted(por_turma_rows, key=lambda item: item["turma"].lower()),
            "por_escola": sorted(por_escola_rows, key=lambda item: item["escola"].lower()),
            "por_descritor": [],
            "aplicacoes": [],
        }

    def _resumo_participacoes(
        self,
        db: Session,
        participacoes: list[ParticipacaoAplicacaoProva],
        *,
        avaliacao_id: int | None = None,
        aplicacao_id: int | None = None,
    ) -> dict:
        if not participacoes:
            return self._empty_resumo()
        aluno_ids = [p.aluno_id for p in participacoes]
        perfil_aluno: dict[int, dict] = {}
        for aluno_id, nome, avatar in (
            db.query(Aluno.id, Usuario.nome, Usuario.avatar_url)
            .join(Usuario, Aluno.usuario_id == Usuario.id)
            .filter(Aluno.id.in_(aluno_ids))
            .all()
        ):
            label = nome or f"Aluno {aluno_id}"
            perfil_aluno[aluno_id] = {
                "nome": label,
                "avatar_url": (avatar or "").strip(),
                "iniciais": _iniciais_nome(label),
            }
        nomes = {aid: row["nome"] for aid, row in perfil_aluno.items()}
        turma_nomes = {tid: nome for tid, nome in db.query(Turma.id, Turma.nome).all()}
        escola_nomes = {eid: nome for eid, nome in db.query(Escola.id, Escola.nome).all()}
        aplicacao_ids = sorted({p.aplicacao_id for p in participacoes})
        aplicacoes_map = {
            a.id: a
            for a in db.query(AplicacaoProva).filter(AplicacaoProva.id.in_(aplicacao_ids)).all()
        }
        avaliacao_ids = sorted({a.avaliacao_id for a in aplicacoes_map.values()})
        avaliacoes_map = {
            a.id: a
            for a in db.query(Avaliacao).filter(Avaliacao.id.in_(avaliacao_ids)).all()
        }
        respostas_q = db.query(RespostaAluno, Questao).join(Questao, RespostaAluno.questao_id == Questao.id)
        if aplicacao_id:
            respostas_q = respostas_q.filter(RespostaAluno.aplicacao_id == aplicacao_id)
        elif avaliacao_id:
            respostas_q = respostas_q.filter(RespostaAluno.avaliacao_id == avaliacao_id)
        else:
            respostas_q = respostas_q.filter(RespostaAluno.participacao_id.in_([p.id for p in participacoes]))
        respostas = respostas_q.all()
        total_respostas = len(respostas)
        total_acertos = sum(1 for resposta, _ in respostas if resposta.acertou)

        respostas_por_participacao: dict[int, int] = {}
        respostas_por_aluno: dict[int, int] = {}
        for resposta, _ in respostas:
            if resposta.participacao_id:
                respostas_por_participacao[resposta.participacao_id] = (
                    respostas_por_participacao.get(resposta.participacao_id, 0) + 1
                )
            respostas_por_aluno[resposta.aluno_id] = respostas_por_aluno.get(resposta.aluno_id, 0) + 1

        total_questoes_map: dict[int, int] = {}
        for aid in avaliacao_ids:
            total_questoes_map[aid] = (
                db.query(Questao).filter(Questao.avaliacao_id == aid).count()
            )

        por_aluno: list[dict] = []
        por_turma_map: dict[tuple[str, str], dict] = {}
        por_escola_map: dict[str, dict] = {}
        por_aplicacao_map: dict[int, dict] = {}
        for p in participacoes:
            nome = nomes.get(p.aluno_id) or f"Aluno {p.aluno_id}"
            turma_nome = turma_nomes.get(p.turma_id_snapshot) or "Sem turma"
            escola_nome = escola_nomes.get(p.escola_id_snapshot) or "Sem escola"
            app = aplicacoes_map.get(p.aplicacao_id)
            prova = avaliacoes_map.get(app.avaliacao_id) if app else None
            perfil = perfil_aluno.get(p.aluno_id, {})
            n_questoes = total_questoes_map.get(app.avaliacao_id, 0) if app else 0
            n_respondidas = respostas_por_participacao.get(p.id, respostas_por_aluno.get(p.aluno_id, 0))
            if n_questoes and n_respondidas >= n_questoes:
                status_resposta = "concluida"
            elif n_respondidas > 0:
                status_resposta = "parcial"
            else:
                status_resposta = "pendente"
            por_aluno.append(
                {
                    "participacao_id": p.id,
                    "aluno_id": p.aluno_id,
                    "aluno": nome,
                    "avatar_url": perfil.get("avatar_url", ""),
                    "iniciais": perfil.get("iniciais", _iniciais_nome(nome)),
                    "turma": turma_nome,
                    "escola": escola_nome,
                    "avaliacao": prova.titulo if prova else "Prova",
                    "respostas": n_respondidas,
                    "total_questoes": n_questoes,
                    "status_resposta": status_resposta,
                    "acertos": int(p.total_acertos or 0),
                    "nota": round(float(p.nota or 0), 2),
                    "presente": bool(p.presente),
                }
            )
            turma_key = (turma_nome, escola_nome)
            por_turma_map.setdefault(
                turma_key,
                {"turma": turma_nome, "escola": escola_nome, "participantes": 0, "presentes": 0, "nota_total": 0.0},
            )
            por_turma_map[turma_key]["participantes"] += 1
            por_turma_map[turma_key]["presentes"] += int(bool(p.presente))
            por_turma_map[turma_key]["nota_total"] += float(p.nota or 0)
            por_escola_map.setdefault(
                escola_nome,
                {"escola": escola_nome, "participantes": 0, "presentes": 0, "nota_total": 0.0},
            )
            por_escola_map[escola_nome]["participantes"] += 1
            por_escola_map[escola_nome]["presentes"] += int(bool(p.presente))
            por_escola_map[escola_nome]["nota_total"] += float(p.nota or 0)
            if app:
                por_aplicacao_map.setdefault(
                    app.id,
                    {
                        "aplicacao_id": app.id,
                        "titulo_aplicacao": app.titulo or (prova.titulo if prova else "Aplicação"),
                        "prova": prova.titulo if prova else "Prova",
                        "escopo": app.escopo,
                        "turma": turma_nomes.get(app.turma_id) or "-",
                        "escola": escola_nomes.get(app.escola_id) or ("Rede" if app.escopo == "rede" else "-"),
                        "status": getattr(app.status, "value", app.status),
                        "participantes": 0,
                        "presentes": 0,
                        "nota_total": 0.0,
                    },
                )
                por_aplicacao_map[app.id]["participantes"] += 1
                por_aplicacao_map[app.id]["presentes"] += int(bool(p.presente))
                por_aplicacao_map[app.id]["nota_total"] += float(p.nota or 0)

        por_turma = []
        for row in por_turma_map.values():
            base_nota = row["presentes"] or row["participantes"]
            nota_media = round(row["nota_total"] / base_nota, 2) if base_nota else 0
            por_turma.append({**row, "nota_media": nota_media, "participacao_pct": round((row["presentes"] / row["participantes"]) * 100, 1) if row["participantes"] else 0})
        por_escola = []
        for row in por_escola_map.values():
            base_nota = row["presentes"] or row["participantes"]
            nota_media = round(row["nota_total"] / base_nota, 2) if base_nota else 0
            por_escola.append({**row, "nota_media": nota_media, "participacao_pct": round((row["presentes"] / row["participantes"]) * 100, 1) if row["participantes"] else 0})
        aplicacoes = []
        for row in por_aplicacao_map.values():
            base_nota = row["presentes"] or row["participantes"]
            nota_media = round(row["nota_total"] / base_nota, 2) if base_nota else 0
            aplicacoes.append({**row, "nota_media": nota_media, "participacao_pct": round((row["presentes"] / row["participantes"]) * 100, 1) if row["participantes"] else 0})

        descritor_map: dict[str, dict] = {}
        for resposta, questao in respostas:
            codigo = (
                (questao.habilidade_saeb or "").strip()
                or (questao.descritor.codigo if getattr(questao, "descritor", None) else "")
                or "Sem descritor"
            )
            descritor_map.setdefault(codigo, {"codigo": codigo, "respostas": 0, "acertos": 0})
            descritor_map[codigo]["respostas"] += 1
            descritor_map[codigo]["acertos"] += int(bool(resposta.acertou))
        por_descritor = [
            {
                "codigo": row["codigo"],
                "respostas": row["respostas"],
                "acertos": row["acertos"],
                "nota_media": round((row["acertos"] / row["respostas"]) * 10, 2) if row["respostas"] else 0,
            }
            for row in descritor_map.values()
        ]

        elegiveis = len(participacoes)
        presentes = sum(1 for p in participacoes if p.presente)
        base_nota_geral = presentes or elegiveis
        nota_geral = round(sum(float(p.nota or 0) for p in participacoes) / base_nota_geral, 2) if base_nota_geral else 0
        return {
            "total_respostas": total_respostas,
            "total_acertos": total_acertos,
            "nota_geral": nota_geral,
            "participantes": presentes,
            "elegiveis": elegiveis,
            "participacao_pct": round((presentes / elegiveis) * 100, 1) if elegiveis else 0,
            "por_aluno": sorted(por_aluno, key=lambda item: item["aluno"].lower()),
            "por_turma": sorted(por_turma, key=lambda item: item["turma"].lower()),
            "por_escola": sorted(por_escola, key=lambda item: item["escola"].lower()),
            "por_descritor": sorted(por_descritor, key=lambda item: item["codigo"].lower()),
            "aplicacoes": sorted(aplicacoes, key=lambda item: item["aplicacao_id"], reverse=True),
        }

    def _empty_resumo(self) -> dict:
        return {
            "total_respostas": 0,
            "total_acertos": 0,
            "nota_geral": 0,
            "participantes": 0,
            "elegiveis": 0,
            "participacao_pct": 0,
            "por_aluno": [],
            "por_turma": [],
            "por_escola": [],
            "por_descritor": [],
            "aplicacoes": [],
        }