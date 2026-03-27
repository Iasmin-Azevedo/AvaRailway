# Operacao local

Este arquivo junta o que normalmente seria usado por quem vai subir e validar o backend no dia a dia.

## Subida mais simples

1. Copie `.env.example` para `.env`.
2. Ajuste o banco conforme o ambiente.
3. Rode:

```powershell
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
python -m alembic upgrade head
python -m uvicorn app.main:app --reload
```

## Subida com containers

### Backend + banco + proxy

```powershell
docker compose up --build
```

### Backend + banco + proxy + Ollama

```powershell
docker compose --profile ai up --build
```

### Backend + banco + proxy + Redis

```powershell
docker compose --profile cache up --build
```

## Primeiro carregamento do Ollama

Depois que o container estiver no ar, baixe o modelo:

```powershell
docker exec -it avamj-ollama ollama pull llama3.1:8b
```

## Enderecos uteis

- backend direto: `http://localhost:8000`
- proxy Nginx: `http://localhost`
- Swagger: `http://localhost/docs`
- health check: `http://localhost/health`
