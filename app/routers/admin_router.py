from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from typing import List, Optional

from app.core.database import get_db
from app.core.dependencies import require_admin
from app.models.user import Usuario, UserRole
from app.repositories.gestao_repository import (
    EscolaRepository,
    TurmaRepository,
    CursoRepository,
    TrilhaRepository,
)
from app.repositories.saeb_repository import DescritorRepository
from app.repositories.h5p_repository import AtividadeH5PRepository
from app.repositories.user_repository import UserRepository
from app.schemas.gestao_schema import (
    EscolaCreate,
    EscolaUpdate,
    EscolaResponse,
    TurmaCreate,
    TurmaUpdate,
    TurmaResponse,
    CursoCreate,
    CursoUpdate,
    CursoResponse,
    TrilhaCreate,
    TrilhaUpdate,
    TrilhaResponse,
)
from app.schemas.h5p_schema import (
    AtividadeH5PCreate,
    AtividadeH5PUpdate,
    AtividadeH5PResponse,
)
from app.schemas.user_schema import UserCreate, UserResponse, UserUpdate
from app.schemas.saeb_schema import DescritorCreate, DescritorUpdate, DescritorResponse

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

# --- Escolas ---
@router.get("/escolas", response_model=List[EscolaResponse])
def listar_escolas(
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
    ativo_only: bool = False,
):
    return EscolaRepository().listar(db, ativo_only=ativo_only)


@router.post("/escolas", response_model=EscolaResponse)
def criar_escola(
    data: EscolaCreate,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
):
    return EscolaRepository().create(db, data)


@router.get("/escolas/{id}", response_model=EscolaResponse)
def obter_escola(
    id: int,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
):
    obj = EscolaRepository().get(db, id)
    if not obj:
        raise HTTPException(404, "Escola não encontrada")
    return obj


@router.patch("/escolas/{id}", response_model=EscolaResponse)
def atualizar_escola(
    id: int,
    data: EscolaUpdate,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
):
    obj = EscolaRepository().update(db, id, data)
    if not obj:
        raise HTTPException(404, "Escola não encontrada")
    return obj


@router.delete("/escolas/{id}", status_code=204)
def excluir_escola(
    id: int,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
):
    if not EscolaRepository().delete(db, id):
        raise HTTPException(404, "Escola não encontrada")


# --- Turmas ---
@router.get("/turmas", response_model=List[TurmaResponse])
def listar_turmas(
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
    escola_id: Optional[int] = None,
    ano_escolar: Optional[int] = None,
):
    return TurmaRepository().listar(db, escola_id=escola_id, ano_escolar=ano_escolar)


@router.post("/turmas", response_model=TurmaResponse)
def criar_turma(
    data: TurmaCreate,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
):
    return TurmaRepository().create(db, data)


@router.get("/turmas/{id}", response_model=TurmaResponse)
def obter_turma(
    id: int,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
):
    obj = TurmaRepository().get(db, id)
    if not obj:
        raise HTTPException(404, "Turma não encontrada")
    return obj


@router.patch("/turmas/{id}", response_model=TurmaResponse)
def atualizar_turma(
    id: int,
    data: TurmaUpdate,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
):
    obj = TurmaRepository().update(db, id, data)
    if not obj:
        raise HTTPException(404, "Turma não encontrada")
    return obj


@router.delete("/turmas/{id}", status_code=204)
def excluir_turma(
    id: int,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
):
    if not TurmaRepository().delete(db, id):
        raise HTTPException(404, "Turma não encontrada")


# --- Cursos ---
@router.get("/cursos", response_model=List[CursoResponse])
def listar_cursos(
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
):
    return CursoRepository().listar(db)


@router.post("/cursos", response_model=CursoResponse)
def criar_curso(
    data: CursoCreate,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
):
    return CursoRepository().create(db, data)


@router.get("/cursos/{id}", response_model=CursoResponse)
def obter_curso(
    id: int,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
):
    obj = CursoRepository().get(db, id)
    if not obj:
        raise HTTPException(404, "Curso não encontrado")
    return obj


@router.patch("/cursos/{id}", response_model=CursoResponse)
def atualizar_curso(
    id: int,
    data: CursoUpdate,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
):
    obj = CursoRepository().update(db, id, data)
    if not obj:
        raise HTTPException(404, "Curso não encontrado")
    return obj


@router.delete("/cursos/{id}", status_code=204)
def excluir_curso(
    id: int,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
):
    if not CursoRepository().delete(db, id):
        raise HTTPException(404, "Curso não encontrado")


# --- Trilhas ---
@router.get("/trilhas", response_model=List[TrilhaResponse])
def listar_trilhas(
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
    curso_id: Optional[int] = None,
    ano_escolar: Optional[int] = None,
):
    return TrilhaRepository().listar(db, curso_id=curso_id, ano_escolar=ano_escolar)


@router.post("/trilhas", response_model=TrilhaResponse)
def criar_trilha(
    data: TrilhaCreate,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
):
    return TrilhaRepository().create(db, data)


@router.get("/trilhas/{id}", response_model=TrilhaResponse)
def obter_trilha(
    id: int,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
):
    obj = TrilhaRepository().get(db, id)
    if not obj:
        raise HTTPException(404, "Trilha não encontrada")
    return obj


@router.patch("/trilhas/{id}", response_model=TrilhaResponse)
def atualizar_trilha(
    id: int,
    data: TrilhaUpdate,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
):
    obj = TrilhaRepository().update(db, id, data)
    if not obj:
        raise HTTPException(404, "Trilha não encontrada")
    return obj


@router.delete("/trilhas/{id}", status_code=204)
def excluir_trilha(
    id: int,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
):
    if not TrilhaRepository().delete(db, id):
        raise HTTPException(404, "Trilha não encontrada")


# --- Descritores SAEB ---
@router.get("/descritores", response_model=List[DescritorResponse])
def listar_descritores(
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
    disciplina: Optional[str] = None,
):
    return DescritorRepository().listar(db, disciplina=disciplina)


@router.post("/descritores", response_model=DescritorResponse)
def criar_descritor(
    data: DescritorCreate,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
):
    return DescritorRepository().create(db, data.codigo, data.descricao, data.disciplina)


@router.patch("/descritores/{id}", response_model=DescritorResponse)
def atualizar_descritor(
    id: int,
    data: DescritorUpdate,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
):
    obj = DescritorRepository().update(
        db, id, data.codigo, data.descricao, data.disciplina
    )
    if not obj:
        raise HTTPException(404, "Descritor não encontrado")
    return obj


@router.delete("/descritores/{id}", status_code=204)
def excluir_descritor(
    id: int,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
):
    if not DescritorRepository().delete(db, id):
        raise HTTPException(404, "Descritor não encontrado")


# --- Atividades H5P ---
@router.get("/atividades-h5p", response_model=List[AtividadeH5PResponse])
def listar_atividades_h5p(
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
    trilha_id: Optional[int] = None,
    ativo_only: bool = False,
):
    return AtividadeH5PRepository().listar(db, trilha_id=trilha_id, ativo_only=ativo_only)


@router.post("/atividades-h5p", response_model=AtividadeH5PResponse)
def criar_atividade_h5p(
    data: AtividadeH5PCreate,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
):
    return AtividadeH5PRepository().create(db, data)


@router.get("/atividades-h5p/{id}", response_model=AtividadeH5PResponse)
def obter_atividade_h5p(
    id: int,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
):
    obj = AtividadeH5PRepository().get(db, id)
    if not obj:
        raise HTTPException(404, "Atividade não encontrada")
    return obj


@router.patch("/atividades-h5p/{id}", response_model=AtividadeH5PResponse)
def atualizar_atividade_h5p(
    id: int,
    data: AtividadeH5PUpdate,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
):
    obj = AtividadeH5PRepository().update(db, id, data)
    if not obj:
        raise HTTPException(404, "Atividade não encontrada")
    return obj


@router.delete("/atividades-h5p/{id}", status_code=204)
def excluir_atividade_h5p(
    id: int,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
):
    if not AtividadeH5PRepository().delete(db, id):
        raise HTTPException(404, "Atividade não encontrada")


# --- Usuários (admin) ---
@router.get("/usuarios", response_model=List[UserResponse])
def listar_usuarios(
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
    role: Optional[UserRole] = None,
    ativo_only: bool = False,
):
    users = UserRepository().listar(db, role=role, ativo_only=ativo_only)
    return [UserResponse.model_validate(u) for u in users]


@router.post("/usuarios", response_model=UserResponse)
def criar_usuario_admin(
    data: UserCreate,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
):
    repo = UserRepository()
    if repo.get_by_email(db, data.email):
        raise HTTPException(400, "E-mail já cadastrado")
    return repo.create(db, data)


@router.get("/usuarios/{id}", response_model=UserResponse)
def obter_usuario(
    id: int,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
):
    obj = UserRepository().get_by_id(db, id)
    if not obj:
        raise HTTPException(404, "Usuário não encontrado")
    return obj


@router.patch("/usuarios/{id}", response_model=UserResponse)
def atualizar_usuario_admin(
    id: int,
    data: UserUpdate,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
):
    obj = UserRepository().update(
        db, id,
        nome=data.nome,
        email=data.email,
        senha=data.senha,
        role=data.role,
        ativo=data.ativo,
    )
    if not obj:
        raise HTTPException(404, "Usuário não encontrado")
    return obj


@router.delete("/usuarios/{id}", status_code=204)
def excluir_usuario(
    id: int,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
):
    if not UserRepository().delete(db, id):
        raise HTTPException(404, "Usuário não encontrado")
