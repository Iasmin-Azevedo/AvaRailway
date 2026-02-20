from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.core.security import limiter
from app.core.database import engine, Base

# 1. IMPORTAR OS NOVOS ROUTERS
from app.routers import (
    auth_router, 
    aluno_router, 
    dashboard_router, 
    avaliacao_router, # <--- NOVO
    ia_router         # <--- NOVO
)

# 2. IMPORTAR OS NOVOS MODELS (Para criar as tabelas)
from app.models import (
    user, 
    aluno, 
    saeb, 
    avaliacao,    # <--- NOVO
    resposta,     # <--- NOVO
    interacao_ia  # <--- NOVO
)

# Cria todas as tabelas no banco de dados
Base.metadata.create_all(bind=engine)

app = FastAPI(title="AVA MJ Enterprise")
templates = Jinja2Templates(directory="app/templates")
app.mount("/static", StaticFiles(directory="app/templates/static"), name="static")

# Configuração Rate Limit
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# 3. REGISTRAR AS NOVAS ROTAS
app.include_router(auth_router.router, prefix="/auth", tags=["Auth"])
app.include_router(aluno_router.router, prefix="/alunos", tags=["Alunos"])
app.include_router(aluno_router.page_router, tags=["Aluno"])
app.include_router(dashboard_router.router, prefix="/api", tags=["Dashboard"])
app.include_router(avaliacao_router.router, prefix="/provas", tags=["Avaliação"]) # <--- NOVO
app.include_router(ia_router.router, prefix="/ia", tags=["Inteligência Artificial"]) # <--- NOVO

@app.get("/login")
def login_page(request: Request):
    return templates.TemplateResponse(
        "auth/login.html",
        {"request": request},
    )


@app.get("/cadastro")
def cadastro_page(request: Request):
    return templates.TemplateResponse(
        "auth/cadastro.html",
        {"request": request},
    )


@app.get("/professor")
def professor_home(request: Request):
    return templates.TemplateResponse(
        "professor/index.html",
        {"request": request},
    )


@app.get("/gestor")
def gestor_home(request: Request):
    return templates.TemplateResponse(
        "gestor/index.html",
        {"request": request},
    )


@app.get("/admin")
def admin_home(request: Request):
    return templates.TemplateResponse(
        "admin/index.html",
        {"request": request},
    )


@app.get("/")
def home(request: Request):
    dados = {
        "status": "online", 
        "system": "AVA MJ Backend",
        "features": ["Auth", "Alunos", "Dashboard", "Avaliações", "IA"]
    }
    return templates.TemplateResponse(
        "auth/index.html",
        {"request": request, **dados},
    )