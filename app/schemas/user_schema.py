from pydantic import BaseModel, EmailStr, Field
from app.models.user import UserRole

class UserCreate(BaseModel):
    nome: str
    email: EmailStr
    senha: str = Field(min_length=6, max_length=128)
    role: UserRole = UserRole.ALUNO

class UserResponse(BaseModel):
    id: int
    nome: str
    email: EmailStr
    role: str
    class Config:
        from_attributes = True