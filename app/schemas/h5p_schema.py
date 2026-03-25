from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class AtividadeH5PBase(BaseModel):
    titulo: str
    tipo: str  # quiz, drag-drop, video, flashcards, etc.
    path_ou_json: str
    trilha_id: Optional[int] = None
    descritor_id: Optional[int] = None
    ordem: int = 0
    ativo: bool = True


class AtividadeH5PCreate(AtividadeH5PBase):
    pass


class AtividadeH5PUpdate(BaseModel):
    titulo: Optional[str] = None
    tipo: Optional[str] = None
    path_ou_json: Optional[str] = None
    trilha_id: Optional[int] = None
    descritor_id: Optional[int] = None
    ordem: Optional[int] = None
    ativo: Optional[bool] = None


class AtividadeH5PResponse(AtividadeH5PBase):
    id: int
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ConcluirH5PRequest(BaseModel):
    concluido: bool = True
    score: Optional[float] = None


class ProgressoH5PResponse(BaseModel):
    id: int
    aluno_id: int
    atividade_id: int
    concluido: bool
    score: Optional[float] = None
    data_conclusao: Optional[datetime] = None
    tentativas: int = 0

    class Config:
        from_attributes = True
