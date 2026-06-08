"""Avaliação semestral de gestores, coordenadores e PDT."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session, joinedload

from app.models.avaliacao import (
    AplicacaoAvaliacaoInstitucional,
    CicloAvaliacaoSemestral,
    CriterioAvaliacaoInstitucional,
    InstrumentoAvaliacaoInstitucional,
    PerfilAvaliadoInstitucional,
    StatusAplicacaoInstitucional,
    StatusCicloAvaliacao,
)
from app.models.resposta import RespostaAvaliacaoInstitucional
from app.models.gestao import Escola
from app.models.user import Usuario
from app.repositories.avaliacao_repository import AvaliacaoRepository


class AvaliacaoInstitucionalService:
    def __init__(self) -> None:
        self.repo = AvaliacaoRepository()

    def listar_ciclos(self, db: Session) -> list[CicloAvaliacaoSemestral]:
        return db.query(CicloAvaliacaoSemestral).order_by(CicloAvaliacaoSemestral.id.desc()).all()

    def criar_ciclo(
        self,
        db: Session,
        *,
        titulo: str,
        ano_letivo: str,
        semestre: str,
        criado_por_usuario_id: int | None,
    ) -> CicloAvaliacaoSemestral:
        return self.repo.create_ciclo(
            db,
            titulo=titulo,
            ano_letivo=ano_letivo,
            semestre=semestre,
            status=StatusCicloAvaliacao.ATIVO,
            criado_por_usuario_id=criado_por_usuario_id,
        )

    def criar_instrumento(
        self,
        db: Session,
        *,
        nome: str,
        perfil: str,
        ciclo_id: int | None,
        descricao: str | None = None,
    ) -> InstrumentoAvaliacaoInstitucional:
        perfil_enum = PerfilAvaliadoInstitucional(perfil)
        return self.repo.create_instrumento(
            db,
            nome=nome,
            descricao=descricao,
            perfil_avaliado=perfil_enum,
            ciclo_id=ciclo_id,
        )

    def criar_criterio(
        self,
        db: Session,
        *,
        instrumento_id: int,
        titulo: str,
        peso: float = 1.0,
        descricao: str | None = None,
    ):
        return self.repo.create_criterio(
            db,
            instrumento_id=instrumento_id,
            titulo=titulo,
            descricao=descricao,
            peso=peso,
        )

    def criar_aplicacao(
        self,
        db: Session,
        *,
        ciclo_id: int,
        instrumento_id: int,
        avaliado_usuario_id: int,
        escola_id: int | None,
        respondente_usuario_id: int | None,
        observacoes: str | None = None,
    ) -> AplicacaoAvaliacaoInstitucional:
        return self.repo.create_aplicacao_institucional(
            db,
            ciclo_id=ciclo_id,
            instrumento_id=instrumento_id,
            escola_id=escola_id,
            avaliado_usuario_id=avaliado_usuario_id,
            respondente_usuario_id=respondente_usuario_id,
            observacoes=observacoes,
        )

    def salvar_respostas(
        self,
        db: Session,
        *,
        aplicacao_id: int,
        notas: list[dict[str, Any]],
        devolutiva: str | None = None,
        respondente_usuario_id: int | None = None,
    ) -> AplicacaoAvaliacaoInstitucional:
        aplicacao = (
            db.query(AplicacaoAvaliacaoInstitucional)
            .options(joinedload(AplicacaoAvaliacaoInstitucional.instrumento))
            .filter(AplicacaoAvaliacaoInstitucional.id == aplicacao_id)
            .first()
        )
        if not aplicacao:
            raise ValueError("Aplicação não encontrada.")
        criterios = (
            db.query(CriterioAvaliacaoInstitucional)
            .filter(CriterioAvaliacaoInstitucional.instrumento_id == aplicacao.instrumento_id)
            .all()
        )
        peso_map = {c.id: float(c.peso or 1.0) for c in criterios}
        respostas_payload = []
        total_peso = 0.0
        soma = 0.0
        for item in notas:
            cid = int(item["criterio_id"])
            nota = float(item.get("nota") or 0)
            respostas_payload.append(
                {"criterio_id": cid, "nota": nota, "comentario": item.get("comentario")}
            )
            peso = peso_map.get(cid, 1.0)
            total_peso += peso
            soma += nota * peso
        self.repo.replace_respostas_institucionais(db, aplicacao_id=aplicacao.id, respostas=respostas_payload)
        aplicacao.nota_final = round(soma / total_peso, 2) if total_peso else 0.0
        aplicacao.devolutiva_resumo = (devolutiva or "").strip() or None
        if respondente_usuario_id:
            aplicacao.respondente_usuario_id = respondente_usuario_id
        aplicacao.status = StatusAplicacaoInstitucional.CONCLUIDA
        db.commit()
        db.refresh(aplicacao)
        return aplicacao

    def consolidado_sme(self, db: Session) -> list[dict[str, Any]]:
        rows = (
            db.query(AplicacaoAvaliacaoInstitucional, InstrumentoAvaliacaoInstitucional, Escola, Usuario)
            .join(InstrumentoAvaliacaoInstitucional, InstrumentoAvaliacaoInstitucional.id == AplicacaoAvaliacaoInstitucional.instrumento_id)
            .outerjoin(Escola, Escola.id == AplicacaoAvaliacaoInstitucional.escola_id)
            .join(Usuario, Usuario.id == AplicacaoAvaliacaoInstitucional.avaliado_usuario_id)
            .order_by(Escola.nome, Usuario.nome)
            .all()
        )
        out: list[dict[str, Any]] = []
        for app, inst, escola, usuario in rows:
            out.append(
                {
                    "aplicacao_id": app.id,
                    "instrumento": inst.nome,
                    "perfil": getattr(inst.perfil_avaliado, "value", inst.perfil_avaliado),
                    "escola": escola.nome if escola else "—",
                    "avaliado": usuario.nome,
                    "nota_final": app.nota_final,
                    "status": getattr(app.status, "value", app.status),
                }
            )
        return out

    def export_csv_rows(self, db: Session) -> tuple[list[str], list[list]]:
        headers = ["aplicacao_id", "instrumento", "perfil", "escola", "avaliado", "nota_final", "status"]
        rows = [
            [
                r["aplicacao_id"],
                r["instrumento"],
                r["perfil"],
                r["escola"],
                r["avaliado"],
                r["nota_final"] if r["nota_final"] is not None else "",
                r["status"],
            ]
            for r in self.consolidado_sme(db)
        ]
        return headers, rows
