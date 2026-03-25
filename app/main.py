from fastapi import FastAPI, Request, Depends
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy.exc import SQLAlchemyError
import logging

from app.core.security import limiter
from app.core.database import engine, get_db, SessionLocal
from sqlalchemy.orm import Session
from app.core.dependencies import require_admin_redirect, require_role_redirect
from app.models.base import Base
from app.models.user import Usuario, UserRole
from app.services.dashboard_service import DashboardService

# 1. IMPORTAR OS ROUTERS
from app.routers import (
    auth_router,
    aluno_router,
    dashboard_router,
    avaliacao_router,
    ia_router,
    admin_router,
    admin_pages_router,
    h5p_router,
)

# 2. IMPORTAR OS MODELS (ordem: base, gestao antes de aluno/h5p)
from app.models import (
    user,
    gestao,
    aluno,
    saeb,
    avaliacao,
    resposta,
    interacao_ia,
    h5p,
    relacoes,
)

# Cria todas as tabelas no banco de dados
Base.metadata.create_all(bind=engine)

app = FastAPI(title="AVA MJ Enterprise")


templates = Jinja2Templates(directory="app/templates")
app.mount("/static", StaticFiles(directory="app/templates/static"), name="static")


# Configuração de Log para o servidor
logger = logging.getLogger("ava_mj_backend")

# Middlewares Globais
app.add_middleware(GZipMiddleware, minimum_size=500)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate Limit
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Blindagem de Segurança do Banco de Dados
@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_exception_handler(request: Request, exc: SQLAlchemyError):
    logger.error(f"Erro Crítico de Banco de Dados: {str(exc)}") 
    return JSONResponse(
        status_code=500,
        content={
            "error": "Erro Interno",
            "message": "Não foi possível processar a requisição. Tente novamente em instantes.",
            "code": "DB_ERROR_500"
        }
    )



def seed_default_users() -> None:
    """
    Seed de usuários padrão para facilitar o primeiro acesso.
    Mantém idempotência por e-mail e garante senha '123456' (hashada).
    """
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
def on_startup_seed_users() -> None:
    try:
        seed_default_users()
        logger.info("Seed de usuários padrão executado com sucesso.")
    except Exception as exc:
        logger.error(f"Falha ao criar usuários padrão: {exc}")


app.include_router(auth_router.router, prefix="/auth", tags=["Auth"])
app.include_router(aluno_router.router, prefix="/alunos", tags=["Alunos"])
app.include_router(aluno_router.page_router, tags=["Aluno"]) 
app.include_router(dashboard_router.router, prefix="/api", tags=["Dashboard"])
app.include_router(avaliacao_router.router, prefix="/provas", tags=["Avaliação"])
app.include_router(ia_router.router, prefix="/ia", tags=["Inteligência Artificial"])
app.include_router(admin_router.router, prefix="/api/admin", tags=["Admin"])
app.include_router(admin_pages_router.router, prefix="/admin", tags=["Admin Pages"])
app.include_router(h5p_router.router, prefix="/api/h5p", tags=["H5P"]) 


@app.get("/login")
def login_page(request: Request):
    return templates.TemplateResponse(
        "auth/login.html",
        {"request": request},
    )

@app.get("/cadastro")
def cadastro_page(request: Request, db: Session = Depends(get_db)):
    from app.repositories.gestao_repository import TurmaRepository, EscolaRepository
    try:
        turmas = TurmaRepository().listar(db)
        escolas = EscolaRepository().listar(db, ativo_only=True)
    except Exception:
        turmas = []
        escolas = []
    return templates.TemplateResponse(
        "auth/cadastro.html",
        {"request": request, "turmas": turmas or [], "escolas": escolas or []},
    )

@app.get("/professor")
def professor_dashboard(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.PROFESSOR)),
):
    from app.models.relacoes import ProfessorTurma
    from app.models.gestao import Turma

    stats = DashboardService().get_professor_stats(db)

    # Turmas do professor (para o seletor no header)
    relacoes = (
        db.query(ProfessorTurma)
        .join(Turma, ProfessorTurma.turma_id == Turma.id)
        .filter(ProfessorTurma.professor_id == current_user.id)
        .all()
    )
    professor_turmas = [rel.turma for rel in relacoes]

    # Iniciais do professor para o avatar
    nome = (current_user.nome or "").strip()
    partes = nome.split()
    if len(partes) >= 2:
        avatar_iniciais = (partes[0][0] + partes[-1][0]).upper()
    elif len(partes) == 1 and len(partes[0]) >= 2:
        avatar_iniciais = partes[0][:2].upper()
    else:
        avatar_iniciais = "PR"

    return templates.TemplateResponse(
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
    return templates.TemplateResponse(
        "gestor/dashboard.html",
        {"request": request, "stats": stats},
    )

@app.get("/admin")
def admin_dashboard(
    request: Request,
    current_user: Usuario = Depends(require_admin_redirect),
):
    return templates.TemplateResponse(
        "admin/dashboard.html",
        {"request": request},
    )

@app.get("/coordenador")
def coordenador_dashboard(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.COORDENADOR)),
):
    from app.models.relacoes import CoordenadorEscola
    from app.models.gestao import Escola

    stats = DashboardService().get_coordenador_stats(db)

    # Escola do coordenador (regra: uma escola por coordenador)
    rel = (
        db.query(CoordenadorEscola)
        .join(Escola, CoordenadorEscola.escola_id == Escola.id)
        .filter(CoordenadorEscola.coordenador_id == current_user.id)
        .first()
    )
    escola = rel.escola if rel else None

    # Iniciais para o avatar
    nome = (current_user.nome or "").strip()
    partes = nome.split()
    if len(partes) >= 2:
        avatar_iniciais = (partes[0][0] + partes[-1][0]).upper()
    elif len(partes) == 1 and len(partes[0]) >= 2:
        avatar_iniciais = partes[0][:2].upper()
    else:
        avatar_iniciais = "CO"

    return templates.TemplateResponse(
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
        "features": ["Auth", "Alunos", "Dashboard", "Avaliações", "IA"],
        "optimizations": ["GZip Compression", "Rate Limiting", "DB Error Handling"]
    }
    return templates.TemplateResponse(
        "auth/index.html",
        {"request": request, **dados},
    )
