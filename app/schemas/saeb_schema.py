from pydantic import BaseModel
from typing import Optional


class DescritorBase(BaseModel):
    codigo: str
    descricao: str
    disciplina: str


class DescritorCreate(DescritorBase):
    pass


class DescritorUpdate(BaseModel):
    codigo: Optional[str] = None
    descricao: Optional[str] = None
    disciplina: Optional[str] = None


class DescritorResponse(DescritorBase):
    id: int

    class Config:
        from_attributes = True
