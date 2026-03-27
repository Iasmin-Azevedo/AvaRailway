from pydantic import BaseModel, Field


class RetrievedChunk(BaseModel):
    source: str
    title: str
    content: str
    score: float
    metadata: dict = Field(default_factory=dict)
