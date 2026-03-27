from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ChatSessionCreateRequest(BaseModel):
    titulo: str | None = Field(default="Nova conversa", max_length=150)


class ChatSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    perfil: str
    titulo: str
    status: str
    created_at: datetime
    updated_at: datetime


class ChatMessageRequest(BaseModel):
    session_id: str | None = None
    message: str = Field(min_length=1, max_length=2000)


class ChatMessageResponse(BaseModel):
    session_id: str
    user_message: str
    assistant_message: str
    assistant_message_id: str
    message_type: str
    created_at: datetime
    used_context: list[str] = Field(default_factory=list)
    used_sources: list[dict[str, Any]] = Field(default_factory=list)
    retrieval_count: int = 0


class ChatHistoryItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    sender: str
    message_text: str
    message_type: str
    created_at: datetime


class ChatHistoryResponse(BaseModel):
    session_id: str
    items: list[ChatHistoryItem]


class ChatFeedbackRequest(BaseModel):
    message_id: str
    rating: Literal["positive", "negative"]
    comment: str | None = None


class ChatFeedbackResponse(BaseModel):
    success: bool
    message: str


class IAChatPayload(BaseModel):
    question: str
    system_prompt: str
    profile: str
    history: list[dict[str, Any]]
    context: dict[str, Any]
    retrieved_chunks: list[dict[str, Any]]


class IAChatResult(BaseModel):
    answer: str
    used_context: list[str] = Field(default_factory=list)
