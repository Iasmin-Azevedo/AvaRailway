from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from typing import List, Optional
import os

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import Usuario
from app.models.aluno import Aluno
from app.models.h5p import AtividadeH5P
from app.repositories.h5p_repository import AtividadeH5PRepository, ProgressoH5PRepository
from app.repositories.gestao_repository import TrilhaRepository
from app.schemas.h5p_schema import AtividadeH5PResponse, ConcluirH5PRequest, ProgressoH5PResponse
from app.core.config import settings

router = APIRouter()


def _get_aluno_id(db: Session, user: Usuario) -> Optional[int]:
    aluno = db.query(Aluno).filter(Aluno.usuario_id == user.id).first()
    return aluno.id if aluno else None


@router.get("/atividades", response_model=List[AtividadeH5PResponse])
def listar_atividades(
    trilha_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Lista atividades H5P (opcionalmente filtradas por trilha)."""
    return AtividadeH5PRepository().listar(db, trilha_id=trilha_id, ativo_only=True)


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
    path = obj.path_ou_json
    if not path:
        raise HTTPException(404, "Arquivo de conteúdo não configurado")
    if not os.path.isabs(path):
        path = os.path.join(settings.H5P_CONTENT_DIR, path)
    if not os.path.isfile(path):
        raise HTTPException(404, "Arquivo de conteúdo não encontrado")
    return FileResponse(path, media_type="application/json")


@router.post("/atividades/{id}/concluir", response_model=ProgressoH5PResponse)
def concluir_atividade(
    id: int,
    body: ConcluirH5PRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Registra conclusão e score da atividade para o aluno logado."""
    aluno_id = _get_aluno_id(db, current_user)
    if not aluno_id:
        raise HTTPException(403, "Apenas alunos podem registrar conclusão de atividades")
    obj = AtividadeH5PRepository().get(db, id)
    if not obj:
        raise HTTPException(404, "Atividade não encontrada")
    progresso = ProgressoH5PRepository().marcar_concluido(
        db, aluno_id, id, score=body.score
    )
    return progresso


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
    progresso = ProgressoH5PRepository().get_or_create(db, aluno_id, id)
    return {
        "concluido": progresso.concluido,
        "score": progresso.score,
        "data_conclusao": progresso.data_conclusao,
        "tentativas": progresso.tentativas,
    }
