from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.schemas.chat_schema import (
    ChatFeedbackRequest,
    ChatFeedbackResponse,
    ChatHistoryItem,
    ChatHistoryResponse,
    ChatMessageRequest,
    ChatMessageResponse,
    ChatRuntimeStatusResponse,
    ChatSessionCreateRequest,
    ChatSessionResponse,
)
from app.services.chat_service import ChatService

router = APIRouter(prefix="/api/v1/chat", tags=["Chatbot"])


@router.get("/sessions", response_model=list[ChatSessionResponse])
def list_chat_sessions(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    service = ChatService(db)
    return service.list_sessions(current_user)


@router.post("/sessions", response_model=ChatSessionResponse, status_code=status.HTTP_201_CREATED)
def create_chat_session(
    payload: ChatSessionCreateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    service = ChatService(db)
    return service.create_session(current_user, payload.titulo or "Nova conversa")


@router.post("/message", response_model=ChatMessageResponse)
async def send_message(
    payload: ChatMessageRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    service = ChatService(db)
    return await service.process_message(current_user, payload)


@router.get("/status", response_model=ChatRuntimeStatusResponse)
async def get_chat_status(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    service = ChatService(db)
    return await service.get_runtime_status()


@router.get("/history/{session_id}", response_model=ChatHistoryResponse)
def get_history(
    session_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    service = ChatService(db)
    items = service.get_history(current_user, session_id)
    return ChatHistoryResponse(
        session_id=session_id,
        items=[ChatHistoryItem.model_validate(item) for item in items],
    )


@router.post("/sessions/{session_id}/feedback", response_model=ChatFeedbackResponse)
def send_feedback(
    session_id: str,
    payload: ChatFeedbackRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    service = ChatService(db)
    service.add_feedback(
        user=current_user,
        session_id=session_id,
        message_id=payload.message_id,
        rating=payload.rating,
        comment=payload.comment,
    )
    return ChatFeedbackResponse(success=True, message="Feedback registrado com sucesso.")


@router.delete("/sessions/{session_id}", response_model=ChatSessionResponse)
def close_chat_session(
    session_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    service = ChatService(db)
    return service.close_session(current_user, session_id)
