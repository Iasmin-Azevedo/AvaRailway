from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from typing import List, Optional
import os
import logging
from datetime import datetime

from app.core.database import get_db
from app.core.dependencies import get_current_user, get_current_user_optional
from app.models.user import Usuario
from app.models.aluno import Aluno, PontuacaoGamificacao
from app.models.h5p import AtividadeH5P
from app.models.professor_h5p import ProfessorAtividadeH5P, ProfessorProgressoH5P
from app.repositories.h5p_repository import AtividadeH5PRepository, ProgressoH5PRepository
from app.repositories.gestao_repository import TrilhaRepository
from app.schemas.h5p_schema import AtividadeH5PResponse, ProgressoH5PResponse
from app.core.config import settings
from jose import jwt, JWTError
from app.core.gamification_rules import calculate_xp_gain, get_level_progress

router = APIRouter()
logger = logging.getLogger("ava_mj_backend.h5p")


def _get_aluno_id(db: Session, user: Usuario) -> Optional[int]:
    aluno = db.query(Aluno).filter(Aluno.usuario_id == user.id).first()
    return aluno.id if aluno else None


def _ensure_aluno_can_access_atividade(db: Session, user: Usuario, atividade: AtividadeH5P) -> None:
    """Garante que aluno só acesse atividade do próprio ano escolar."""
    aluno = db.query(Aluno).filter(Aluno.usuario_id == user.id).first()
    if not aluno:
        return
    trilha = TrilhaRepository().get(db, atividade.trilha_id) if atividade.trilha_id else None
    if trilha and trilha.ano_escolar and trilha.ano_escolar != aluno.ano_escolar:
        raise HTTPException(403, "Você não pode acessar atividade de outro ano escolar")


def _resolve_aluno_id_for_conclusao(
    request: Request,
    db: Session,
    atividade_id: int,
    current_user: Usuario | None,
) -> int:
    if current_user:
        aluno_id = _get_aluno_id(db, current_user)
        if aluno_id:
            return aluno_id

    token = request.headers.get("X-H5P-Completion-Token")
    if not token:
        raise HTTPException(401, "Não autenticado para concluir atividade")
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        if payload.get("scope") != "h5p_complete":
            raise HTTPException(401, "Token de conclusão inválido")
        if int(payload.get("atividade_id", -1)) != int(atividade_id):
            raise HTTPException(401, "Token de conclusão não corresponde à atividade")
        aluno_id = int(payload.get("aluno_id"))
    except (JWTError, ValueError, TypeError):
        raise HTTPException(401, "Token de conclusão inválido ou expirado")

    aluno = db.query(Aluno).filter(Aluno.id == aluno_id).first()
    if not aluno:
        raise HTTPException(401, "Aluno inválido para conclusão")
    return aluno_id


def _parse_score_from_payload(payload: dict) -> Optional[float]:
    """Aceita formatos variados de score vindos do H5P e normaliza para 0..100."""
    raw_score = payload.get("score")
    if raw_score is None and isinstance(payload.get("result"), dict):
        result = payload["result"]
        if isinstance(result.get("score"), dict):
            raw = result["score"].get("raw")
            max_score = result["score"].get("max")
            if raw is not None and max_score not in (None, 0):
                try:
                    return max(0.0, min(100.0, (float(raw) / float(max_score)) * 100.0))
                except Exception:
                    pass
        raw_score = result.get("score")
        if raw_score is None:
            scaled = result.get("score_scaled")
            if scaled is not None:
                raw_score = scaled

    if raw_score is None and isinstance(payload.get("statement"), dict):
        statement = payload["statement"]
        result = statement.get("result") if isinstance(statement.get("result"), dict) else {}
        score_obj = result.get("score") if isinstance(result.get("score"), dict) else {}
        raw = score_obj.get("raw")
        max_score = score_obj.get("max")
        scaled = score_obj.get("scaled")
        if raw is not None and max_score not in (None, 0):
            try:
                return max(0.0, min(100.0, (float(raw) / float(max_score)) * 100.0))
            except Exception:
                pass
        if scaled is not None:
            raw_score = scaled

    if raw_score is None:
        return None

    try:
        score = float(raw_score)
    except Exception:
        return None

    # Alguns players mandam score em escala 0..1.
    if 0.0 <= score <= 1.0:
        score = score * 100.0

    return max(0.0, min(100.0, score))


@router.get("/atividades", response_model=List[AtividadeH5PResponse])
def listar_atividades(
    trilha_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Lista atividades H5P (opcionalmente filtradas por trilha)."""
    atividades = AtividadeH5PRepository().listar(db, trilha_id=trilha_id, ativo_only=True)
    aluno = db.query(Aluno).filter(Aluno.usuario_id == current_user.id).first()
    if not aluno:
        return atividades
    trilhas_ano = {
        t.id
        for t in TrilhaRepository().listar(db, ano_escolar=aluno.ano_escolar)
    }
    return [a for a in atividades if a.trilha_id in trilhas_ano]


@router.get("/atividades/{id}", response_model=AtividadeH5PResponse)
def obter_atividade(
    id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Retorna metadados da atividade para exibição no player."""
    obj = AtividadeH5PRepository().get(db, id)
    if not obj or not obj.ativo:
        raise HTTPException(404, "Atividade não encontrada")
    _ensure_aluno_can_access_atividade(db, current_user, obj)
    return obj


@router.get("/content/{id}/content.json")
def servir_conteudo_h5p(
    id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Serve o JSON do conteúdo H5P (protegido por autenticação)."""
    obj = AtividadeH5PRepository().get(db, id)
    if not obj or not obj.ativo:
        raise HTTPException(404, "Atividade não encontrada")
    _ensure_aluno_can_access_atividade(db, current_user, obj)
    path = obj.path_ou_json
    if not path:
        raise HTTPException(404, "Arquivo de conteúdo não configurado")
    if not os.path.isabs(path):
        path = os.path.join(settings.H5P_CONTENT_DIR, path)
    if os.path.isdir(path):
        path = os.path.join(path, "content", "content.json")
    if not os.path.isfile(path):
        raise HTTPException(404, "Arquivo de conteúdo não encontrado")
    return FileResponse(path, media_type="application/json")


@router.post("/atividades/{id}/concluir", response_model=ProgressoH5PResponse)
async def concluir_atividade(
    id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario | None = Depends(get_current_user_optional),
):
    """Registra conclusão e score da atividade para o aluno logado."""
    obj = AtividadeH5PRepository().get(db, id)
    if not obj:
        raise HTTPException(404, "Atividade não encontrada")
    aluno_id = _resolve_aluno_id_for_conclusao(request, db, id, current_user)

    # Quando houver usuário autenticado por sessão/header, mantém validação de acesso por ano
    if current_user:
        _ensure_aluno_can_access_atividade(db, current_user, obj)
    else:
        aluno = db.query(Aluno).filter(Aluno.id == aluno_id).first()
        trilha = TrilhaRepository().get(db, obj.trilha_id) if obj.trilha_id else None
        if aluno and trilha and trilha.ano_escolar and trilha.ano_escolar != aluno.ano_escolar:
            raise HTTPException(403, "Você não pode acessar atividade de outro ano escolar")

    score = None
    try:
        payload = await request.json()
    except Exception:
        payload = None
        try:
            form = await request.form()
            payload = dict(form)
        except Exception:
            payload = None

    if isinstance(payload, dict):
        score = _parse_score_from_payload(payload)

    logger.info(
        "H5P concluir recebido: atividade_id=%s aluno_id=%s score=%s payload_keys=%s",
        id,
        aluno_id,
        score,
        list(payload.keys()) if isinstance(payload, dict) else None,
    )

    repo = ProgressoH5PRepository()
    progresso_atual = repo.get(db, aluno_id, id)
    primeira_conclusao = not (progresso_atual and progresso_atual.concluido)
    progresso = repo.marcar_concluido(db, aluno_id, id, score=score)

    # Dá XP somente na primeira conclusão da atividade.
    if primeira_conclusao:
        gamificacao = (
            db.query(PontuacaoGamificacao)
            .filter(PontuacaoGamificacao.aluno_id == aluno_id)
            .first()
        )
        if not gamificacao:
            gamificacao = PontuacaoGamificacao(aluno_id=aluno_id, xp_total=0, nivel="Novato")
            db.add(gamificacao)
            db.commit()
            db.refresh(gamificacao)

        ganho_xp = calculate_xp_gain(
            activity_type=getattr(obj, "tipo", "outro"),
            score=score,
            is_first_completion=primeira_conclusao,
        )
        gamificacao.xp_total = int((gamificacao.xp_total or 0) + ganho_xp)
        nivel_info = get_level_progress(gamificacao.xp_total)
        gamificacao.nivel = nivel_info["nivel"]
        db.commit()
        logger.info(
            "XP adicionado: atividade_id=%s aluno_id=%s ganho_xp=%s xp_total=%s nivel=%s",
            id,
            aluno_id,
            ganho_xp,
            gamificacao.xp_total,
            gamificacao.nivel,
        )
    else:
        logger.info(
            "Conclusão repetida sem XP: atividade_id=%s aluno_id=%s",
            id,
            aluno_id,
        )

    return progresso


@router.post("/professor-atividades/{id}/concluir")
async def concluir_atividade_professor(
    id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    aluno = db.query(Aluno).filter(Aluno.usuario_id == current_user.id).first()
    if not aluno:
        raise HTTPException(403, "Apenas alunos podem concluir essa atividade")
    atividade = db.query(ProfessorAtividadeH5P).filter(ProfessorAtividadeH5P.id == id, ProfessorAtividadeH5P.ativo == True).first()
    if not atividade:
        raise HTTPException(404, "Atividade não encontrada")
    if not aluno.turma_id or atividade.turma_id != aluno.turma_id:
        raise HTTPException(403, "Atividade não pertence à sua turma")

    score = None
    try:
        payload = await request.json()
    except Exception:
        payload = None
    if isinstance(payload, dict):
        score = _parse_score_from_payload(payload)

    progresso = db.query(ProfessorProgressoH5P).filter(
        ProfessorProgressoH5P.aluno_id == aluno.id,
        ProfessorProgressoH5P.atividade_id == atividade.id,
    ).first()
    primeira_conclusao = not (progresso and progresso.concluido)
    if not progresso:
        progresso = ProfessorProgressoH5P(
            aluno_id=aluno.id,
            atividade_id=atividade.id,
            tentativas=0,
        )
        db.add(progresso)
    progresso.tentativas = int((progresso.tentativas or 0) + 1)
    progresso.concluido = True
    progresso.score = score
    progresso.data_conclusao = datetime.utcnow()
    db.commit()

    if primeira_conclusao:
        gamificacao = db.query(PontuacaoGamificacao).filter(PontuacaoGamificacao.aluno_id == aluno.id).first()
        if not gamificacao:
            gamificacao = PontuacaoGamificacao(aluno_id=aluno.id, xp_total=0, nivel="Novato")
            db.add(gamificacao)
            db.commit()
            db.refresh(gamificacao)
        ganho_xp = calculate_xp_gain(
            activity_type=getattr(atividade, "tipo", "outro"),
            score=score,
            is_first_completion=True,
        )
        gamificacao.xp_total = int((gamificacao.xp_total or 0) + ganho_xp)
        gamificacao.nivel = get_level_progress(gamificacao.xp_total)["nivel"]
        db.commit()
    return {"aluno_id": aluno.id, "atividade_id": atividade.id, "concluido": True, "score": score}


@router.get("/atividades/{id}/progresso")
def obter_progresso(
    id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Retorna o progresso do aluno na atividade."""
    aluno_id = _get_aluno_id(db, current_user)
    if not aluno_id:
        raise HTTPException(403, "Apenas alunos possuem progresso")
    obj = AtividadeH5PRepository().get(db, id)
    if not obj or not obj.ativo:
        raise HTTPException(404, "Atividade não encontrada")
    _ensure_aluno_can_access_atividade(db, current_user, obj)
    progresso = ProgressoH5PRepository().get_or_create(db, aluno_id, id)
    return {
        "concluido": progresso.concluido,
        "score": progresso.score,
        "data_conclusao": progresso.data_conclusao,
        "tentativas": progresso.tentativas,
    }
