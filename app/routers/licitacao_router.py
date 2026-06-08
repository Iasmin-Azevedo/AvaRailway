from __future__ import annotations

import csv
import io
import zipfile
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.core.catalogs import SCHOOL_YEARS
from app.core.dependencies import require_admin_redirect, require_role_redirect
from app.models.avaliacao import (
    Avaliacao,
    AplicacaoAvaliacaoInstitucional,
    AplicacaoProva,
    BancoQuestao,
    CriterioAvaliacaoInstitucional,
    InstrumentoAvaliacaoInstitucional,
    OrigemBancoQuestao,
    PerfilAvaliadoInstitucional,
    Questao,
    StatusAplicacaoInstitucional,
)
from app.models.formacao import (
    EncontroPresencialFormacaoBNCC,
    ParticipanteTurmaFormacaoBNCC,
    PapelParticipanteFormacao,
    ProgramaFormacaoBNCC,
    TipoRecursoFormacao,
    TurmaFormacaoBNCC,
)
from app.models.gestao import Curso, Escola, Trilha, Turma
from app.models.moodle_gestao import MoodleCourseCatalog
from app.models.relacoes import CoordenadorEscola, GestorEscola, ProfessorTurma
from app.models.resposta import RespostaAvaliacaoInstitucional
from app.models.saeb import Descritor
from app.models.user import TeacherRole, UserRole, Usuario
from app.repositories.gestao_repository import CursoRepository
from app.services.audit_service import AuditService
from app.services.avaliacao_service import AvaliacaoService
from app.services.formacao_service import FormacaoService
from app.core.br_datetime import parse_data_aplicacao_form
from app.services.licitacao_service import LicitacaoService


router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _redirect_with_message(path: str, status_code: int = 303) -> RedirectResponse:
    return RedirectResponse(url=path, status_code=status_code)


def _maybe_return_redirect(current_user: Any) -> RedirectResponse | None:
    if isinstance(current_user, RedirectResponse):
        return current_user
    return None


def _curricular_context(db: Session) -> dict[str, list]:
    return {
        "cursos": CursoRepository().listar(db),
        "descritores": db.query(Descritor).order_by(Descritor.disciplina.asc(), Descritor.ano_escolar.asc(), Descritor.codigo.asc()).all(),
        "escolas": db.query(Escola).filter(Escola.ativo.is_(True)).order_by(Escola.nome.asc()).all(),
        "turmas": db.query(Turma).order_by(Turma.ano_escolar.asc(), Turma.sigla.asc(), Turma.nome.asc()).all(),
        "trilhas": db.query(Trilha).order_by(Trilha.nome.asc()).all(),
        "school_years": SCHOOL_YEARS,
    }


def _professor_turmas(db: Session, professor_id: int) -> list[Turma]:
    return (
        db.query(Turma)
        .join(ProfessorTurma, ProfessorTurma.turma_id == Turma.id)
        .filter(ProfessorTurma.professor_id == professor_id)
        .order_by(Turma.ano_escolar.asc(), Turma.sigla.asc(), Turma.nome.asc())
        .all()
    )


def _optional_int(value: Any) -> int | None:
    try:
        number = int(str(value or "").strip())
        return number or None
    except Exception:
        return None


def _professor_avaliacoes_query(db: Session, professor_id: int):
    return (
        db.query(Avaliacao)
        .options(
            joinedload(Avaliacao.aplicacoes).joinedload(AplicacaoProva.participacoes),
            joinedload(Avaliacao.questoes),
            joinedload(Avaliacao.trilha),
            joinedload(Avaliacao.curso),
        )
        .filter(Avaliacao.criado_por_usuario_id == professor_id)
        .order_by(Avaliacao.id.desc())
    )


def _respostas_count_aplicacao(aplicacao: AplicacaoProva) -> int:
    participacoes = getattr(aplicacao, "participacoes", None) or []
    return sum(
        1
        for p in participacoes
        if bool(p.presente) or int(p.total_questoes or 0) > 0
    )


def _prova_tem_resultados(prova: Avaliacao) -> bool:
    for aplicacao in getattr(prova, "aplicacoes", None) or []:
        if _respostas_count_aplicacao(aplicacao) > 0:
            return True
    return False


def _professor_trilhas(db: Session, professor_id: int) -> list[Trilha]:
    anos = sorted({turma.ano_escolar for turma in _professor_turmas(db, professor_id) if turma.ano_escolar})
    query = db.query(Trilha)
    if anos:
        query = query.filter(or_(Trilha.ano_escolar.is_(None), Trilha.ano_escolar.in_(anos)))
    return query.order_by(Trilha.ordem.asc(), Trilha.id.asc()).all()


def _professor_get_avaliacao(db: Session, professor_id: int, avaliacao_id: int | None) -> Avaliacao | None:
    if not avaliacao_id:
        return None
    return (
        db.query(Avaliacao)
        .filter(Avaliacao.id == avaliacao_id, Avaliacao.criado_por_usuario_id == professor_id)
        .first()
    )


@router.get("/admin/avaliacoes-institucionais")
def admin_avaliacoes_institucionais(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    service = AvaliacaoService()
    selected_aplicacao_raw = (request.query_params.get("aplicacao_id") or "").strip()
    selected_aplicacao_id = int(selected_aplicacao_raw) if selected_aplicacao_raw.isdigit() else None
    consolidado = service.consolidado_desempenho(db, aplicacao_id=selected_aplicacao_id)
    return templates.TemplateResponse(
        request,
        "admin/avaliacoes_institucionais.html",
        {
            "request": request,
            "current_user": current_user,
            "consolidado": consolidado,
            "aplicacoes": consolidado["aplicacoes"],
            "selected_aplicacao_id": selected_aplicacao_id,
            "flash_ok": (request.query_params.get("ok") or "").strip(),
            "flash_err": (request.query_params.get("err") or "").strip(),
        },
    )


@router.get("/admin/avaliacoes-institucionais/export.csv")
def admin_avaliacoes_institucionais_export_csv(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    _ = current_user
    consolidado = AvaliacaoService().consolidado_desempenho(db)
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(["turma", "escola", "participacao_pct", "nota_media"])
    for row in consolidado.get("por_turma") or []:
        writer.writerow(
            [
                row.get("turma", ""),
                row.get("escola", ""),
                row.get("participacao_pct", 0),
                row.get("nota_media", 0),
            ]
        )
    data = "\ufeff" + output.getvalue()
    return StreamingResponse(
        iter([data]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="avaliacoes_institucionais_admin.csv"'},
    )


@router.get("/admin/avaliacoes-institucionais/imprimir")
def admin_avaliacoes_institucionais_imprimir(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    consolidado = AvaliacaoService().consolidado_desempenho(db)
    rows = [
        [
            row.get("turma", ""),
            row.get("escola", ""),
            f"{row.get('participacao_pct', 0)}%",
            row.get("nota_media", 0),
        ]
        for row in (consolidado.get("por_turma") or [])
    ]
    return templates.TemplateResponse(
        request,
        "shared/relatorio_imprimir.html",
        {
            "request": request,
            "report_title": "Avaliação institucional por desempenho",
            "report_subtitle": "Consolidado por turma e escola da rede",
            "column_labels": ["Turma", "Escola", "Participação", "Nota média"],
            "rows": rows,
            "generated_at": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "back_href": "/admin/avaliacoes-institucionais",
            "report_author_label": "Secretaria",
            "report_author_name": (current_user.nome or "").strip(),
            "report_kicker": "Mj Connect Edu — Avaliação institucional",
        },
    )


@router.get("/admin/gestao-integrada")
def admin_gestao_integrada(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    licitacao_service = LicitacaoService()
    avaliacao_service = AvaliacaoService()
    consolidado = avaliacao_service.consolidado_desempenho(db)
    return templates.TemplateResponse(
        request,
        "admin/gestao_integrada.html",
        {
            "request": request,
            "current_user": current_user,
            "sme_stats": licitacao_service.get_sme_dashboard(db),
            "resumo_institucional": consolidado["aplicacoes"][:5],
            "resumo_objetivo": avaliacao_service.resumo_avaliacao_objetiva(db),
            "mapa_legado": consolidado["mapa_migracao_legado"],
            "fontes_externas": consolidado["fontes_externas"],
            "programas_formacao": db.query(ProgramaFormacaoBNCC).order_by(ProgramaFormacaoBNCC.id.desc()).limit(5).all(),
            "avaliacoes_objetivas": (
                db.query(Avaliacao)
                .filter(or_(Avaliacao.tipo.is_(None), Avaliacao.tipo == "objetiva"))
                .order_by(Avaliacao.id.desc())
                .limit(5)
                .all()
            ),
        },
    )


@router.get("/admin/correcao-gabaritos")
def admin_correcao_gabaritos(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    service = AvaliacaoService()
    selected_raw = (request.query_params.get("avaliacao_id") or "").strip()
    selected_aplicacao_raw = (request.query_params.get("aplicacao_id") or "").strip()
    avaliacoes = (
        db.query(Avaliacao)
        .filter(or_(Avaliacao.tipo.is_(None), Avaliacao.tipo == "objetiva"))
        .order_by(Avaliacao.id.desc())
        .all()
    )
    selected_aplicacao = None
    if selected_aplicacao_raw.isdigit():
        selected_aplicacao = (
            db.query(AplicacaoProva)
            .options(joinedload(AplicacaoProva.avaliacao))
            .filter(AplicacaoProva.id == int(selected_aplicacao_raw))
            .first()
        )

    selected = None
    if selected_raw.isdigit():
        selected = db.query(Avaliacao).filter(Avaliacao.id == int(selected_raw)).first()
    elif selected_aplicacao and selected_aplicacao.avaliacao_id:
        selected = selected_aplicacao.avaliacao

    if selected is None and avaliacoes:
        selected = avaliacoes[0]

    aplicacoes = (
        db.query(AplicacaoProva)
        .filter(AplicacaoProva.avaliacao_id == selected.id)
        .order_by(AplicacaoProva.id.desc())
        .all()
        if selected
        else []
    )
    if selected_aplicacao and selected and selected_aplicacao.avaliacao_id != selected.id:
        selected_aplicacao = None
    if selected_aplicacao is None and aplicacoes and not (selected and selected.trilha_id):
        selected_aplicacao = aplicacoes[0]
    resumo = service.resumo_avaliacao_objetiva(
        db,
        avaliacao_id=selected.id if selected else None,
        aplicacao_id=selected_aplicacao.id if selected_aplicacao else None,
    )
    trilha_elegiveis = []
    if selected and not selected_aplicacao and selected.trilha_id:
        try:
            trilha_elegiveis = service.alunos_elegiveis_trilha(db, avaliacao_id=selected.id)
        except ValueError:
            trilha_elegiveis = []
        if trilha_elegiveis:
            respostas_por_aluno = {
                int((row.get("aluno_id") or 0)): row for row in (resumo.get("por_aluno") or [])
            }
            resumo["elegiveis"] = len(trilha_elegiveis)
            resumo["participantes"] = 0
            resumo["por_aluno"] = []
            for item in trilha_elegiveis:
                row = respostas_por_aluno.get(int(item["aluno_id"]), {})
                respostas = int(row.get("respostas") or 0)
                status = "pendente"
                total_q = row.get("total_questoes")
                if respostas > 0 and total_q and respostas >= int(total_q):
                    status = "concluida"
                elif respostas > 0:
                    status = "parcial"
                if status != "pendente":
                    resumo["participantes"] += 1
                resumo["por_aluno"].append(
                    {
                        "aluno_id": item["aluno_id"],
                        "aluno": item["aluno_nome"],
                        "turma": item["turma_nome"],
                        "escola": item["escola_nome"],
                        "respostas": respostas,
                        "total_questoes": row.get("total_questoes"),
                        "status_resposta": status,
                        "nota": row.get("nota", 0),
                        "acertos": row.get("acertos", 0),
                    }
                )
            resumo["participacao_pct"] = (
                round((resumo["participantes"] / resumo["elegiveis"]) * 100, 1) if resumo["elegiveis"] else 0
            )
    questoes = (
        db.query(Questao)
        .filter(Questao.avaliacao_id == selected.id)
        .order_by(Questao.numero.asc(), Questao.id.asc())
        .all()
        if selected
        else []
    )
    banco_questoes = service.listar_banco_questoes(db)
    context = _curricular_context(db)
    return templates.TemplateResponse(
        request,
        "admin/correcao_gabaritos.html",
        {
            "request": request,
            "current_user": current_user,
            "avaliacoes": avaliacoes,
            "selected_avaliacao": selected,
            "aplicacoes": aplicacoes,
            "selected_aplicacao": selected_aplicacao,
            "questoes": questoes,
            "banco_questoes": banco_questoes[:30],
            "resumo": resumo,
            "trilha_elegiveis": trilha_elegiveis,
            **context,
            "flash_ok": (request.query_params.get("ok") or "").strip(),
            "flash_err": (request.query_params.get("err") or "").strip(),
        },
    )


@router.post("/admin/correcao-gabaritos/avaliacoes")
async def admin_correcao_gabaritos_avaliacoes(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    form = await request.form()
    titulo = (form.get("titulo") or "").strip()
    if not titulo:
        return _redirect_with_message("/admin/correcao-gabaritos?err=Informe%20o%20t%C3%ADtulo%20da%20avalia%C3%A7%C3%A3o.")
    try:
        avaliacao = AvaliacaoService().criar_avaliacao_objetiva(
            db,
            titulo=titulo,
            descricao=(form.get("descricao") or "").strip(),
            codigo=(form.get("codigo") or "").strip() or None,
            ano_letivo=(form.get("ano_letivo") or "").strip() or None,
            curso_id=_optional_int(form.get("curso_id")),
            trilha_id=_optional_int(form.get("trilha_id")),
            ano_escolar=_optional_int(form.get("ano_escolar")),
            criado_por_usuario_id=current_user.id if current_user else None,
            escopo=(form.get("escopo") or "").strip() or "rede",
        )
    except ValueError as exc:
        return _redirect_with_message(f"/admin/correcao-gabaritos?err={str(exc).replace(' ', '%20')}")
    AuditService.log(
        db,
        usuario_id=current_user.id if current_user else None,
        acao="avaliacao_objetiva_criada",
        categoria="licitacao",
        entidade="avaliacao_objetiva",
        entidade_id=avaliacao.id,
        detalhes=f"Avaliação objetiva criada: {avaliacao.titulo}",
        ip=request.client.host if request.client else None,
    )
    return _redirect_with_message(f"/admin/correcao-gabaritos?ok=avaliacao&avaliacao_id={avaliacao.id}")


@router.post("/admin/correcao-gabaritos/banco-questoes")
async def admin_correcao_gabaritos_banco_questoes(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    form = await request.form()
    enunciado = (form.get("enunciado") or "").strip()
    if not enunciado:
        return _redirect_with_message("/admin/correcao-gabaritos?err=Informe%20o%20enunciado%20da%20quest%C3%A3o.")
    origem_raw = (form.get("origem") or OrigemBancoQuestao.MANUAL.value).strip()
    try:
        origem = OrigemBancoQuestao(origem_raw)
    except ValueError:
        origem = OrigemBancoQuestao.MANUAL
    questao = AvaliacaoService().criar_banco_questao(
        db,
        autor_usuario_id=current_user.id if current_user else None,
        curso_id=_optional_int(form.get("curso_id")),
        ano_escolar=_optional_int(form.get("ano_escolar")),
        descritor_id=_optional_int(form.get("descritor_id")),
        conteudo=(form.get("conteudo") or "").strip() or None,
        tipo_questao=(form.get("tipo_questao") or "").strip() or "multipla_escolha",
        enunciado=enunciado,
        gabarito=(form.get("gabarito") or "").strip(),
        origem=origem,
        alternativa_a=(form.get("alternativa_a") or "").strip(),
        alternativa_b=(form.get("alternativa_b") or "").strip(),
        alternativa_c=(form.get("alternativa_c") or "").strip(),
        alternativa_d=(form.get("alternativa_d") or "").strip(),
        alternativa_e=(form.get("alternativa_e") or "").strip(),
        codigo_referencia=(form.get("codigo_referencia") or "").strip() or None,
        observacoes=(form.get("observacoes") or "").strip() or None,
    )
    AuditService.log(
        db,
        usuario_id=current_user.id if current_user else None,
        acao="questao_banco_criada",
        categoria="licitacao",
        entidade="banco_questoes",
        entidade_id=questao.id,
        detalhes=f"Questão adicionada ao banco autoral: {questao.id}",
        ip=request.client.host if request.client else None,
    )
    return _redirect_with_message("/admin/correcao-gabaritos?ok=banco")


@router.post("/admin/correcao-gabaritos/questoes")
async def admin_correcao_gabaritos_questoes(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    form = await request.form()
    try:
        avaliacao_id = int(form.get("avaliacao_id") or 0)
        banco_questao_id = int(form.get("banco_questao_id") or 0)
    except Exception:
        return _redirect_with_message("/admin/correcao-gabaritos?err=Selecione%20a%20prova%20e%20a%20quest%C3%A3o%20do%20banco.")
    questao = AvaliacaoService().anexar_questao_banco(
        db,
        avaliacao_id=avaliacao_id,
        banco_questao_id=banco_questao_id,
        numero=int(form.get("numero") or 0) or None,
        peso=float(form.get("peso") or 1.0),
    )
    AuditService.log(
        db,
        usuario_id=current_user.id if current_user else None,
        acao="questao_anexada",
        categoria="licitacao",
        entidade="questao_prova",
        entidade_id=questao.id,
        detalhes=f"Questão do banco anexada à prova {avaliacao_id}",
        ip=request.client.host if request.client else None,
    )
    return _redirect_with_message(f"/admin/correcao-gabaritos?ok=questao&avaliacao_id={avaliacao_id}")


@router.post("/admin/correcao-gabaritos/aplicacoes")
async def admin_correcao_gabaritos_aplicacoes(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    form = await request.form()
    try:
        avaliacao_id = int(form.get("avaliacao_id") or 0)
    except Exception:
        return _redirect_with_message("/admin/correcao-gabaritos?err=Selecione%20uma%20prova.")
    turma_id = int(form.get("turma_id") or 0) or None
    escola_id = int(form.get("escola_id") or 0) or None
    data_aplicacao = parse_data_aplicacao_form(form.get("data_aplicacao"))
    aplicacao = AvaliacaoService().criar_aplicacao_prova(
        db,
        avaliacao_id=avaliacao_id,
        titulo=(form.get("titulo") or "").strip() or None,
        escopo=(form.get("escopo") or "").strip() or "turma",
        turma_id=turma_id,
        escola_id=escola_id,
        ano_letivo=(form.get("ano_letivo") or "").strip() or None,
        periodo_referencia=(form.get("periodo_referencia") or "").strip() or None,
        data_aplicacao=data_aplicacao,
        observacoes=(form.get("observacoes") or "").strip() or None,
        criado_por_usuario_id=current_user.id if current_user else None,
    )
    AuditService.log(
        db,
        usuario_id=current_user.id if current_user else None,
        acao="aplicacao_prova_criada",
        categoria="licitacao",
        entidade="aplicacoes_prova",
        entidade_id=aplicacao.id,
        detalhes=f"Aplicação de prova criada para escopo {aplicacao.escopo}",
        ip=request.client.host if request.client else None,
    )
    return _redirect_with_message(
        f"/admin/correcao-gabaritos?ok=aplicacao&avaliacao_id={avaliacao_id}&aplicacao_id={aplicacao.id}"
    )


@router.post("/admin/correcao-gabaritos/importar")
async def admin_correcao_gabaritos_importar(
    request: Request,
    arquivo_csv: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    redirect = _maybe_return_redirect(current_user)
    if redirect:
        return redirect
    aplicacao_id = _optional_int(request.query_params.get("aplicacao_id"))
    avaliacao_id = _optional_int(request.query_params.get("avaliacao_id"))
    body = await arquivo_csv.read()
    try:
        resultado = AvaliacaoService().importar_respostas_csv(
            db,
            avaliacao_id=avaliacao_id,
            aplicacao_id=aplicacao_id,
            csv_bytes=body,
            arquivo_nome=arquivo_csv.filename or "importacao.csv",
            criado_por_usuario_id=current_user.id if current_user else None,
        )
    except ValueError as exc:
        qs = f"avaliacao_id={avaliacao_id or ''}&aplicacao_id={aplicacao_id or ''}"
        return _redirect_with_message(f"/admin/correcao-gabaritos?err={str(exc).replace(' ', '%20')}&{qs}")
    AuditService.log(
        db,
        usuario_id=current_user.id if current_user else None,
        acao="gabarito_importado",
        categoria="licitacao",
        entidade="lote_importacao_gabarito",
        entidade_id=resultado["lote_id"],
        detalhes=f"Importação de gabarito com {resultado['linhas_processadas']} linhas válidas e {resultado['linhas_com_erro']} inconsistências.",
        ip=request.client.host if request.client else None,
    )
    return _redirect_with_message(f"/admin/correcao-gabaritos?ok=importacao&avaliacao_id={resultado['avaliacao_id']}&aplicacao_id={resultado.get('aplicacao_id') or ''}")


@router.get("/admin/correcao-gabaritos/modelo.csv")
def admin_correcao_gabaritos_modelo_csv(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    redirect = _maybe_return_redirect(current_user)
    if redirect:
        return redirect
    _ = current_user
    aplicacao_id = _optional_int(request.query_params.get("aplicacao_id"))
    if aplicacao_id:
        try:
            content, filename = AvaliacaoService().gerar_modelo_importacao_aplicacao_csv(
                db,
                aplicacao_id=aplicacao_id,
            )
        except ValueError as exc:
            return _redirect_with_message(f"/admin/correcao-gabaritos?err={str(exc).replace(' ', '%20')}")
    else:
        content = "ID;NOME;QUESTAO 1;QUESTAO 2\n1;Aluno Exemplo;A;B\n"
        filename = "modelo_importacao_gabarito.csv"
    return StreamingResponse(
        io.BytesIO(content.encode("utf-8-sig")),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/admin/correcao-gabaritos/export.csv")
def admin_correcao_gabaritos_export_csv(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    redirect = _maybe_return_redirect(current_user)
    if redirect:
        return redirect
    aplicacao_id = _optional_int(request.query_params.get("aplicacao_id"))
    avaliacao_id = _optional_int(request.query_params.get("avaliacao_id"))
    if not aplicacao_id and not avaliacao_id:
        return _redirect_with_message("/admin/correcao-gabaritos?err=Selecione%20uma%20aplica%C3%A7%C3%A3o.")
    headers, rows = AvaliacaoService().export_por_aluno_csv_rows(
        db, aplicacao_id=aplicacao_id, avaliacao_id=avaliacao_id
    )
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(headers)
    writer.writerows(rows)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=notas_por_aluno.csv"},
    )


@router.get("/admin/correcao-gabaritos/folhas.pdf")
def admin_correcao_gabaritos_folhas_pdf(
    request: Request,
    aplicacao_id: int | None = None,
    avaliacao_id: int | None = None,
    formato: str = "pdf",
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    redirect = _maybe_return_redirect(current_user)
    if redirect:
        return redirect
    from app.services.gabarito_sheet_service import GabaritoSheetService

    svc = GabaritoSheetService()
    try:
        if aplicacao_id:
            if (formato or "pdf").lower() == "zip":
                file_bytes, filename = svc.gerar_zip_aplicacao(db, aplicacao_id=aplicacao_id)
                media_type = "application/zip"
            else:
                file_bytes, filename = svc.gerar_pdf_aplicacao_completo(db, aplicacao_id=aplicacao_id)
                media_type = "application/pdf"
        else:
            if not avaliacao_id:
                return _redirect_with_message(
                    "/admin/correcao-gabaritos?err=Selecione%20prova%20ou%20aplica%C3%A7%C3%A3o."
                )
            elegiveis = AvaliacaoService().alunos_elegiveis_trilha(db, avaliacao_id=avaliacao_id)
            if (formato or "pdf").lower() == "zip":
                file_bytes, filename = svc.gerar_zip_avaliacao_trilha(
                    db,
                    avaliacao_id=avaliacao_id,
                    elegiveis=elegiveis,
                )
                media_type = "application/zip"
            else:
                file_bytes, filename = svc.gerar_pdf_avaliacao_trilha_completo(
                    db,
                    avaliacao_id=avaliacao_id,
                    elegiveis=elegiveis,
                )
                media_type = "application/pdf"
    except ValueError as exc:
        qs = f"aplicacao_id={aplicacao_id or ''}&avaliacao_id={avaliacao_id or ''}"
        return _redirect_with_message(
            f"/admin/correcao-gabaritos?err={str(exc).replace(' ', '%20')}&{qs}"
        )
    return StreamingResponse(
        io.BytesIO(file_bytes),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/admin/correcao-gabaritos/ocr-preview")
async def admin_correcao_gabaritos_ocr_preview(
    request: Request,
    aplicacao_id: int | None = None,
    avaliacao_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    redirect = _maybe_return_redirect(current_user)
    if redirect:
        return redirect
    from app.services.gabarito_ocr_service import GabaritoOcrService

    form = await request.form()
    files = form.getlist("folhas_imagem")
    zip_upload = form.get("arquivo_zip")
    pdf_upload = form.get("arquivo_pdf")
    modo_trilha = not aplicacao_id
    aplicacao = None
    if aplicacao_id:
        aplicacao = db.query(AplicacaoProva).filter(AplicacaoProva.id == aplicacao_id).first()
        if not aplicacao:
            return _redirect_with_message("/admin/correcao-gabaritos?err=Aplica%C3%A7%C3%A3o%20n%C3%A3o%20encontrada.")
        avaliacao_id = aplicacao.avaliacao_id
    if not avaliacao_id:
        return _redirect_with_message("/admin/correcao-gabaritos?err=Selecione%20uma%20prova.")
    n_questoes = db.query(func.count(Questao.id)).filter(Questao.avaliacao_id == avaliacao_id).scalar() or 0
    batch: list[tuple[str, bytes]] = []
    allowed_ext = (".jpg", ".jpeg", ".png", ".webp")
    for f in files:
        if hasattr(f, "read"):
            data = await f.read()
            if data:
                nome = (getattr(f, "filename", None) or "folha.jpg").strip()
                if nome.lower().endswith(allowed_ext):
                    batch.append((nome, data))
    if hasattr(zip_upload, "read"):
        zip_data = await zip_upload.read()
        if zip_data:
            try:
                with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
                    for info in zf.infolist():
                        if info.is_dir():
                            continue
                        nome = (info.filename or "").strip()
                        if not nome.lower().endswith(allowed_ext):
                            continue
                        try:
                            data = zf.read(info)
                        except Exception:
                            continue
                        if data:
                            batch.append((nome.split("/")[-1] or "folha.jpg", data))
            except zipfile.BadZipFile:
                qs = f"aplicacao_id={aplicacao_id or ''}&avaliacao_id={avaliacao_id or ''}"
                return _redirect_with_message(
                    f"/admin/correcao-gabaritos?err=Arquivo%20ZIP%20inv%C3%A1lido.&{qs}"
                )
    if hasattr(pdf_upload, "read"):
        pdf_data = await pdf_upload.read()
        if pdf_data:
            try:
                import pypdfium2 as pdfium
                from PIL import ImageOps
            except Exception:
                qs = f"aplicacao_id={aplicacao_id or ''}&avaliacao_id={avaliacao_id or ''}"
                return _redirect_with_message(
                    f"/admin/correcao-gabaritos?err=Leitor%20de%20PDF%20indispon%C3%ADvel%20no%20servidor%20(pypdfium2).&{qs}"
                )
            try:
                def _crop_margens_brancas(img):
                    gray = ImageOps.grayscale(img)
                    # Realça conteúdo escuro e encontra bounding box.
                    mask = gray.point(lambda p: 255 if p < 245 else 0)
                    bbox = mask.getbbox()
                    if not bbox:
                        return img
                    x0, y0, x1, y1 = bbox
                    pad = 18
                    x0 = max(0, x0 - pad)
                    y0 = max(0, y0 - pad)
                    x1 = min(img.width, x1 + pad)
                    y1 = min(img.height, y1 + pad)
                    return img.crop((x0, y0, x1, y1))

                # Alguns PDFs vindos de scanner/celular têm bytes extras antes do %PDF.
                # Tentamos localizar o header em vez de rejeitar direto.
                header_pos = pdf_data.find(b"%PDF-")
                pdf_bytes = pdf_data[header_pos:] if header_pos > 0 else pdf_data
                pages_extraidas = 0
                pdf = pdfium.PdfDocument(pdf_bytes)
                for idx, page in enumerate(pdf):
                    pil_img = page.render(scale=3.0).to_pil().convert("RGB")
                    if pil_img.width > int(pil_img.height * 1.1):
                        pil_img = pil_img.rotate(90, expand=True)
                    pil_img = _crop_margens_brancas(pil_img)
                    out = io.BytesIO()
                    pil_img.save(out, format="JPEG", quality=92)
                    batch.append((f"pdf_pagina_{idx + 1}.jpg", out.getvalue()))
                    pages_extraidas += 1
                if pages_extraidas == 0:
                    raise ValueError("PDF sem páginas renderizáveis")
            except Exception:
                # Fallback: alguns arquivos chegam com extensão .pdf mas são imagem única.
                try:
                    from PIL import Image

                    img_single = Image.open(io.BytesIO(pdf_data)).convert("RGB")
                    out = io.BytesIO()
                    img_single.save(out, format="JPEG", quality=92)
                    batch.append(("pdf_fallback_imagem.jpg", out.getvalue()))
                except Exception:
                    qs = f"aplicacao_id={aplicacao_id or ''}&avaliacao_id={avaliacao_id or ''}"
                    return _redirect_with_message(
                        f"/admin/correcao-gabaritos?err=Arquivo%20PDF%20inv%C3%A1lido%20ou%20corrompido.%20Exporte%20novamente%20em%20PDF%20padr%C3%A3o.&{qs}"
                    )
    if not batch:
        qs = f"aplicacao_id={aplicacao_id or ''}&avaliacao_id={avaliacao_id or ''}"
        return _redirect_with_message(
            f"/admin/correcao-gabaritos?err=Envie%20imagens%20JPG/PNG%2C%20um%20ZIP%20ou%20um%20PDF%20com%20as%20folhas.&{qs}"
        )
    ocr = GabaritoOcrService()
    preview = ocr.processar_multiplas(batch, n_questoes=int(n_questoes))
    import json as json_mod

    from app.models.aluno import Aluno
    from app.models.avaliacao import ParticipacaoAplicacaoProva
    from app.models.user import Usuario

    alunos_lookup = {}
    if modo_trilha:
        elegiveis = AvaliacaoService().alunos_elegiveis_trilha(db, avaliacao_id=avaliacao_id)
        alunos_lookup = {int(item["aluno_id"]): item for item in elegiveis}

    for row in preview:
        pid = row.get("participacao_id")
        if modo_trilha:
            aluno_id = int(row.get("aluno_id") or 0) or None
            if not aluno_id:
                continue
            aluno_item = alunos_lookup.get(aluno_id)
            if not aluno_item:
                row["ok"] = False
                row["erro"] = "Aluno fora da elegibilidade da trilha."
                continue
            row["aluno_nome"] = aluno_item["aluno_nome"]
            row["turma_nome"] = aluno_item["turma_nome"]
            continue
        if not pid:
            continue
        participacao = (
            db.query(ParticipacaoAplicacaoProva)
            .filter(
                ParticipacaoAplicacaoProva.id == int(pid),
                ParticipacaoAplicacaoProva.aplicacao_id == aplicacao_id,
            )
            .first()
        )
        if not participacao:
            continue
        nome = (
            db.query(Usuario.nome)
            .join(Aluno, Aluno.usuario_id == Usuario.id)
            .filter(Aluno.id == participacao.aluno_id)
            .scalar()
        )
        row["aluno_nome"] = nome or f"Aluno #{participacao.aluno_id}"

    preview_json = json_mod.dumps(preview, ensure_ascii=False)
    return templates.TemplateResponse(
        request,
        "admin/correcao_gabaritos_ocr_preview.html",
        {
            "request": request,
            "current_user": current_user,
            "aplicacao_id": aplicacao_id,
            "avaliacao_id": avaliacao_id,
            "modo_trilha": modo_trilha,
            "preview": preview,
            "preview_json": preview_json,
        },
    )


@router.post("/admin/correcao-gabaritos/ocr-importar")
async def admin_correcao_gabaritos_ocr_importar(
    request: Request,
    aplicacao_id: int | None = None,
    avaliacao_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    redirect = _maybe_return_redirect(current_user)
    if redirect:
        return redirect
    form = await request.form()
    import json as json_mod

    raw = (form.get("preview_json") or "").strip()
    try:
        folhas = json_mod.loads(raw) if raw else []
    except json_mod.JSONDecodeError:
        qs = f"aplicacao_id={aplicacao_id or ''}&avaliacao_id={avaliacao_id or ''}"
        return _redirect_with_message(
            f"/admin/correcao-gabaritos?err=Preview%20inv%C3%A1lido.%20Refa%C3%A7a%20a%20leitura%20OCR.&{qs}"
        )
    modo_trilha = not aplicacao_id
    if modo_trilha and not avaliacao_id:
        return _redirect_with_message("/admin/correcao-gabaritos?err=Selecione%20uma%20prova.")
    for idx, folha in enumerate(folhas):
        if modo_trilha:
            if folha.get("aluno_id"):
                continue
            manual_aluno = (form.get(f"aluno_manual_{idx}") or "").strip()
            if manual_aluno.isdigit():
                folha["aluno_id"] = int(manual_aluno)
                folha["ok"] = True
                folha.pop("erro", None)
        elif folha.get("participacao_id"):
            continue
        else:
            manual = (form.get(f"participacao_manual_{idx}") or "").strip()
            if manual.isdigit():
                folha["participacao_id"] = int(manual)
                folha["ok"] = True
                folha.pop("erro", None)
        for r in folha.get("respostas") or []:
            qn = r.get("questao_numero")
            if qn is None:
                continue
            override = (form.get(f"resposta_{idx}_{qn}") or "").strip().upper()
            if override in {"A", "B", "C", "D", "E"}:
                r["resposta_marcada"] = override

    folhas_import: list[dict] = []
    linhas_trilha: list[dict[str, str]] = []
    for folha in folhas:
        ref_id = folha.get("aluno_id") if modo_trilha else folha.get("participacao_id")
        if not ref_id:
            continue
        respostas = [
            r
            for r in (folha.get("respostas") or [])
            if (r.get("resposta_marcada") or "").strip().upper() in {"A", "B", "C", "D", "E"}
        ]
        if not respostas:
            continue
        if modo_trilha:
            for r in respostas:
                linhas_trilha.append(
                    {
                        "aluno_id": str(int(ref_id)),
                        "questao_numero": str(int(r.get("questao_numero") or 0)),
                        "resposta_marcada": (r.get("resposta_marcada") or "").strip().upper()[:1],
                    }
                )
            continue
        folhas_import.append(
            {
                "participacao_id": int(ref_id),
                "arquivo": folha.get("arquivo"),
                "respostas": respostas,
            }
        )
    if modo_trilha and not linhas_trilha:
        qs = f"aplicacao_id={aplicacao_id or ''}&avaliacao_id={avaliacao_id or ''}"
        return _redirect_with_message(
            f"/admin/correcao-gabaritos?err=Nenhuma%20resposta%20v%C3%A1lida%20para%20importar.&{qs}"
        )
    if not modo_trilha and not folhas_import:
        qs = f"aplicacao_id={aplicacao_id or ''}&avaliacao_id={avaliacao_id or ''}"
        return _redirect_with_message(
            f"/admin/correcao-gabaritos?err=Nenhuma%20resposta%20v%C3%A1lida%20para%20importar.&{qs}"
        )
    try:
        if modo_trilha:
            import csv as csv_mod

            buf = io.StringIO()
            writer = csv_mod.DictWriter(buf, fieldnames=["aluno_id", "questao_numero", "resposta_marcada"])
            writer.writeheader()
            writer.writerows(linhas_trilha)
            resultado = AvaliacaoService().importar_respostas_csv(
                db,
                avaliacao_id=avaliacao_id,
                csv_bytes=buf.getvalue().encode("utf-8-sig"),
                arquivo_nome="ocr_trilha_importacao.csv",
                criado_por_usuario_id=current_user.id if current_user else None,
            )
        else:
            resultado = AvaliacaoService().importar_respostas_ocr(
                db,
                aplicacao_id=aplicacao_id,
                folhas=folhas_import,
                criado_por_usuario_id=current_user.id if current_user else None,
            )
    except ValueError as exc:
        qs = f"aplicacao_id={aplicacao_id or ''}&avaliacao_id={avaliacao_id or ''}"
        return _redirect_with_message(
            f"/admin/correcao-gabaritos?err={str(exc).replace(' ', '%20')}&{qs}"
        )
    return _redirect_with_message(
        f"/admin/correcao-gabaritos?ok=importacao&avaliacao_id={resultado['avaliacao_id']}&aplicacao_id={resultado.get('aplicacao_id') or ''}"
    )


@router.get("/admin/correcao-gabaritos/imprimir")
def admin_correcao_gabaritos_imprimir(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    aplicacao_id = _optional_int(request.query_params.get("aplicacao_id"))
    avaliacao_id = _optional_int(request.query_params.get("avaliacao_id"))
    resumo = AvaliacaoService().resumo_avaliacao_objetiva(
        db, aplicacao_id=aplicacao_id, avaliacao_id=avaliacao_id
    )
    from datetime import datetime as dt

    rows = [
        [r.get("aluno"), r.get("turma"), r.get("respostas"), r.get("acertos"), r.get("nota")]
        for r in resumo.get("por_aluno") or []
    ]
    return templates.TemplateResponse(
        request,
        "admin/correcao_gabaritos_imprimir.html",
        {
            "request": request,
            "current_user": current_user,
            "back_href": f"/admin/correcao-gabaritos?aplicacao_id={aplicacao_id or ''}",
            "generated_at": dt.now().strftime("%d/%m/%Y %H:%M"),
            "report_title": "Resultados da aplicação de prova",
            "report_subtitle": "Notas por aluno",
            "column_labels": ["Aluno", "Turma", "Respostas", "Acertos", "Nota"],
            "rows": rows,
        },
    )


@router.get("/admin/avaliacao-semestral")
def admin_avaliacao_semestral(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    redirect = _maybe_return_redirect(current_user)
    if redirect:
        return redirect
    from app.models.avaliacao import PerfilAvaliadoInstitucional
    from app.services.avaliacao_institucional_service import AvaliacaoInstitucionalService

    svc = AvaliacaoInstitucionalService()
    instrumentos = (
        db.query(InstrumentoAvaliacaoInstitucional)
        .options(joinedload(InstrumentoAvaliacaoInstitucional.criterios))
        .order_by(InstrumentoAvaliacaoInstitucional.id.desc())
        .all()
    )
    aplicacoes = svc.consolidado_sme(db)
    total_aplicacoes = len(aplicacoes)
    concluidas = [r for r in aplicacoes if (r.get("status") or "").strip().lower() == "concluida"]
    pendentes = total_aplicacoes - len(concluidas)
    notas_validas = [
        float(r["nota_final"])
        for r in aplicacoes
        if r.get("nota_final") is not None
    ]
    media_geral = round(sum(notas_validas) / len(notas_validas), 2) if notas_validas else 0.0

    por_perfil_map: dict[str, dict[str, Any]] = {}
    por_escola_map: dict[str, dict[str, Any]] = {}
    por_instrumento_map: dict[str, dict[str, Any]] = {}
    for r in aplicacoes:
        perfil = (r.get("perfil") or "—").strip() or "—"
        escola = (r.get("escola") or "—").strip() or "—"
        instrumento = (r.get("instrumento") or "—").strip() or "—"
        status = (r.get("status") or "").strip().lower()
        nota = r.get("nota_final")

        por_perfil_map.setdefault(perfil, {"perfil": perfil, "total": 0, "concluidas": 0, "nota_sum": 0.0, "nota_count": 0})
        por_escola_map.setdefault(escola, {"escola": escola, "total": 0, "concluidas": 0, "nota_sum": 0.0, "nota_count": 0})
        por_instrumento_map.setdefault(
            instrumento,
            {"instrumento": instrumento, "total": 0, "concluidas": 0, "pendentes": 0, "nota_sum": 0.0, "nota_count": 0},
        )

        for bucket in (por_perfil_map[perfil], por_escola_map[escola], por_instrumento_map[instrumento]):
            bucket["total"] += 1
            if status == "concluida":
                bucket["concluidas"] += 1
            if nota is not None:
                bucket["nota_sum"] += float(nota)
                bucket["nota_count"] += 1
        if status != "concluida":
            por_instrumento_map[instrumento]["pendentes"] += 1

    por_perfil = []
    for item in por_perfil_map.values():
        total = item["total"] or 0
        item["conclusao_pct"] = round((item["concluidas"] / total) * 100, 1) if total else 0
        item["nota_media"] = round(item["nota_sum"] / item["nota_count"], 2) if item["nota_count"] else 0
        por_perfil.append(item)
    por_perfil.sort(key=lambda x: x["perfil"])

    por_escola = []
    for item in por_escola_map.values():
        total = item["total"] or 0
        item["conclusao_pct"] = round((item["concluidas"] / total) * 100, 1) if total else 0
        item["nota_media"] = round(item["nota_sum"] / item["nota_count"], 2) if item["nota_count"] else 0
        por_escola.append(item)
    por_escola.sort(key=lambda x: x["escola"])

    por_instrumento = []
    for item in por_instrumento_map.values():
        total = item["total"] or 0
        item["conclusao_pct"] = round((item["concluidas"] / total) * 100, 1) if total else 0
        item["nota_media"] = round(item["nota_sum"] / item["nota_count"], 2) if item["nota_count"] else 0
        por_instrumento.append(item)
    por_instrumento.sort(key=lambda x: x["instrumento"])

    resumo_institucional = {
        "total_aplicacoes": total_aplicacoes,
        "concluidas": len(concluidas),
        "pendentes": pendentes,
        "conclusao_pct": round((len(concluidas) / total_aplicacoes) * 100, 1) if total_aplicacoes else 0,
        "nota_media_geral": media_geral,
        "por_perfil": por_perfil,
        "por_escola": por_escola,
        "por_instrumento": por_instrumento,
    }
    return templates.TemplateResponse(
        request,
        "admin/avaliacao_semestral.html",
        {
            "request": request,
            "current_user": current_user,
            "resumo_institucional": resumo_institucional,
            "ciclos": svc.listar_ciclos(db),
            "instrumentos": instrumentos,
            "aplicacoes": aplicacoes,
            "perfil_choices": list(PerfilAvaliadoInstitucional),
            "usuarios": db.query(Usuario).filter(Usuario.ativo.is_(True)).order_by(Usuario.nome).all(),
            "escolas": db.query(Escola).filter(Escola.ativo.is_(True)).order_by(Escola.nome).all(),
            "flash_ok": request.query_params.get("ok"),
            "flash_err": request.query_params.get("err"),
        },
    )


@router.post("/admin/avaliacao-semestral/ciclos")
async def admin_avaliacao_semestral_ciclos(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    redirect = _maybe_return_redirect(current_user)
    if redirect:
        return redirect
    from app.services.avaliacao_institucional_service import AvaliacaoInstitucionalService

    form = await request.form()
    titulo = (form.get("titulo") or "").strip()
    if not titulo:
        return _redirect_with_message("/admin/avaliacao-semestral?err=T%C3%ADtulo%20obrigat%C3%B3rio")
    AvaliacaoInstitucionalService().criar_ciclo(
        db,
        titulo=titulo,
        ano_letivo=(form.get("ano_letivo") or "2026").strip(),
        semestre=(form.get("semestre") or "1").strip(),
        criado_por_usuario_id=current_user.id,
    )
    return _redirect_with_message("/admin/avaliacao-semestral?ok=ciclo")


@router.post("/admin/avaliacao-semestral/instrumentos")
async def admin_avaliacao_semestral_instrumentos(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    redirect = _maybe_return_redirect(current_user)
    if redirect:
        return redirect
    from app.services.avaliacao_institucional_service import AvaliacaoInstitucionalService

    form = await request.form()
    nome = (form.get("nome") or "").strip()
    perfil = (form.get("perfil") or "").strip()
    if not nome or not perfil:
        return _redirect_with_message("/admin/avaliacao-semestral?err=Informe%20nome%20e%20perfil")
    criterios_brutos = [(c or "").strip() for c in form.getlist("criterio_titulo")]
    criterios_validos = [c for c in criterios_brutos if c]
    if not criterios_validos:
        return _redirect_with_message("/admin/avaliacao-semestral?err=Informe%20ao%20menos%201%20crit%C3%A9rio")

    inst = AvaliacaoInstitucionalService().criar_instrumento(
        db,
        nome=nome,
        perfil=perfil,
        ciclo_id=_optional_int(form.get("ciclo_id")),
        descricao=(form.get("descricao") or "").strip() or None,
    )
    for idx, titulo_criterio in enumerate(criterios_validos):
        AvaliacaoInstitucionalService().criar_criterio(
            db,
            instrumento_id=inst.id,
            titulo=titulo_criterio,
            peso=1.0,
            descricao=f"Ordem {idx + 1}",
        )
    return _redirect_with_message("/admin/avaliacao-semestral?ok=instrumento")


@router.post("/admin/avaliacao-semestral/aplicacoes")
async def admin_avaliacao_semestral_aplicacoes(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    redirect = _maybe_return_redirect(current_user)
    if redirect:
        return redirect
    from app.services.avaliacao_institucional_service import AvaliacaoInstitucionalService

    form = await request.form()
    ciclo_id = _optional_int(form.get("ciclo_id"))
    instrumento_id = _optional_int(form.get("instrumento_id"))
    if not all([ciclo_id, instrumento_id]):
        return _redirect_with_message("/admin/avaliacao-semestral?err=Dados%20incompletos")

    instrumento = (
        db.query(InstrumentoAvaliacaoInstitucional)
        .filter(InstrumentoAvaliacaoInstitucional.id == instrumento_id)
        .first()
    )
    if not instrumento:
        return _redirect_with_message("/admin/avaliacao-semestral?err=Instrumento%20inv%C3%A1lido")
    if not instrumento.criterios:
        return _redirect_with_message("/admin/avaliacao-semestral?err=Instrumento%20sem%20crit%C3%A9rios%20n%C3%A3o%20pode%20ser%20aplicado")
    escola_id = _optional_int(form.get("escola_id"))

    perfil_alvo = getattr(instrumento.perfil_avaliado, "value", instrumento.perfil_avaliado)
    usuarios_query = db.query(Usuario).filter(Usuario.ativo.is_(True))
    if perfil_alvo == PerfilAvaliadoInstitucional.GESTOR.value:
        usuarios_query = usuarios_query.filter(Usuario.role == UserRole.GESTOR)
        if escola_id:
            usuarios_query = usuarios_query.join(GestorEscola, GestorEscola.gestor_id == Usuario.id).filter(
                GestorEscola.escola_id == escola_id
            )
    elif perfil_alvo == PerfilAvaliadoInstitucional.COORDENADOR.value:
        usuarios_query = usuarios_query.filter(Usuario.role == UserRole.COORDENADOR)
        if escola_id:
            usuarios_query = usuarios_query.join(
                CoordenadorEscola, CoordenadorEscola.coordenador_id == Usuario.id
            ).filter(CoordenadorEscola.escola_id == escola_id)
    elif perfil_alvo == PerfilAvaliadoInstitucional.PDT.value:
        usuarios_query = usuarios_query.filter(
            Usuario.role == UserRole.PROFESSOR,
            Usuario.funcao_docente == TeacherRole.PDT,
        )
        if escola_id:
            usuarios_query = (
                usuarios_query.join(ProfessorTurma, ProfessorTurma.professor_id == Usuario.id)
                .join(Turma, Turma.id == ProfessorTurma.turma_id)
                .filter(Turma.escola_id == escola_id)
            )
    else:
        return _redirect_with_message("/admin/avaliacao-semestral?err=Perfil%20do%20instrumento%20inv%C3%A1lido")

    usuarios_alvo = usuarios_query.distinct().all()
    if not usuarios_alvo:
        return _redirect_with_message(
            "/admin/avaliacao-semestral?err=Nenhum%20usu%C3%A1rio%20ativo%20encontrado%20para%20este%20perfil"
        )

    criadas = 0
    for usuario in usuarios_alvo:
        ja_existe = (
            db.query(AplicacaoAvaliacaoInstitucional.id)
            .filter(
                AplicacaoAvaliacaoInstitucional.ciclo_id == ciclo_id,
                AplicacaoAvaliacaoInstitucional.instrumento_id == instrumento_id,
                AplicacaoAvaliacaoInstitucional.avaliado_usuario_id == usuario.id,
                AplicacaoAvaliacaoInstitucional.escola_id == escola_id,
            )
            .first()
        )
        if ja_existe:
            continue
        AvaliacaoInstitucionalService().criar_aplicacao(
            db,
            ciclo_id=ciclo_id,
            instrumento_id=instrumento_id,
            avaliado_usuario_id=usuario.id,
            escola_id=escola_id,
            respondente_usuario_id=None,
        )
        criadas += 1

    if criadas == 0:
        return _redirect_with_message(
            "/admin/avaliacao-semestral?err=Todas%20as%20aplica%C3%A7%C3%B5es%20deste%20perfil%20j%C3%A1%20foram%20geradas"
        )
    return _redirect_with_message(f"/admin/avaliacao-semestral?ok=aplicacoes_{criadas}")


@router.post("/admin/avaliacao-semestral/instrumentos/{instrumento_id}/editar")
async def admin_avaliacao_semestral_instrumento_editar(
    instrumento_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    redirect = _maybe_return_redirect(current_user)
    if redirect:
        return redirect
    _ = current_user
    instrumento = (
        db.query(InstrumentoAvaliacaoInstitucional)
        .options(joinedload(InstrumentoAvaliacaoInstitucional.criterios))
        .filter(InstrumentoAvaliacaoInstitucional.id == instrumento_id)
        .first()
    )
    if not instrumento:
        return _redirect_with_message("/admin/avaliacao-semestral?err=Question%C3%A1rio%20n%C3%A3o%20encontrado")

    respostas_existem = (
        db.query(func.count(1))
        .select_from(AplicacaoAvaliacaoInstitucional)
        .join(
            CriterioAvaliacaoInstitucional,
            CriterioAvaliacaoInstitucional.instrumento_id == AplicacaoAvaliacaoInstitucional.instrumento_id,
        )
        .join(
            RespostaAvaliacaoInstitucional,
            RespostaAvaliacaoInstitucional.criterio_id == CriterioAvaliacaoInstitucional.id,
        )
        .filter(AplicacaoAvaliacaoInstitucional.instrumento_id == instrumento_id)
        .scalar()
        or 0
    )
    if respostas_existem:
        return _redirect_with_message(
            "/admin/avaliacao-semestral?err=Question%C3%A1rio%20com%20respostas%20n%C3%A3o%20pode%20ser%20editado"
        )

    form = await request.form()
    nome = (form.get("nome") or "").strip()
    perfil = (form.get("perfil") or "").strip()
    if not nome or not perfil:
        return _redirect_with_message("/admin/avaliacao-semestral?err=Informe%20nome%20e%20perfil")
    criterios_brutos = [(c or "").strip() for c in form.getlist("criterio_titulo")]
    criterios_validos = [c for c in criterios_brutos if c]
    if not criterios_validos:
        return _redirect_with_message("/admin/avaliacao-semestral?err=Informe%20ao%20menos%201%20pergunta")

    try:
        instrumento.perfil_avaliado = PerfilAvaliadoInstitucional(perfil)
    except ValueError:
        return _redirect_with_message("/admin/avaliacao-semestral?err=Perfil%20inv%C3%A1lido")
    instrumento.nome = nome
    instrumento.descricao = (form.get("descricao") or "").strip() or None
    instrumento.ciclo_id = _optional_int(form.get("ciclo_id"))
    db.flush()
    db.query(CriterioAvaliacaoInstitucional).filter(
        CriterioAvaliacaoInstitucional.instrumento_id == instrumento.id
    ).delete(synchronize_session=False)
    for idx, titulo in enumerate(criterios_validos):
        db.add(
            CriterioAvaliacaoInstitucional(
                instrumento_id=instrumento.id,
                titulo=titulo,
                descricao=f"Ordem {idx + 1}",
                peso=1.0,
                ordem=idx,
            )
        )
    db.commit()
    return _redirect_with_message("/admin/avaliacao-semestral?ok=instrumento_editado")


@router.post("/admin/avaliacao-semestral/instrumentos/{instrumento_id}/excluir")
def admin_avaliacao_semestral_instrumento_excluir(
    instrumento_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    redirect = _maybe_return_redirect(current_user)
    if redirect:
        return redirect
    _ = current_user
    instrumento = (
        db.query(InstrumentoAvaliacaoInstitucional)
        .filter(InstrumentoAvaliacaoInstitucional.id == instrumento_id)
        .first()
    )
    if not instrumento:
        return _redirect_with_message("/admin/avaliacao-semestral?err=Question%C3%A1rio%20n%C3%A3o%20encontrado")
    apps_count = (
        db.query(func.count(AplicacaoAvaliacaoInstitucional.id))
        .filter(AplicacaoAvaliacaoInstitucional.instrumento_id == instrumento_id)
        .scalar()
        or 0
    )
    if apps_count:
        return _redirect_with_message(
            "/admin/avaliacao-semestral?err=Question%C3%A1rio%20com%20aplica%C3%A7%C3%B5es%20n%C3%A3o%20pode%20ser%20exclu%C3%ADdo"
        )
    db.query(CriterioAvaliacaoInstitucional).filter(
        CriterioAvaliacaoInstitucional.instrumento_id == instrumento_id
    ).delete(synchronize_session=False)
    db.delete(instrumento)
    db.commit()
    return _redirect_with_message("/admin/avaliacao-semestral?ok=instrumento_excluido")


@router.post("/admin/avaliacao-semestral/aplicacoes/{aplicacao_id}/excluir")
def admin_avaliacao_semestral_aplicacao_excluir(
    aplicacao_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    redirect = _maybe_return_redirect(current_user)
    if redirect:
        return redirect
    _ = current_user
    aplicacao = (
        db.query(AplicacaoAvaliacaoInstitucional)
        .filter(AplicacaoAvaliacaoInstitucional.id == aplicacao_id)
        .first()
    )
    if not aplicacao:
        return _redirect_with_message("/admin/avaliacao-semestral?err=Aplica%C3%A7%C3%A3o%20n%C3%A3o%20encontrada")

    db.query(RespostaAvaliacaoInstitucional).filter(
        RespostaAvaliacaoInstitucional.aplicacao_id == aplicacao.id
    ).delete(synchronize_session=False)
    db.delete(aplicacao)
    db.commit()
    return _redirect_with_message("/admin/avaliacao-semestral?ok=aplicacao_excluida")


@router.get("/admin/avaliacao-semestral/export.csv")
def admin_avaliacao_semestral_export(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    redirect = _maybe_return_redirect(current_user)
    if redirect:
        return redirect
    rows_raw = AvaliacaoInstitucionalService().consolidado_sme(db)
    headers = ["aplicacao_id", "instrumento", "perfil", "escola", "avaliado", "nota_final", "status"]
    rows: list[list[Any]] = [
        [
            r.get("aplicacao_id", ""),
            r.get("instrumento", ""),
            r.get("perfil", ""),
            r.get("escola", ""),
            r.get("avaliado", ""),
            r.get("nota_final", "") if r.get("nota_final") is not None else "",
            r.get("status", ""),
        ]
        for r in rows_raw
    ]
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(headers)
    writer.writerows(rows)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=avaliacao_semestral.csv"},
    )


@router.get("/admin/avaliacao-semestral/imprimir")
def admin_avaliacao_semestral_imprimir(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    redirect = _maybe_return_redirect(current_user)
    if redirect:
        return redirect
    from datetime import datetime as dt

    rows_raw = AvaliacaoInstitucionalService().consolidado_sme(db)
    rows = [
        [
            r.get("instrumento", ""),
            r.get("perfil", ""),
            r.get("escola", ""),
            r.get("avaliado", ""),
            r.get("nota_final", "—") if r.get("nota_final") is not None else "—",
            r.get("status", ""),
        ]
        for r in rows_raw
    ]
    return templates.TemplateResponse(
        request,
        "shared/relatorio_imprimir.html",
        {
            "request": request,
            "report_title": "Avaliação semestral — Questionários institucionais",
            "report_subtitle": "Consolidado de respostas por instrumento, perfil e escola",
            "column_labels": ["Instrumento", "Perfil", "Escola", "Avaliado", "Nota final", "Status"],
            "rows": rows,
            "generated_at": dt.now().strftime("%d/%m/%Y %H:%M"),
            "back_href": "/admin/avaliacao-semestral",
            "report_author_label": "Secretaria",
            "report_author_name": (current_user.nome or "").strip(),
            "report_kicker": "Mj Connect Edu — Avaliação Institucional",
        },
    )


@router.get("/admin/devolutiva-poc")
def admin_devolutiva_poc(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    from app.services.licitacao_service import LicitacaoService

    sme = LicitacaoService().get_sme_dashboard(db)
    consolidado = AvaliacaoService().consolidado_desempenho(db)
    from app.services.avaliacao_institucional_service import AvaliacaoInstitucionalService

    semestral = AvaliacaoInstitucionalService().consolidado_sme(db)
    return templates.TemplateResponse(
        request,
        "admin/devolutiva_poc.html",
        {
            "request": request,
            "current_user": current_user,
            "sme_stats": sme,
            "prova_resumo": consolidado,
            "semestral": semestral,
        },
    )


@router.get("/gestor/avaliacao-semestral")
def gestor_avaliacao_semestral(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.GESTOR)),
):
    from app.models.avaliacao import AplicacaoAvaliacaoInstitucional, InstrumentoAvaliacaoInstitucional
    from app.models.relacoes import GestorEscola

    escola_ids = [
        r[0] for r in db.query(GestorEscola.escola_id).filter(GestorEscola.gestor_id == current_user.id).all()
    ]
    q = (
        db.query(AplicacaoAvaliacaoInstitucional, InstrumentoAvaliacaoInstitucional)
        .join(InstrumentoAvaliacaoInstitucional, InstrumentoAvaliacaoInstitucional.id == AplicacaoAvaliacaoInstitucional.instrumento_id)
    )
    if escola_ids:
        q = q.filter(AplicacaoAvaliacaoInstitucional.escola_id.in_(escola_ids))
    rows = q.order_by(AplicacaoAvaliacaoInstitucional.id.desc()).limit(50).all()
    return templates.TemplateResponse(
        request,
        "gestor/avaliacao_semestral.html",
        {"request": request, "current_user": current_user, "rows": rows},
    )


@router.post("/coordenador/avaliacao-semestral/{aplicacao_id}/responder")
async def coordenador_avaliacao_semestral_responder(
    aplicacao_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.COORDENADOR)),
):
    from urllib.parse import quote

    from app.models.resposta import RespostaAvaliacaoInstitucional
    from app.services.avaliacao_institucional_service import AvaliacaoInstitucionalService

    app_inst = (
        db.query(AplicacaoAvaliacaoInstitucional, InstrumentoAvaliacaoInstitucional)
        .join(
            InstrumentoAvaliacaoInstitucional,
            InstrumentoAvaliacaoInstitucional.id == AplicacaoAvaliacaoInstitucional.instrumento_id,
        )
        .filter(
            AplicacaoAvaliacaoInstitucional.id == aplicacao_id,
            AplicacaoAvaliacaoInstitucional.avaliado_usuario_id == current_user.id,
            AplicacaoAvaliacaoInstitucional.status == StatusAplicacaoInstitucional.ABERTA,
            InstrumentoAvaliacaoInstitucional.perfil_avaliado == PerfilAvaliadoInstitucional.COORDENADOR,
        )
        .first()
    )
    if not app_inst:
        return RedirectResponse(
            url=f"/coordenador?err={quote('Aplicação institucional inválida ou indisponível.')}",
            status_code=303,
        )
    aplicacao, instrumento = app_inst
    criterios = (
        db.query(RespostaAvaliacaoInstitucional.criterio_id)
        .filter(RespostaAvaliacaoInstitucional.aplicacao_id == aplicacao.id)
        .all()
    )
    if criterios:
        return RedirectResponse(
            url=f"/coordenador?err={quote('Esta avaliação já foi respondida.')}",
            status_code=303,
        )
    form = await request.form()
    notas: list[dict[str, Any]] = []
    for criterio in instrumento.criterios:
        raw = (form.get(f"nota_{criterio.id}") or "").strip().replace(",", ".")
        try:
            nota_val = float(raw)
        except (TypeError, ValueError):
            nota_val = -1.0
        if nota_val < 0 or nota_val > 5:
            return RedirectResponse(
                url=f"/coordenador?err={quote('Informe notas válidas de 0 a 5 em todos os critérios.')}",
                status_code=303,
            )
        notas.append(
            {
                "criterio_id": criterio.id,
                "nota": nota_val,
                "comentario": (form.get(f"comentario_{criterio.id}") or "").strip() or None,
            }
        )
    AvaliacaoInstitucionalService().salvar_respostas(
        db,
        aplicacao_id=aplicacao.id,
        notas=notas,
        devolutiva=(form.get("devolutiva_resumo") or "").strip() or None,
        respondente_usuario_id=current_user.id,
    )
    return RedirectResponse(url="/coordenador?ok=avaliacao_institucional", status_code=303)


@router.post("/professor/avaliacao-semestral/{aplicacao_id}/responder")
async def professor_avaliacao_semestral_responder(
    aplicacao_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.PROFESSOR)),
):
    from urllib.parse import quote

    from app.models.resposta import RespostaAvaliacaoInstitucional
    from app.services.avaliacao_institucional_service import AvaliacaoInstitucionalService

    if current_user.funcao_docente != TeacherRole.PDT:
        return RedirectResponse(
            url=f"/professor?err={quote('Apenas Professor Diretor de Turma pode responder esta avaliação.')}",
            status_code=303,
        )
    app_inst = (
        db.query(AplicacaoAvaliacaoInstitucional, InstrumentoAvaliacaoInstitucional)
        .join(
            InstrumentoAvaliacaoInstitucional,
            InstrumentoAvaliacaoInstitucional.id == AplicacaoAvaliacaoInstitucional.instrumento_id,
        )
        .filter(
            AplicacaoAvaliacaoInstitucional.id == aplicacao_id,
            AplicacaoAvaliacaoInstitucional.avaliado_usuario_id == current_user.id,
            AplicacaoAvaliacaoInstitucional.status == StatusAplicacaoInstitucional.ABERTA,
            InstrumentoAvaliacaoInstitucional.perfil_avaliado == PerfilAvaliadoInstitucional.PDT,
        )
        .first()
    )
    if not app_inst:
        return RedirectResponse(
            url=f"/professor?err={quote('Aplicação institucional inválida ou indisponível.')}",
            status_code=303,
        )
    aplicacao, instrumento = app_inst
    criterios = (
        db.query(RespostaAvaliacaoInstitucional.criterio_id)
        .filter(RespostaAvaliacaoInstitucional.aplicacao_id == aplicacao.id)
        .all()
    )
    if criterios:
        return RedirectResponse(
            url=f"/professor?err={quote('Esta avaliação já foi respondida.')}",
            status_code=303,
        )
    form = await request.form()
    notas: list[dict[str, Any]] = []
    for criterio in instrumento.criterios:
        raw = (form.get(f"nota_{criterio.id}") or "").strip().replace(",", ".")
        try:
            nota_val = float(raw)
        except (TypeError, ValueError):
            nota_val = -1.0
        if nota_val < 0 or nota_val > 5:
            return RedirectResponse(
                url=f"/professor?err={quote('Informe notas válidas de 0 a 5 em todos os critérios.')}",
                status_code=303,
            )
        notas.append(
            {
                "criterio_id": criterio.id,
                "nota": nota_val,
                "comentario": (form.get(f"comentario_{criterio.id}") or "").strip() or None,
            }
        )
    AvaliacaoInstitucionalService().salvar_respostas(
        db,
        aplicacao_id=aplicacao.id,
        notas=notas,
        devolutiva=(form.get("devolutiva_resumo") or "").strip() or None,
        respondente_usuario_id=current_user.id,
    )
    return RedirectResponse(url="/professor?ok=avaliacao_institucional", status_code=303)


@router.get("/admin/comunicacao")
def admin_comunicacao_stub(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    """Fase 6: canal de comunicação até integração com fórum Moodle."""
    return templates.TemplateResponse(
        request,
        "admin/comunicacao_stub.html",
        {"request": request, "current_user": current_user},
    )


@router.get("/admin/formacao-bncc")
def admin_formacao_bncc(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    service = FormacaoService()
    return templates.TemplateResponse(
        request,
        "admin/formacao_bncc.html",
        {
            "request": request,
            "current_user": current_user,
            "resumo": service.resumo_programas(db),
            "programas": db.query(ProgramaFormacaoBNCC).order_by(ProgramaFormacaoBNCC.id.desc()).all(),
            "turmas_formacao": db.query(TurmaFormacaoBNCC).order_by(TurmaFormacaoBNCC.id.desc()).all(),
            "participantes": db.query(ParticipanteTurmaFormacaoBNCC).order_by(ParticipanteTurmaFormacaoBNCC.id.desc()).all(),
            "escolas": db.query(Escola).filter(Escola.ativo.is_(True)).order_by(Escola.nome.asc()).all(),
            "trilhas": db.query(Trilha).order_by(Trilha.nome.asc()).all(),
            "moodle_catalog": db.query(MoodleCourseCatalog).order_by(MoodleCourseCatalog.fullname.asc()).all(),
            "usuarios_formacao": db.query(Usuario).filter(Usuario.ativo.is_(True), Usuario.role.in_([UserRole.PROFESSOR, UserRole.COORDENADOR, UserRole.GESTOR, UserRole.ADMIN])).order_by(Usuario.nome.asc()).all(),
            "papel_participante_choices": list(PapelParticipanteFormacao),
            "tipo_recurso_choices": list(TipoRecursoFormacao),
            "encontros": db.query(EncontroPresencialFormacaoBNCC).order_by(EncontroPresencialFormacaoBNCC.data_encontro.desc()).limit(30).all(),
            "flash_ok": (request.query_params.get("ok") or "").strip(),
            "flash_err": (request.query_params.get("err") or "").strip(),
        },
    )


@router.post("/admin/formacao-bncc/programas")
async def admin_formacao_bncc_programas(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    form = await request.form()
    nome = (form.get("nome") or "").strip()
    if not nome:
        return _redirect_with_message("/admin/formacao-bncc?err=Informe%20o%20nome%20do%20programa.")
    programa = FormacaoService().criar_programa(
        db,
        nome=nome,
        descricao=(form.get("descricao") or "").strip() or None,
        publico_alvo=(form.get("publico_alvo") or "").strip() or None,
    )
    AuditService.log(
        db,
        usuario_id=current_user.id if current_user else None,
        acao="programa_formacao_criado",
        categoria="licitacao",
        entidade="programa_formacao_bncc",
        entidade_id=programa.id,
        detalhes=f"Programa BNCC criado: {programa.nome}",
        ip=request.client.host if request.client else None,
    )
    return _redirect_with_message("/admin/formacao-bncc?ok=programa")


@router.post("/admin/formacao-bncc/recursos")
async def admin_formacao_bncc_recursos(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    form = await request.form()
    try:
        programa_id = int(form.get("programa_id") or 0)
        tipo = TipoRecursoFormacao((form.get("tipo_recurso") or "").strip())
    except Exception:
        return _redirect_with_message("/admin/formacao-bncc?err=Programa%20ou%20tipo%20de%20recurso%20inv%C3%A1lido.")
    recurso = FormacaoService().vincular_recurso(
        db,
        programa_id=programa_id,
        tipo_recurso=tipo,
        titulo=(form.get("titulo") or "").strip(),
        trilha_id=int(form.get("trilha_id") or 0) or None,
        moodle_course_id=int(form.get("moodle_course_id") or 0) or None,
        descricao=(form.get("descricao") or "").strip() or None,
    )
    AuditService.log(
        db,
        usuario_id=current_user.id if current_user else None,
        acao="recurso_formacao_vinculado",
        categoria="licitacao",
        entidade="programa_formacao_recurso",
        entidade_id=recurso.id,
        detalhes=f"Recurso {recurso.tipo_recurso} vinculado ao programa {programa_id}",
        ip=request.client.host if request.client else None,
    )
    return _redirect_with_message("/admin/formacao-bncc?ok=recurso")


@router.post("/admin/formacao-bncc/turmas")
async def admin_formacao_bncc_turmas(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    form = await request.form()
    try:
        programa_id = int(form.get("programa_id") or 0)
    except Exception:
        return _redirect_with_message("/admin/formacao-bncc?err=Programa%20inv%C3%A1lido.")
    turma = FormacaoService().criar_turma(
        db,
        programa_id=programa_id,
        nome=(form.get("nome") or "").strip(),
        escola_id=int(form.get("escola_id") or 0) or None,
        limite_participantes=int(form.get("limite_participantes") or 30) or 30,
    )
    AuditService.log(
        db,
        usuario_id=current_user.id if current_user else None,
        acao="turma_formacao_criada",
        categoria="licitacao",
        entidade="turma_formacao_bncc",
        entidade_id=turma.id,
        detalhes=f"Turma de formação criada: {turma.nome}",
        ip=request.client.host if request.client else None,
    )
    return _redirect_with_message("/admin/formacao-bncc?ok=turma")


@router.post("/admin/formacao-bncc/inscricoes")
async def admin_formacao_bncc_inscricoes(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    form = await request.form()
    try:
        turma_id = int(form.get("turma_id") or 0)
        usuario_id = int(form.get("usuario_id") or 0)
        papel = PapelParticipanteFormacao((form.get("papel_participante") or "").strip())
    except Exception:
        return _redirect_with_message("/admin/formacao-bncc?err=Dados%20de%20inscri%C3%A7%C3%A3o%20inv%C3%A1lidos.")
    participante = FormacaoService().inscrever_participante(
        db,
        turma_id=turma_id,
        usuario_id=usuario_id,
        papel_participante=papel,
    )
    AuditService.log(
        db,
        usuario_id=current_user.id if current_user else None,
        acao="participante_inscrito",
        categoria="licitacao",
        entidade="participante_turma_formacao_bncc",
        entidade_id=participante.id,
        detalhes=f"Participante {usuario_id} inscrito na turma {turma_id}",
        ip=request.client.host if request.client else None,
    )
    return _redirect_with_message("/admin/formacao-bncc?ok=inscricao")


@router.post("/admin/formacao-bncc/participantes/{participante_id}/progresso")
async def admin_formacao_bncc_progresso(
    participante_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    form = await request.form()
    participante = FormacaoService().atualizar_progresso_participante(
        db,
        participante_id=participante_id,
        carga_horaria_remota_realizada=float(form.get("carga_horaria_remota_realizada") or 0),
        carga_horaria_presencial_realizada=float(form.get("carga_horaria_presencial_realizada") or 0),
        devolutiva=(form.get("devolutiva") or "").strip() or None,
    )
    if not participante:
        return _redirect_with_message("/admin/formacao-bncc?err=Participante%20n%C3%A3o%20encontrado.")
    AuditService.log(
        db,
        usuario_id=current_user.id if current_user else None,
        acao="participante_formacao_atualizado",
        categoria="licitacao",
        entidade="participante_turma_formacao_bncc",
        entidade_id=participante.id,
        detalhes=f"Progresso atualizado para participante {participante.id}",
        ip=request.client.host if request.client else None,
    )
    return _redirect_with_message("/admin/formacao-bncc?ok=progresso")


@router.post("/admin/formacao-bncc/encontros")
async def admin_formacao_bncc_encontros(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    form = await request.form()
    turma_id = _optional_int(form.get("turma_id"))
    titulo = (form.get("titulo") or "").strip()
    if not turma_id or not titulo:
        return _redirect_with_message("/admin/formacao-bncc?err=Informe%20turma%20e%20t%C3%ADtulo%20do%20encontro.")
    data_raw = (form.get("data_encontro") or "").strip()
    try:
        data_encontro = datetime.fromisoformat(data_raw) if data_raw else datetime.utcnow()
    except ValueError:
        data_encontro = datetime.utcnow()
    FormacaoService().criar_encontro_presencial(
        db,
        turma_id=turma_id,
        titulo=titulo,
        data_encontro=data_encontro,
        carga_horaria=float(form.get("carga_horaria") or 4),
        local=(form.get("local") or "").strip() or None,
    )
    return _redirect_with_message("/admin/formacao-bncc?ok=encontro")


@router.get("/admin/formacao-bncc/certificado/{participante_id}.pdf")
def admin_formacao_bncc_certificado(
    participante_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    try:
        pdf_bytes, filename = FormacaoService().gerar_certificado_pdf(db, participante_id=participante_id)
    except ValueError as exc:
        return _redirect_with_message(f"/admin/formacao-bncc?err={str(exc).replace(' ', '%20')}")
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/coordenador/formacao-bncc")
def coordenador_formacao_bncc(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.COORDENADOR)),
):
    service = FormacaoService()
    return templates.TemplateResponse(
        request,
        "professor/formacao_bncc.html",
        {
            "request": request,
            "current_user": current_user,
            "programas": service.listagem_programas(db),
            "back_url": "/coordenador",
        },
    )


@router.get("/admin/relatorios-sme")
def admin_relatorios_sme(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    imprimir_raw = (request.query_params.get("imprimir") or "").strip().lower()
    modo_impressao = imprimir_raw in ("1", "true", "sim", "yes")
    tipo = (request.query_params.get("tipo") or "").strip() or "sme_completo"
    licitacao_service = LicitacaoService()
    if modo_impressao:
        allowed = {"sme_completo", "avaliacao_institucional", "avaliacao_larga_escala", "avaliacao_por_escola", "avaliacao_semestral"}
        if tipo not in allowed:
            return RedirectResponse(url="/admin/relatorios-sme", status_code=303)
        headers, rows = licitacao_service.relatorio_sme_rows(db, tipo)
        title_map = {
            "sme_completo": "Relatório geral completo da Secretaria",
            "avaliacao_institucional": "Relatório geral da rede",
            "avaliacao_larga_escala": "Relatório por turma (larga escala)",
            "avaliacao_por_escola": "Relatório por escola",
            "avaliacao_semestral": "Relatório avaliação semestral",
        }
        return templates.TemplateResponse(
            request,
            "admin/relatorios_sme.html",
            {
                "request": request,
                "current_user": current_user,
                "modo_impressao": True,
                "report_title": title_map.get(tipo, "Relatório Secretaria"),
                "report_subtitle": "Secretaria Municipal de Educação — visão consolidada da rede",
                "column_labels": headers,
                "rows": rows,
                "generated_at": datetime.now().strftime("%d/%m/%Y %H:%M"),
                "back_href": "/admin/relatorios-sme",
                "report_author_label": "Secretaria",
                "report_author_name": (current_user.nome or "").strip(),
                "report_kicker": "Mj Connect Edu — Relatório da Secretaria",
            },
        )

    headers_sme, rows_sme, cards_escola, turmas_por_escola = licitacao_service.relatorio_sme_completo(db)
    return templates.TemplateResponse(
        request,
        "admin/relatorios_sme.html",
        {
            "request": request,
            "current_user": current_user,
            "modo_impressao": False,
            "headers_sme": headers_sme,
            "rows_sme": rows_sme,
            "cards_escola": cards_escola,
            "turmas_por_escola": turmas_por_escola,
        },
    )


@router.get("/admin/relatorios-sme/export.csv")
def admin_relatorios_sme_export(
    tipo: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    _ = current_user
    licitacao_service = LicitacaoService()
    headers, rows = licitacao_service.relatorio_sme_rows(db, tipo)
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(headers)
    for row in rows:
        writer.writerow(row)
    data = "\ufeff" + output.getvalue()
    return StreamingResponse(
        iter([data]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{tipo}.csv"'},
    )


@router.get("/admin/conformidade")
def admin_conformidade(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    return templates.TemplateResponse(
        request,
        "admin/conformidade.html",
        {
            "request": request,
            "current_user": current_user,
            "snapshot": LicitacaoService().conformidade_snapshot(db),
        },
    )


@router.get("/gestor/avaliacoes-institucionais")
def gestor_avaliacoes_institucionais(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.GESTOR)),
):
    escola_ids = [r[0] for r in db.query(GestorEscola.escola_id).filter(GestorEscola.gestor_id == current_user.id).all()]
    consolidado = AvaliacaoService().consolidado_desempenho(db, escola_ids=escola_ids)
    return templates.TemplateResponse(
        request,
        "gestor/avaliacoes_institucionais.html",
        {"request": request, "current_user": current_user, "consolidado": consolidado},
    )


@router.get("/coordenador/avaliacoes-institucionais")
def coordenador_avaliacoes_institucionais(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.COORDENADOR)),
):
    escola_id = (
        db.query(CoordenadorEscola.escola_id)
        .join(Escola, CoordenadorEscola.escola_id == Escola.id)
        .filter(CoordenadorEscola.coordenador_id == current_user.id, Escola.ativo.is_(True))
        .scalar()
    )
    turma_ids_escola = (
        [r[0] for r in db.query(Turma.id).filter(Turma.escola_id == escola_id).all()]
        if escola_id
        else []
    )
    consolidado = AvaliacaoService().consolidado_desempenho(
        db,
        escola_ids=[escola_id] if escola_id else None,
        turma_ids=turma_ids_escola if turma_ids_escola else None,
    )
    return templates.TemplateResponse(
        request,
        "coordenador/avaliacoes_institucionais.html",
        {"request": request, "current_user": current_user, "consolidado": consolidado},
    )


@router.get("/coordenador/avaliacoes-institucionais/export.csv")
def coordenador_avaliacoes_institucionais_export_csv(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.COORDENADOR)),
):
    escola_id = (
        db.query(CoordenadorEscola.escola_id)
        .join(Escola, CoordenadorEscola.escola_id == Escola.id)
        .filter(CoordenadorEscola.coordenador_id == current_user.id, Escola.ativo.is_(True))
        .scalar()
    )
    turma_ids_escola = [r[0] for r in db.query(Turma.id).filter(Turma.escola_id == escola_id).all()] if escola_id else []
    consolidado = AvaliacaoService().consolidado_desempenho(
        db,
        escola_ids=[escola_id] if escola_id else None,
        turma_ids=turma_ids_escola if turma_ids_escola else None,
    )
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(["turma", "participacao_pct", "nota_media"])
    for row in consolidado.get("por_turma") or []:
        writer.writerow([row.get("turma", ""), row.get("participacao_pct", 0), row.get("nota_media", 0)])
    data = "\ufeff" + output.getvalue()
    return StreamingResponse(
        iter([data]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="coordenador_desempenho_provas.csv"'},
    )


@router.get("/coordenador/avaliacoes-institucionais/imprimir")
def coordenador_avaliacoes_institucionais_imprimir(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.COORDENADOR)),
):
    escola_id = (
        db.query(CoordenadorEscola.escola_id)
        .join(Escola, CoordenadorEscola.escola_id == Escola.id)
        .filter(CoordenadorEscola.coordenador_id == current_user.id, Escola.ativo.is_(True))
        .scalar()
    )
    turma_ids_escola = [r[0] for r in db.query(Turma.id).filter(Turma.escola_id == escola_id).all()] if escola_id else []
    consolidado = AvaliacaoService().consolidado_desempenho(
        db,
        escola_ids=[escola_id] if escola_id else None,
        turma_ids=turma_ids_escola if turma_ids_escola else None,
    )
    rows = [
        [row.get("turma", ""), f"{row.get('participacao_pct', 0)}%", row.get("nota_media", 0)]
        for row in (consolidado.get("por_turma") or [])
    ]
    return templates.TemplateResponse(
        request,
        "shared/relatorio_imprimir.html",
        {
            "request": request,
            "report_title": "Desempenho institucional da escola",
            "report_subtitle": "Resultados por turma no escopo da coordenação",
            "column_labels": ["Turma", "Participação", "Média nas provas"],
            "rows": rows,
            "generated_at": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "back_href": "/coordenador/avaliacoes-institucionais",
            "report_author_label": "Coordenação",
            "report_author_name": (current_user.nome or "").strip(),
            "report_kicker": "Mj Connect Edu — Desempenho em provas",
        },
    )


@router.get("/professor/avaliacao-institucional")
def professor_avaliacao_institucional_redirect(
    request: Request,
    current_user: Usuario = Depends(require_role_redirect(UserRole.PROFESSOR)),
):
    _ = (request, current_user)
    return _redirect_with_message("/professor/banco-questoes", status_code=302)


@router.get("/professor/banco-questoes")
def professor_banco_questoes(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.PROFESSOR)),
):
    service = AvaliacaoService()
    questoes = service.listar_banco_questoes(
        db,
        autor_usuario_id=current_user.id,
        curso_id=_optional_int(request.query_params.get("curso_id")),
        ano_escolar=_optional_int(request.query_params.get("ano_escolar")),
        descritor_id=_optional_int(request.query_params.get("descritor_id")),
        conteudo=(request.query_params.get("conteudo") or "").strip() or None,
        termo=(request.query_params.get("q") or "").strip() or None,
        tipo_questao=(request.query_params.get("tipo_questao") or "").strip() or None,
    )
    total_questoes = (
        db.query(BancoQuestao)
        .filter(BancoQuestao.autor_usuario_id == current_user.id, BancoQuestao.ativo.is_(True))
        .count()
    )
    questoes_em_provas = (
        db.query(func.count(func.distinct(Questao.banco_questao_id)))
        .join(Avaliacao, Avaliacao.id == Questao.avaliacao_id)
        .filter(Avaliacao.criado_por_usuario_id == current_user.id, Questao.banco_questao_id.isnot(None))
        .scalar()
        or 0
    )
    return templates.TemplateResponse(
        request,
        "professor/banco_questoes_list.html",
        {
            "request": request,
            "current_user": current_user,
            "questoes": questoes,
            "stats": {
                "total_questoes": total_questoes,
                "questoes_em_provas": questoes_em_provas,
                "total_filtrado": len(questoes),
            },
            **_curricular_context(db),
            "flash_ok": (request.query_params.get("ok") or "").strip(),
            "flash_err": (request.query_params.get("err") or "").strip(),
            "filters": {
                "q": (request.query_params.get("q") or "").strip(),
                "curso_id": _optional_int(request.query_params.get("curso_id")),
                "ano_escolar": _optional_int(request.query_params.get("ano_escolar")),
                "descritor_id": _optional_int(request.query_params.get("descritor_id")),
                "conteudo": (request.query_params.get("conteudo") or "").strip(),
                "tipo_questao": (request.query_params.get("tipo_questao") or "").strip(),
            },
        },
    )


@router.get("/professor/banco-questoes/nova")
def professor_banco_questoes_nova(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.PROFESSOR)),
):
    return templates.TemplateResponse(
        request,
        "professor/banco_questao_form.html",
        {
            "request": request,
            "current_user": current_user,
            "questao": None,
            "form_action": "/professor/banco-questoes",
            **_curricular_context(db),
            "flash_err": (request.query_params.get("err") or "").strip(),
        },
    )


@router.get("/professor/banco-questoes/{id}/editar")
def professor_banco_questoes_editar(
    request: Request,
    id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.PROFESSOR)),
):
    questao = AvaliacaoService().get_banco_questao(db, id)
    if not questao or questao.autor_usuario_id != current_user.id:
        return _redirect_with_message("/professor/banco-questoes?err=Quest%C3%A3o%20n%C3%A3o%20encontrada.", status_code=302)
    return templates.TemplateResponse(
        request,
        "professor/banco_questao_form.html",
        {
            "request": request,
            "current_user": current_user,
            "questao": questao,
            "form_action": f"/professor/banco-questoes/{questao.id}/editar",
            **_curricular_context(db),
            "flash_err": (request.query_params.get("err") or "").strip(),
        },
    )


@router.post("/professor/banco-questoes")
@router.post("/professor/avaliacao-institucional/banco-questoes")
async def professor_banco_questoes_criar(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.PROFESSOR)),
):
    form = await request.form()
    enunciado = (form.get("enunciado") or "").strip()
    if not enunciado:
        return _redirect_with_message("/professor/banco-questoes/nova?err=Informe%20o%20enunciado.")
    questao = AvaliacaoService().criar_banco_questao(
        db,
        autor_usuario_id=current_user.id,
        curso_id=_optional_int(form.get("curso_id")),
        ano_escolar=_optional_int(form.get("ano_escolar")),
        descritor_id=_optional_int(form.get("descritor_id")),
        conteudo=(form.get("conteudo") or "").strip() or None,
        tipo_questao=(form.get("tipo_questao") or "").strip() or "multipla_escolha",
        enunciado=enunciado,
        gabarito=(form.get("gabarito") or "").strip(),
        origem=OrigemBancoQuestao.MANUAL,
        alternativa_a=(form.get("alternativa_a") or "").strip(),
        alternativa_b=(form.get("alternativa_b") or "").strip(),
        alternativa_c=(form.get("alternativa_c") or "").strip(),
        alternativa_d=(form.get("alternativa_d") or "").strip(),
        alternativa_e=(form.get("alternativa_e") or "").strip(),
        codigo_referencia=(form.get("codigo_referencia") or "").strip() or None,
        observacoes=(form.get("observacoes") or "").strip() or None,
    )
    AuditService.log(
        db,
        usuario_id=current_user.id,
        acao="questao_banco_professor_criada",
        categoria="avaliacao_desempenho",
        entidade="banco_questoes",
        entidade_id=questao.id,
        detalhes="Professor adicionou item ao banco de questões.",
        ip=request.client.host if request.client else None,
    )
    return _redirect_with_message("/professor/banco-questoes?ok=banco")


@router.post("/professor/banco-questoes/{id}/editar")
async def professor_banco_questoes_atualizar(
    request: Request,
    id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.PROFESSOR)),
):
    questao = AvaliacaoService().get_banco_questao(db, id)
    if not questao or questao.autor_usuario_id != current_user.id:
        return _redirect_with_message("/professor/banco-questoes?err=Quest%C3%A3o%20n%C3%A3o%20encontrada.")
    form = await request.form()
    enunciado = (form.get("enunciado") or "").strip()
    if not enunciado:
        return _redirect_with_message(f"/professor/banco-questoes/{id}/editar?err=Informe%20o%20enunciado.")
    atualizada = AvaliacaoService().atualizar_banco_questao(
        db,
        banco_questao_id=id,
        curso_id=_optional_int(form.get("curso_id")),
        ano_escolar=_optional_int(form.get("ano_escolar")),
        descritor_id=_optional_int(form.get("descritor_id")),
        conteudo=(form.get("conteudo") or "").strip() or None,
        tipo_questao=(form.get("tipo_questao") or "").strip() or "multipla_escolha",
        enunciado=enunciado,
        gabarito=(form.get("gabarito") or "").strip(),
        alternativa_a=(form.get("alternativa_a") or "").strip(),
        alternativa_b=(form.get("alternativa_b") or "").strip(),
        alternativa_c=(form.get("alternativa_c") or "").strip(),
        alternativa_d=(form.get("alternativa_d") or "").strip(),
        alternativa_e=(form.get("alternativa_e") or "").strip(),
        observacoes=(form.get("observacoes") or "").strip() or None,
    )
    if not atualizada:
        return _redirect_with_message("/professor/banco-questoes?err=Quest%C3%A3o%20n%C3%A3o%20foi%20atualizada.")
    AuditService.log(
        db,
        usuario_id=current_user.id,
        acao="questao_banco_professor_atualizada",
        categoria="avaliacao_desempenho",
        entidade="banco_questoes",
        entidade_id=atualizada.id,
        detalhes="Professor atualizou item do banco de questões.",
        ip=request.client.host if request.client else None,
    )
    return _redirect_with_message("/professor/banco-questoes?ok=editado")


@router.post("/professor/banco-questoes/{id}/deletar")
def professor_banco_questoes_deletar(
    request: Request,
    id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.PROFESSOR)),
):
    questao = AvaliacaoService().get_banco_questao(db, id)
    if not questao or questao.autor_usuario_id != current_user.id:
        return _redirect_with_message("/professor/banco-questoes?err=Quest%C3%A3o%20n%C3%A3o%20encontrada.")
    AvaliacaoService().excluir_banco_questao(db, id)
    AuditService.log(
        db,
        usuario_id=current_user.id,
        acao="questao_banco_professor_excluida",
        categoria="avaliacao_desempenho",
        entidade="banco_questoes",
        entidade_id=id,
        detalhes="Professor excluiu item do banco de questões.",
        ip=request.client.host if request.client else None,
    )
    return _redirect_with_message("/professor/banco-questoes?ok=deletado")


@router.get("/professor/provas")
def professor_provas(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.PROFESSOR)),
):
    redirect = _maybe_return_redirect(current_user)
    if redirect:
        return redirect
    termo = (request.query_params.get("q") or "").strip()
    curso_id = _optional_int(request.query_params.get("curso_id"))
    trilha_id = _optional_int(request.query_params.get("trilha_id"))
    avaliacoes_query = _professor_avaliacoes_query(db, current_user.id)
    if termo:
        termo_like = f"%{termo}%"
        avaliacoes_query = avaliacoes_query.filter(Avaliacao.titulo.ilike(termo_like))
    if curso_id:
        avaliacoes_query = avaliacoes_query.filter(Avaliacao.curso_id == curso_id)
    if trilha_id:
        avaliacoes_query = avaliacoes_query.filter(Avaliacao.trilha_id == trilha_id)
    avaliacoes = avaliacoes_query.all()
    return templates.TemplateResponse(
        request,
        "professor/provas_list.html",
        {
            "request": request,
            "current_user": current_user,
            "avaliacoes": avaliacoes,
            "stats": {
                "total_provas": len(avaliacoes),
                "com_trilha": sum(1 for item in avaliacoes if item.trilha_id),
                "total_aplicacoes": sum(len(item.aplicacoes or []) for item in avaliacoes),
            },
            **_curricular_context(db),
            "trilhas": _professor_trilhas(db, current_user.id),
            "flash_ok": (request.query_params.get("ok") or "").strip(),
            "flash_err": (request.query_params.get("err") or "").strip(),
            "filters": {"q": termo, "curso_id": curso_id, "trilha_id": trilha_id},
        },
    )


@router.get("/professor/provas/nova")
def professor_provas_nova(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.PROFESSOR)),
):
    redirect = _maybe_return_redirect(current_user)
    if redirect:
        return redirect
    service = AvaliacaoService()
    questoes = service.listar_banco_questoes(
        db,
        autor_usuario_id=current_user.id,
        curso_id=_optional_int(request.query_params.get("curso_id")),
        ano_escolar=_optional_int(request.query_params.get("ano_escolar")),
        descritor_id=_optional_int(request.query_params.get("descritor_id")),
        conteudo=(request.query_params.get("conteudo") or "").strip() or None,
        termo=(request.query_params.get("q") or "").strip() or None,
        tipo_questao=(request.query_params.get("tipo_questao") or "").strip() or None,
    )
    return templates.TemplateResponse(
        request,
        "professor/prova_form.html",
        {
            "request": request,
            "current_user": current_user,
            "prova": None,
            "questoes": questoes,
            "selected_banco_questao_ids": [],
            "form_action": "/professor/provas",
            **_curricular_context(db),
            "trilhas": _professor_trilhas(db, current_user.id),
            "filters": {
                "q": (request.query_params.get("q") or "").strip(),
                "curso_id": _optional_int(request.query_params.get("curso_id")),
                "ano_escolar": _optional_int(request.query_params.get("ano_escolar")),
                "descritor_id": _optional_int(request.query_params.get("descritor_id")),
                "conteudo": (request.query_params.get("conteudo") or "").strip(),
                "tipo_questao": (request.query_params.get("tipo_questao") or "").strip(),
            },
            "flash_err": (request.query_params.get("err") or "").strip(),
        },
    )


@router.get("/professor/provas/{id}/editar")
def professor_provas_editar(
    request: Request,
    id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.PROFESSOR)),
):
    redirect = _maybe_return_redirect(current_user)
    if redirect:
        return redirect
    prova = _professor_get_avaliacao(db, current_user.id, id)
    if not prova:
        return _redirect_with_message("/professor/provas?err=Prova%20n%C3%A3o%20encontrada.", status_code=302)
    service = AvaliacaoService()
    questoes = service.listar_banco_questoes(
        db,
        autor_usuario_id=current_user.id,
        curso_id=_optional_int(request.query_params.get("curso_id")),
        ano_escolar=_optional_int(request.query_params.get("ano_escolar")),
        descritor_id=_optional_int(request.query_params.get("descritor_id")),
        conteudo=(request.query_params.get("conteudo") or "").strip() or None,
        termo=(request.query_params.get("q") or "").strip() or None,
        tipo_questao=(request.query_params.get("tipo_questao") or "").strip() or None,
    )
    return templates.TemplateResponse(
        request,
        "professor/prova_form.html",
        {
            "request": request,
            "current_user": current_user,
            "prova": prova,
            "questoes": questoes,
            "selected_banco_questao_ids": [q.banco_questao_id for q in prova.questoes if q.banco_questao_id],
            "form_action": f"/professor/provas/{prova.id}/editar",
            **_curricular_context(db),
            "trilhas": _professor_trilhas(db, current_user.id),
            "filters": {
                "q": (request.query_params.get("q") or "").strip(),
                "curso_id": _optional_int(request.query_params.get("curso_id")),
                "ano_escolar": _optional_int(request.query_params.get("ano_escolar")),
                "descritor_id": _optional_int(request.query_params.get("descritor_id")),
                "conteudo": (request.query_params.get("conteudo") or "").strip(),
                "tipo_questao": (request.query_params.get("tipo_questao") or "").strip(),
            },
            "flash_err": (request.query_params.get("err") or "").strip(),
        },
    )


@router.post("/professor/provas")
@router.post("/professor/avaliacao-institucional/provas")
async def professor_provas_criar(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.PROFESSOR)),
):
    redirect = _maybe_return_redirect(current_user)
    if redirect:
        return redirect
    form = await request.form()
    titulo = (form.get("titulo") or "").strip()
    banco_questao_ids = [
        int(item)
        for item in form.getlist("banco_questao_ids")
        if str(item or "").strip().isdigit()
    ]
    if not titulo:
        return _redirect_with_message("/professor/provas/nova?err=Informe%20o%20t%C3%ADtulo%20da%20prova.")
    if not banco_questao_ids:
        return _redirect_with_message("/professor/provas/nova?err=Selecione%20ao%20menos%20uma%20quest%C3%A3o.")
    trilha_id = _optional_int(form.get("trilha_id"))
    trilha = AvaliacaoService().get_trilha(db, trilha_id)
    try:
        avaliacao = AvaliacaoService().criar_prova_com_questoes(
            db,
            titulo=titulo,
            descricao=(form.get("descricao") or "").strip(),
            codigo=None,
            ano_letivo=(form.get("ano_letivo") or "").strip() or None,
            curso_id=_optional_int(form.get("curso_id")) or (trilha.curso_id if trilha else None),
            trilha_id=trilha_id,
            ano_escolar=_optional_int(form.get("ano_escolar")) or (trilha.ano_escolar if trilha else None),
            criado_por_usuario_id=current_user.id,
            escopo="turma",
            banco_questao_ids=banco_questao_ids,
        )
    except ValueError as exc:
        return _redirect_with_message(f"/professor/provas/nova?err={str(exc).replace(' ', '%20')}")
    AuditService.log(
        db,
        usuario_id=current_user.id,
        acao="prova_professor_criada",
        categoria="avaliacao_desempenho",
        entidade="avaliacoes",
        entidade_id=avaliacao.id,
        detalhes="Professor criou nova prova com itens selecionados do banco.",
        ip=request.client.host if request.client else None,
    )
    return _redirect_with_message(f"/professor/provas?ok=prova&avaliacao_id={avaliacao.id}")


@router.post("/professor/provas/{id}/editar")
async def professor_provas_atualizar(
    request: Request,
    id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.PROFESSOR)),
):
    redirect = _maybe_return_redirect(current_user)
    if redirect:
        return redirect
    prova = _professor_get_avaliacao(db, current_user.id, id)
    if not prova:
        return _redirect_with_message("/professor/provas?err=Prova%20n%C3%A3o%20encontrada.")
    form = await request.form()
    titulo = (form.get("titulo") or "").strip()
    banco_questao_ids = [
        int(item)
        for item in form.getlist("banco_questao_ids")
        if str(item or "").strip().isdigit()
    ]
    if not titulo:
        return _redirect_with_message(f"/professor/provas/{id}/editar?err=Informe%20o%20t%C3%ADtulo%20da%20prova.")
    if not banco_questao_ids:
        return _redirect_with_message(f"/professor/provas/{id}/editar?err=Selecione%20ao%20menos%20uma%20quest%C3%A3o.")
    trilha_id = _optional_int(form.get("trilha_id"))
    trilha = AvaliacaoService().get_trilha(db, trilha_id)
    try:
        atualizada = AvaliacaoService().atualizar_prova_com_questoes(
            db,
            avaliacao_id=id,
            titulo=titulo,
            descricao=(form.get("descricao") or "").strip(),
            ano_letivo=(form.get("ano_letivo") or "").strip() or None,
            curso_id=_optional_int(form.get("curso_id")) or (trilha.curso_id if trilha else None),
            trilha_id=trilha_id,
            ano_escolar=_optional_int(form.get("ano_escolar")) or (trilha.ano_escolar if trilha else None),
            banco_questao_ids=banco_questao_ids,
        )
    except ValueError as exc:
        return _redirect_with_message(f"/professor/provas/{id}/editar?err={str(exc).replace(' ', '%20')}")
    AuditService.log(
        db,
        usuario_id=current_user.id,
        acao="prova_professor_atualizada",
        categoria="avaliacao_desempenho",
        entidade="avaliacoes",
        entidade_id=atualizada.id,
        detalhes="Professor atualizou prova e seleção de questões.",
        ip=request.client.host if request.client else None,
    )
    return _redirect_with_message(f"/professor/provas?ok=editado&avaliacao_id={atualizada.id}")


@router.post("/professor/provas/{id}/deletar")
def professor_provas_deletar(
    request: Request,
    id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.PROFESSOR)),
):
    redirect = _maybe_return_redirect(current_user)
    if redirect:
        return redirect
    prova = _professor_get_avaliacao(db, current_user.id, id)
    if not prova:
        return _redirect_with_message("/professor/provas?err=Prova%20n%C3%A3o%20encontrada.")
    try:
        ok = AvaliacaoService().excluir_prova(db, id)
    except ValueError as exc:
        return _redirect_with_message(f"/professor/provas?err={str(exc).replace(' ', '%20')}")
    if not ok:
        return _redirect_with_message("/professor/provas?err=N%C3%A3o%20foi%20poss%C3%ADvel%20excluir%20a%20prova.")
    AuditService.log(
        db,
        usuario_id=current_user.id,
        acao="prova_professor_excluida",
        categoria="avaliacao_desempenho",
        entidade="avaliacoes",
        entidade_id=id,
        detalhes="Professor excluiu prova sem aplicações.",
        ip=request.client.host if request.client else None,
    )
    return _redirect_with_message("/professor/provas?ok=deletado")


@router.post("/professor/avaliacao-institucional/questoes")
async def professor_provas_anexar_questao_legado(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.PROFESSOR)),
):
    form = await request.form()
    avaliacao_id = _optional_int(form.get("avaliacao_id"))
    banco_questao_id = _optional_int(form.get("banco_questao_id"))
    if not avaliacao_id or not banco_questao_id:
        return _redirect_with_message("/professor/provas?err=Selecione%20a%20prova%20e%20a%20quest%C3%A3o.")
    questao = AvaliacaoService().anexar_questao_banco(
        db,
        avaliacao_id=avaliacao_id,
        banco_questao_id=banco_questao_id,
        numero=_optional_int(form.get("numero")),
        peso=float(form.get("peso") or 1.0),
    )
    AuditService.log(
        db,
        usuario_id=current_user.id,
        acao="questao_professor_anexada",
        categoria="avaliacao_desempenho",
        entidade="questoes_prova",
        entidade_id=questao.id,
        detalhes="Professor anexou item do banco a uma prova existente.",
        ip=request.client.host if request.client else None,
    )
    return _redirect_with_message(f"/professor/provas?ok=questao&avaliacao_id={avaliacao_id}")


@router.get("/professor/aplicacoes-prova")
def professor_aplicacoes_prova(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.PROFESSOR)),
):
    redirect = _maybe_return_redirect(current_user)
    if redirect:
        return redirect
    avaliacao_id = _optional_int(request.query_params.get("avaliacao_id"))
    status = (request.query_params.get("status") or "").strip()
    avaliacoes = _professor_avaliacoes_query(db, current_user.id).all()
    aplicacoes_query = (
        db.query(AplicacaoProva)
        .options(
            joinedload(AplicacaoProva.participacoes),
            joinedload(AplicacaoProva.avaliacao).joinedload(Avaliacao.questoes),
            joinedload(AplicacaoProva.turma),
        )
        .join(Avaliacao, Avaliacao.id == AplicacaoProva.avaliacao_id)
        .filter(Avaliacao.criado_por_usuario_id == current_user.id)
        .order_by(AplicacaoProva.id.desc())
    )
    if avaliacao_id:
        aplicacoes_query = aplicacoes_query.filter(AplicacaoProva.avaliacao_id == avaliacao_id)
    if status:
        aplicacoes_query = aplicacoes_query.filter(AplicacaoProva.status == status)
    aplicacoes = aplicacoes_query.all()
    aplicacao_cards = [
        {
            "item": item,
            "questoes_total": len(getattr(item.avaliacao, "questoes", None) or []),
            "participantes_total": len(item.participacoes or []),
            "respostas_total": _respostas_count_aplicacao(item),
        }
        for item in aplicacoes
    ]
    return templates.TemplateResponse(
        request,
        "professor/aplicacoes_prova.html",
        {
            "request": request,
            "current_user": current_user,
            "avaliacoes": avaliacoes,
            "aplicacoes": aplicacoes,
            "aplicacao_cards": aplicacao_cards,
            "turmas_professor": _professor_turmas(db, current_user.id),
            "stats": {
                "total_aplicacoes": len(aplicacoes),
                "planejadas": sum(1 for item in aplicacoes if str(item.status) == "StatusAplicacaoProva.PLANEJADA" or getattr(item.status, "value", item.status) == "planejada"),
                "corrigidas": sum(1 for item in aplicacoes if getattr(item.status, "value", item.status) == "corrigida"),
            },
            "filters": {"avaliacao_id": avaliacao_id, "status": status},
            "flash_ok": (request.query_params.get("ok") or "").strip(),
            "flash_err": (request.query_params.get("err") or "").strip(),
        },
    )


@router.get("/professor/aplicacoes-prova/{aplicacao_id}")
def professor_aplicacao_resultados(
    request: Request,
    aplicacao_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.PROFESSOR)),
):
    redirect = _maybe_return_redirect(current_user)
    if redirect:
        return redirect
    aplicacao = (
        db.query(AplicacaoProva)
        .options(
            joinedload(AplicacaoProva.participacoes),
            joinedload(AplicacaoProva.avaliacao).joinedload(Avaliacao.questoes),
            joinedload(AplicacaoProva.turma),
        )
        .join(Avaliacao, Avaliacao.id == AplicacaoProva.avaliacao_id)
        .filter(
            AplicacaoProva.id == aplicacao_id,
            Avaliacao.criado_por_usuario_id == current_user.id,
        )
        .first()
    )
    if not aplicacao:
        return _redirect_with_message("/professor/aplicacoes-prova?err=Aplica%C3%A7%C3%A3o%20n%C3%A3o%20encontrada.", status_code=302)

    resumo = AvaliacaoService().resumo_avaliacao_objetiva(db, aplicacao_id=aplicacao.id)
    participantes_total = len(aplicacao.participacoes or [])
    respostas_total = _respostas_count_aplicacao(aplicacao)
    return templates.TemplateResponse(
        request,
        "professor/aplicacao_resultados.html",
        {
            "request": request,
            "current_user": current_user,
            "aplicacao": aplicacao,
            "avaliacao": aplicacao.avaliacao,
            "resumo": resumo,
            "modo": "aplicacao",
            "participantes_total": participantes_total,
            "respostas_total": respostas_total,
            "questoes_total": len(getattr(aplicacao.avaliacao, "questoes", None) or []),
        },
    )


@router.get("/professor/provas/{avaliacao_id}/visualizar")
def professor_prova_visualizar(
    request: Request,
    avaliacao_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.PROFESSOR)),
):
    redirect = _maybe_return_redirect(current_user)
    if redirect:
        return redirect
    prova = (
        db.query(Avaliacao)
        .options(
            joinedload(Avaliacao.questoes),
            joinedload(Avaliacao.trilha),
            joinedload(Avaliacao.curso),
        )
        .filter(Avaliacao.id == avaliacao_id, Avaliacao.criado_por_usuario_id == current_user.id)
        .first()
    )
    if not prova:
        return _redirect_with_message("/professor/provas?err=Prova%20n%C3%A3o%20encontrada.", status_code=302)
    questoes = sorted(
        list(getattr(prova, "questoes", []) or []),
        key=lambda item: ((item.numero if item.numero is not None else 9999), item.id),
    )
    return templates.TemplateResponse(
        request,
        "professor/prova_visualizar.html",
        {
            "request": request,
            "current_user": current_user,
            "avaliacao": prova,
            "questoes": questoes,
        },
    )


@router.get("/professor/provas/{avaliacao_id}/resultados")
def professor_prova_resultados(
    request: Request,
    avaliacao_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.PROFESSOR)),
):
    redirect = _maybe_return_redirect(current_user)
    if redirect:
        return redirect
    prova = _professor_get_avaliacao(db, current_user.id, avaliacao_id)
    if not prova:
        return _redirect_with_message("/professor/provas?err=Prova%20n%C3%A3o%20encontrada.", status_code=302)

    resumo = AvaliacaoService().resumo_avaliacao_objetiva(db, avaliacao_id=prova.id)
    por_aluno = resumo.get("por_aluno") or []
    respostas_total = sum(1 for row in por_aluno if int(row.get("respostas") or 0) > 0)
    return templates.TemplateResponse(
        request,
        "professor/aplicacao_resultados.html",
        {
            "request": request,
            "current_user": current_user,
            "aplicacao": None,
            "avaliacao": prova,
            "resumo": resumo,
            "modo": "prova",
            "participantes_total": len(por_aluno),
            "respostas_total": respostas_total,
            "questoes_total": len(getattr(prova, "questoes", None) or []),
        },
    )


@router.post("/professor/aplicacoes-prova")
@router.post("/professor/avaliacao-institucional/aplicacoes")
async def professor_aplicacoes_criar(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.PROFESSOR)),
):
    form = await request.form()
    avaliacao_id = _optional_int(form.get("avaliacao_id"))
    turma_id = _optional_int(form.get("turma_id"))
    if not avaliacao_id or not turma_id:
        return _redirect_with_message("/professor/aplicacoes-prova?err=Selecione%20a%20prova%20e%20a%20turma.")
    data_aplicacao = parse_data_aplicacao_form(form.get("data_aplicacao"))
    aplicacao = AvaliacaoService().criar_aplicacao_prova(
        db,
        avaliacao_id=avaliacao_id,
        titulo=(form.get("titulo") or "").strip() or None,
        escopo="turma",
        turma_id=turma_id,
        ano_letivo=(form.get("ano_letivo") or "").strip() or None,
        periodo_referencia=(form.get("periodo_referencia") or "").strip() or None,
        data_aplicacao=data_aplicacao,
        observacoes=(form.get("observacoes") or "").strip() or None,
        criado_por_usuario_id=current_user.id,
    )
    AuditService.log(
        db,
        usuario_id=current_user.id,
        acao="aplicacao_professor_criada",
        categoria="avaliacao_desempenho",
        entidade="aplicacoes_prova",
        entidade_id=aplicacao.id,
        detalhes="Professor criou aplicação de prova por turma.",
        ip=request.client.host if request.client else None,
    )
    return _redirect_with_message(
        f"/professor/aplicacoes-prova?ok=aplicacao&avaliacao_id={avaliacao_id}&aplicacao_id={aplicacao.id}"
    )


@router.get("/professor/aplicacoes-prova/{aplicacao_id}/editar")
def professor_aplicacoes_editar(
    request: Request,
    aplicacao_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.PROFESSOR)),
):
    redirect = _maybe_return_redirect(current_user)
    if redirect:
        return redirect
    aplicacao = (
        db.query(AplicacaoProva)
        .join(Avaliacao, Avaliacao.id == AplicacaoProva.avaliacao_id)
        .filter(
            AplicacaoProva.id == aplicacao_id,
            Avaliacao.criado_por_usuario_id == current_user.id,
        )
        .first()
    )
    if not aplicacao:
        return _redirect_with_message("/professor/aplicacoes-prova?err=Aplica%C3%A7%C3%A3o%20n%C3%A3o%20encontrada.", status_code=302)
    return templates.TemplateResponse(
        request,
        "professor/aplicacao_form.html",
        {
            "request": request,
            "current_user": current_user,
            "aplicacao": aplicacao,
            "form_action": f"/professor/aplicacoes-prova/{aplicacao.id}/editar",
            "flash_err": (request.query_params.get("err") or "").strip(),
        },
    )


@router.post("/professor/aplicacoes-prova/{aplicacao_id}/editar")
async def professor_aplicacoes_atualizar(
    request: Request,
    aplicacao_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.PROFESSOR)),
):
    redirect = _maybe_return_redirect(current_user)
    if redirect:
        return redirect
    aplicacao = (
        db.query(AplicacaoProva)
        .join(Avaliacao, Avaliacao.id == AplicacaoProva.avaliacao_id)
        .filter(
            AplicacaoProva.id == aplicacao_id,
            Avaliacao.criado_por_usuario_id == current_user.id,
        )
        .first()
    )
    if not aplicacao:
        return _redirect_with_message("/professor/aplicacoes-prova?err=Aplica%C3%A7%C3%A3o%20n%C3%A3o%20encontrada.")
    form = await request.form()
    try:
        status_raw = (form.get("status") or "").strip() or None
        data_aplicacao = parse_data_aplicacao_form(form.get("data_aplicacao"))
        atualizada = AvaliacaoService().atualizar_aplicacao_prova(
            db,
            aplicacao_id=aplicacao_id,
            titulo=(form.get("titulo") or "").strip() or None,
            ano_letivo=(form.get("ano_letivo") or "").strip() or None,
            periodo_referencia=(form.get("periodo_referencia") or "").strip() or None,
            data_aplicacao=data_aplicacao,
            observacoes=(form.get("observacoes") or "").strip() or None,
            status=status_raw,
        )
    except ValueError as exc:
        return _redirect_with_message(
            f"/professor/aplicacoes-prova/{aplicacao_id}/editar?err={str(exc).replace(' ', '%20')}"
        )
    AuditService.log(
        db,
        usuario_id=current_user.id,
        acao="aplicacao_professor_atualizada",
        categoria="avaliacao_desempenho",
        entidade="aplicacoes_prova",
        entidade_id=atualizada.id,
        detalhes="Professor atualizou dados da aplicação.",
        ip=request.client.host if request.client else None,
    )
    return _redirect_with_message(f"/professor/aplicacoes-prova?ok=editado&aplicacao_id={atualizada.id}")


@router.post("/professor/aplicacoes-prova/{aplicacao_id}/deletar")
def professor_aplicacoes_deletar(
    request: Request,
    aplicacao_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.PROFESSOR)),
):
    redirect = _maybe_return_redirect(current_user)
    if redirect:
        return redirect
    aplicacao = (
        db.query(AplicacaoProva)
        .join(Avaliacao, Avaliacao.id == AplicacaoProva.avaliacao_id)
        .filter(
            AplicacaoProva.id == aplicacao_id,
            Avaliacao.criado_por_usuario_id == current_user.id,
        )
        .first()
    )
    if not aplicacao:
        return _redirect_with_message("/professor/aplicacoes-prova?err=Aplica%C3%A7%C3%A3o%20n%C3%A3o%20encontrada.")
    ok = AvaliacaoService().excluir_aplicacao_prova(db, aplicacao_id)
    if not ok:
        return _redirect_with_message("/professor/aplicacoes-prova?err=N%C3%A3o%20foi%20poss%C3%ADvel%20excluir%20a%20aplica%C3%A7%C3%A3o.")
    AuditService.log(
        db,
        usuario_id=current_user.id,
        acao="aplicacao_professor_excluida",
        categoria="avaliacao_desempenho",
        entidade="aplicacoes_prova",
        entidade_id=aplicacao_id,
        detalhes="Professor excluiu aplicação de prova.",
        ip=request.client.host if request.client else None,
    )
    return _redirect_with_message("/professor/aplicacoes-prova?ok=deletado")


@router.get("/professor/formacao-bncc")
def professor_formacao_bncc(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.PROFESSOR)),
):
    from app.services import moodle_assignment_service as moodle_assign_svc

    participacoes = (
        db.query(ParticipanteTurmaFormacaoBNCC)
        .filter(ParticipanteTurmaFormacaoBNCC.usuario_id == current_user.id)
        .order_by(ParticipanteTurmaFormacaoBNCC.id.desc())
        .all()
    )
    moodle_cursos = moodle_assign_svc.list_assignments_for_professor(db, current_user.id)
    return templates.TemplateResponse(
        request,
        "professor/formacao_bncc.html",
        {
            "request": request,
            "current_user": current_user,
            "participacoes": participacoes,
            "moodle_cursos": moodle_cursos,
        },
    )
