from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session
from fastapi.templating import Jinja2Templates

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import UserRole
from app.schemas.live_support_schema import (
    AulaAoVivoCreateRequest,
    AulaAoVivoResponse,
    SolicitacaoProfessorAck,
    SolicitacaoProfessorCreateRequest,
    SolicitacaoProfessorResponse,
)
from app.services.live_support_service import LiveSupportService

router = APIRouter(prefix="/api/v1/live-support", tags=["Aulas ao Vivo e Suporte"])
page_router = APIRouter(tags=["Aulas ao Vivo"])
templates = Jinja2Templates(directory="app/templates")


@router.post("/live-classes", response_model=AulaAoVivoResponse, status_code=status.HTTP_201_CREATED)
def create_live_class(
    payload: AulaAoVivoCreateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    # Front: cria um agendamento leve e devolve o caminho interno da sala ao vivo.
    service = LiveSupportService(db)
    return service.create_live_class(current_user, payload)


@router.get("/live-classes/upcoming", response_model=list[AulaAoVivoResponse])
def list_upcoming_live_classes(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    # Front: usa esta rota para listar a agenda visivel para aluno ou professor.
    service = LiveSupportService(db)
    role = getattr(current_user.role, "value", current_user.role)
    if role == "professor":
        return service.list_live_classes_for_professor(current_user)
    return service.list_live_classes_for_student(current_user)


@router.post("/teacher-help-requests", response_model=SolicitacaoProfessorAck)
def create_teacher_help_request(
    payload: SolicitacaoProfessorCreateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    # Front: registra pedido de apoio do chatbot para o professor da turma.
    service = LiveSupportService(db)
    created = service.create_teacher_help_request(current_user, payload)
    return SolicitacaoProfessorAck(
        success=True,
        message="Sua solicitacao foi registrada e encaminhada ao professor responsavel.",
        request_id=created.id,
    )


@router.get("/teacher-help-requests", response_model=list[SolicitacaoProfessorResponse])
def list_teacher_help_requests(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    service = LiveSupportService(db)
    return service.list_teacher_help_requests(current_user)


@page_router.get("/ao-vivo/{live_class_id}")
def open_live_classroom(
    live_class_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    service = LiveSupportService(db)
    live_class = service.get_live_class_for_user(current_user, live_class_id)
    role = getattr(current_user.role, "value", current_user.role)
    back_path = "/professor" if role == UserRole.PROFESSOR.value else "/aluno"
    return templates.TemplateResponse(
        request,
        "live_support/live_classroom.html",
        {
            "request": request,
            "live_class": live_class,
            "back_path": back_path,
        },
    )
