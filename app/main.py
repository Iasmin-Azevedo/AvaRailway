import logging
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal, engine, get_db
from app.core.dependencies import require_admin_redirect, require_role_redirect
from app.core.logging_config import configure_logging
from app.core.security import limiter
from app.models.base import Base
from app.models.user import UserRole, Usuario
from app.services.dashboard_service import DashboardService

from app.routers import (
    admin_pages_router,
    admin_router,
    aluno_router,
    auth_router,
    avaliacao_router,
    chat_router,
    dashboard_router,
    h5p_router,
    ia_router,
)
from app.models import (
    aluno,
    avaliacao,
    chat_feedback,
    chat_memory,
    chat_message,
    chat_session,
    gestao,
    h5p,
    interacao_ia,
    relacoes,
    resposta,
    saeb,
    user,
)

configure_logging()
logger = logging.getLogger("ava_mj_backend")

app = FastAPI(title="AVA MJ Enterprise")

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "templates" / "static")), name="static")

app.add_middleware(GZipMiddleware, minimum_size=500)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_exception_handler(request: Request, exc: SQLAlchemyError):
    logger.error(f"Erro critico de banco de dados: {str(exc)}")
    return JSONResponse(
        status_code=500,
        content={
            "status_code": 500,
            "mensagem_amigavel": "Nao foi possivel processar a solicitacao.",
            "detalhe_tecnico": "Falha interna de banco de dados.",
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "status_code": 422,
            "mensagem_amigavel": "Existem campos invalidos na solicitacao.",
            "detalhe_tecnico": exc.errors(),
        },
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "status_code": exc.status_code,
            "mensagem_amigavel": str(exc.detail),
            "detalhe_tecnico": str(exc.detail),
        },
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.exception("Erro inesperado na aplicacao", exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={
            "status_code": 500,
            "mensagem_amigavel": "Nao foi possivel processar a solicitacao.",
            "detalhe_tecnico": "Erro interno nao tratado.",
        },
    )


def seed_default_users() -> None:
    from app.repositories.user_repository import UserRepository
    from app.schemas.user_schema import UserCreate

    defaults = [
        {"nome": "Admin AVA MJ", "email": "admin@avajmj.com", "role": UserRole.ADMIN},
        {"nome": "Professor AVA MJ", "email": "professor@avamj.com", "role": UserRole.PROFESSOR},
        {"nome": "Aluno AVA MJ", "email": "aluno@avamj.com", "role": UserRole.ALUNO},
        {"nome": "Gestor AVA MJ", "email": "gestor@avamj.com", "role": UserRole.GESTOR},
        {"nome": "Coordenador AVA MJ", "email": "coordenador@avamj.com", "role": UserRole.COORDENADOR},
    ]

    db = SessionLocal()
    try:
        repo = UserRepository()
        for d in defaults:
            existing = repo.get_by_email(db, d["email"])
            if existing:
                repo.update(
                    db,
                    id=existing.id,
                    nome=d["nome"],
                    email=d["email"],
                    senha="123456",
                    role=d["role"],
                    ativo=True,
                )
            else:
                repo.create(
                    db,
                    UserCreate(
                        nome=d["nome"],
                        email=d["email"],
                        senha="123456",
                        role=d["role"],
                    ),
                )
    finally:
        db.close()


@app.on_event("startup")
def on_startup():
    try:
        Base.metadata.create_all(bind=engine)
        seed_default_users()
        logger.info("Banco sincronizado e seed executado.")
    except Exception as exc:
        logger.error(f"Erro no startup: {exc}")


app.include_router(auth_router.router, prefix="/auth", tags=["Auth"])
app.include_router(aluno_router.router, prefix="/alunos", tags=["Alunos"])
app.include_router(aluno_router.page_router, tags=["Aluno"])
app.include_router(dashboard_router.router, prefix="/api", tags=["Dashboard"])
app.include_router(avaliacao_router.router, prefix="/provas", tags=["Avaliacao"])
app.include_router(ia_router.router, prefix="/ia", tags=["Inteligencia Artificial"])
app.include_router(admin_router.router, prefix="/api/admin", tags=["Admin"])
app.include_router(admin_pages_router.router, prefix="/admin", tags=["Admin Pages"])
app.include_router(h5p_router.router, prefix="/api/h5p", tags=["H5P"])
app.include_router(chat_router.router)


@app.get("/login")
def login_page(request: Request):
    return templates.TemplateResponse(request, "auth/login.html", {"request": request})


@app.get("/cadastro")
def cadastro_page(request: Request, db: Session = Depends(get_db)):
    from app.repositories.gestao_repository import EscolaRepository, TurmaRepository

    try:
        turmas = TurmaRepository().listar(db)
        escolas = EscolaRepository().listar(db, ativo_only=True)
    except Exception:
        turmas = []
        escolas = []
    return templates.TemplateResponse(
        request,
        "auth/cadastro.html",
        {"request": request, "turmas": turmas or [], "escolas": escolas or []},
    )


@app.get("/professor")
def professor_dashboard(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.PROFESSOR)),
):
    from app.models.gestao import Turma
    from app.models.relacoes import ProfessorTurma

    stats = DashboardService().get_professor_stats(db)
    relacoes = (
        db.query(ProfessorTurma)
        .join(Turma, ProfessorTurma.turma_id == Turma.id)
        .filter(ProfessorTurma.professor_id == current_user.id)
        .all()
    )
    professor_turmas = [rel.turma for rel in relacoes]

    nome = (current_user.nome or "").strip()
    partes = nome.split()
    if len(partes) >= 2:
        avatar_iniciais = (partes[0][0] + partes[-1][0]).upper()
    elif len(partes) == 1 and len(partes[0]) >= 2:
        avatar_iniciais = partes[0][:2].upper()
    else:
        avatar_iniciais = "PR"

    return templates.TemplateResponse(
        request,
        "professor/dashboard.html",
        {
            "request": request,
            "stats": stats,
            "current_user": current_user,
            "professor_turmas": professor_turmas,
            "selected_turma_id": None,
            "avatar_iniciais": avatar_iniciais,
        },
    )


@app.get("/gestor")
def gestor_dashboard(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.GESTOR)),
):
    stats = DashboardService().get_gestor_stats(db)
    return templates.TemplateResponse(request, "gestor/dashboard.html", {"request": request, "stats": stats})


@app.get("/admin")
def admin_dashboard(
    request: Request,
    current_user: Usuario = Depends(require_admin_redirect),
):
    return templates.TemplateResponse(request, "admin/dashboard.html", {"request": request})


@app.get("/coordenador")
def coordenador_dashboard(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.COORDENADOR)),
):
    from app.models.gestao import Escola
    from app.models.relacoes import CoordenadorEscola

    stats = DashboardService().get_coordenador_stats(db)
    rel = (
        db.query(CoordenadorEscola)
        .join(Escola, CoordenadorEscola.escola_id == Escola.id)
        .filter(CoordenadorEscola.coordenador_id == current_user.id)
        .first()
    )
    escola = rel.escola if rel else None

    nome = (current_user.nome or "").strip()
    partes = nome.split()
    if len(partes) >= 2:
        avatar_iniciais = (partes[0][0] + partes[-1][0]).upper()
    elif len(partes) == 1 and len(partes[0]) >= 2:
        avatar_iniciais = partes[0][:2].upper()
    else:
        avatar_iniciais = "CO"

    return templates.TemplateResponse(
        request,
        "coordenador/dashboard.html",
        {
            "request": request,
            "stats": stats,
            "current_user": current_user,
            "escola": escola,
            "avatar_iniciais": avatar_iniciais,
        },
    )


@app.get("/")
def home(request: Request):
    dados = {
        "status": "online",
        "system": "AVA MJ Backend",
        "features": ["Auth", "Alunos", "Dashboard", "Avaliacoes", "IA", "Chatbot"],
        "optimizations": ["GZip Compression", "Rate Limiting", "DB Error Handling"],
    }
    return templates.TemplateResponse(request, "auth/index.html", {"request": request, **dados})


@app.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {
        "status": "healthy",
        "project": settings.PROJECT_NAME,
        "database": "connected",
        "service": "online",
    }
