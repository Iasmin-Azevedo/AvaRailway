from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from jose import JWTError, jwt
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.config import settings
from app.schemas.user_schema import UserCreate, UserResponse
from app.repositories.user_repository import UserRepository
from app.repositories.aluno_repository import AlunoRepository

router = APIRouter()
page_router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
user_repo = UserRepository()
aluno_repo = AlunoRepository()


def _get_aluno_nome(request: Request, db: Session) -> str:
    aluno_nome = "Aluno"
    token = request.cookies.get("access_token")
    if token:
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
            email = payload.get("sub")
            if email:
                user = user_repo.get_by_email(db, email)
                if user and user.nome:
                    aluno_nome = user.nome
        except JWTError:
            pass
    return aluno_nome


@page_router.get("/aluno")
def aluno_home(request: Request, db: Session = Depends(get_db)):
    aluno_nome = _get_aluno_nome(request, db)

    return templates.TemplateResponse(
        "aluno/index.html",
        {"request": request, "aluno_nome": aluno_nome},
    )


@page_router.get("/aluno/missao1")
def aluno_missao_1(request: Request, db: Session = Depends(get_db)):
    aluno_nome = _get_aluno_nome(request, db)
    return templates.TemplateResponse(
        "aluno/missao1_desafios.html",
        {"request": request, "aluno_nome": aluno_nome},
    )


@page_router.post("/aluno")
async def criar_aluno_web(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    user = UserCreate(
        nome=form.get("nome"),
        email=form.get("email"),
        senha=form.get("senha"),
        role="aluno",
    )
    turma_id = form.get("turma_id")
    ano = form.get("ano")

    if turma_id is None or ano is None:
        raise HTTPException(status_code=422, detail="turma_id e ano sao obrigatorios")

    novo_user = user_repo.create(db, user)
    aluno_repo.create(db, novo_user.id, int(turma_id), int(ano))
    return RedirectResponse(url="/aluno", status_code=303)


@router.post("/cadastro", response_model=UserResponse)
async def criar_aluno(
    request: Request,
    turma_id: int | None = None,
    ano: int | None = None,
    db: Session = Depends(get_db),
):
    content_type = request.headers.get("content-type", "")
    accepts_html = "text/html" in request.headers.get("accept", "")

    if "application/json" in content_type:
        payload = await request.json()
        user = UserCreate(
            nome=payload.get("nome"),
            email=payload.get("email"),
            senha=payload.get("senha"),
            role=payload.get("role", "aluno"),
        )
        turma_id = turma_id if turma_id is not None else payload.get("turma_id")
        ano = ano if ano is not None else payload.get("ano")
    else:
        form = await request.form()
        user = UserCreate(
            nome=form.get("nome"),
            email=form.get("email"),
            senha=form.get("senha"),
            role="aluno",
        )
        turma_id = turma_id if turma_id is not None else form.get("turma_id")
        ano = ano if ano is not None else form.get("ano")

    if turma_id is None or ano is None:
        raise HTTPException(status_code=422, detail="turma_id e ano sao obrigatorios")

    novo_user = user_repo.create(db, user)
    aluno_repo.create(db, novo_user.id, int(turma_id), int(ano))

    if accepts_html:
        return RedirectResponse(url="/aluno", status_code=303)
    return novo_user