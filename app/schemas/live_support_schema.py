from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AulaAoVivoCreateRequest(BaseModel):
    turma_id: int
    disciplina: str = Field(min_length=2, max_length=50)
    titulo: str = Field(min_length=3, max_length=150)
    descricao: str | None = Field(default=None, max_length=1000)
    meeting_url: str | None = Field(default=None, max_length=500)
    scheduled_at: datetime
    duration_minutes: int = Field(default=50, ge=15, le=240)


class AulaAoVivoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    professor_id: int
    turma_id: int
    disciplina: str
    titulo: str
    descricao: str | None
    meeting_provider: str
    room_name: str
    meeting_url: str
    scheduled_at: datetime
    duration_minutes: int
    ativa: bool
    created_at: datetime
    join_path: str


class SolicitacaoProfessorCreateRequest(BaseModel):
    disciplina: str = Field(min_length=2, max_length=50)
    assunto: str = Field(min_length=4, max_length=255)
    session_id: str | None = Field(default=None, max_length=36)


class SolicitacaoProfessorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    requester_user_id: int
    professor_id: int | None
    turma_id: int | None
    disciplina: str
    assunto: str
    requester_role: str
    session_id: str | None
    status: str
    origem: str
    created_at: datetime


class SolicitacaoProfessorAck(BaseModel):
    success: bool
    message: str
    request_id: int


class SolicitacaoProfessorStatusUpdateRequest(BaseModel):
    status: str = Field(min_length=3, max_length=20)
