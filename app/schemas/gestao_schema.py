from pydantic import BaseModel
from typing import Optional


class EscolaBase(BaseModel):
    nome: str
    ativo: bool = True
    endereco: Optional[str] = None


class EscolaCreate(EscolaBase):
    pass


class EscolaUpdate(BaseModel):
    nome: Optional[str] = None
    ativo: Optional[bool] = None
    endereco: Optional[str] = None


class EscolaResponse(EscolaBase):
    id: int

    class Config:
        from_attributes = True


class TurmaBase(BaseModel):
    nome: str
    ano_escolar: int  # 2, 5 ou 9
    escola_id: int
    ano_letivo: Optional[str] = None


class TurmaCreate(TurmaBase):
    pass


class TurmaUpdate(BaseModel):
    nome: Optional[str] = None
    ano_escolar: Optional[int] = None
    escola_id: Optional[int] = None
    ano_letivo: Optional[str] = None


class TurmaResponse(TurmaBase):
    id: int

    class Config:
        from_attributes = True


class TurmaComEscola(TurmaResponse):
    escola_nome: Optional[str] = None


class CursoBase(BaseModel):
    nome: str


class CursoCreate(CursoBase):
    pass


class CursoUpdate(BaseModel):
    nome: Optional[str] = None


class CursoResponse(CursoBase):
    id: int

    class Config:
        from_attributes = True


class TrilhaBase(BaseModel):
    nome: str
    curso_id: int
    ano_escolar: Optional[int] = None
    ordem: int = 0


class TrilhaCreate(TrilhaBase):
    pass


class TrilhaUpdate(BaseModel):
    nome: Optional[str] = None
    curso_id: Optional[int] = None
    ano_escolar: Optional[int] = None
    ordem: Optional[int] = None


class TrilhaResponse(TrilhaBase):
    id: int

    class Config:
        from_attributes = True
