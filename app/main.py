from fastapi import FastAPI, Request
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
from app.core.database import engine
from app.models.base import Base

# 1. IMPORTAR OS NOVOS ROUTERS
from app.routers import (
    auth_router, 
    aluno_router, 
    dashboard_router, 
    avaliacao_router, 
    ia_router         
)

# 2. IMPORTAR OS NOVOS MODELS 
from app.models import (
    user, 
    aluno, 
    saeb, 
    avaliacao,    
    resposta,     
    interacao_ia  
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



app.include_router(auth_router.router, prefix="/auth", tags=["Auth"])
app.include_router(aluno_router.router, prefix="/alunos", tags=["Alunos"])
app.include_router(aluno_router.page_router, tags=["Aluno"]) 
app.include_router(dashboard_router.router, prefix="/api", tags=["Dashboard"])
app.include_router(avaliacao_router.router, prefix="/provas", tags=["Avaliação"]) 
app.include_router(ia_router.router, prefix="/ia", tags=["Inteligência Artificial"]) 


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
        "features": ["Auth", "Alunos", "Dashboard", "Avaliações", "IA"],
        "optimizations": ["GZip Compression", "Rate Limiting", "DB Error Handling"]
    }
    return templates.TemplateResponse(
        "auth/index.html",
        {"request": request, **dados},
    )
