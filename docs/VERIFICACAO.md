# Como validar a entrega

Este roteiro foi pensado para facilitar uma verificacao objetiva do que entrou no backend.

## 1. Preparar o ambiente

1. Copie `.env.example` para `.env`.
2. Ajuste `SECRET_KEY`.
3. Se for usar SQLite em desenvolvimento, mantenha `DATABASE_URL=sqlite:///./avamj.db`.
4. Se for usar MySQL, ajuste a URL para o banco correto.

## 2. Instalar dependencias

```powershell
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
```

## 3. Aplicar migracoes

```powershell
python -m alembic upgrade head
```

## 4. Subir o backend

```powershell
python -m uvicorn app.main:app --reload
```

Depois disso, abra:

- `http://127.0.0.1:8000/`
- `http://127.0.0.1:8000/health`
- `http://127.0.0.1:8000/docs`

## 5. Validar o login

Usuarios criados automaticamente:

- `admin@avajmj.com`
- `professor@avamj.com`
- `aluno@avamj.com`
- `gestor@avamj.com`
- `coordenador@avamj.com`

Senha:

- `123456`

Checklist:

- login redireciona cada perfil para sua area;
- logout remove a sessao;
- endpoints autenticados respondem apenas quando o usuario esta logado.

## 6. Validar o chatbot

### Criar sessao

`POST /api/v1/chat/sessions`

```json
{
  "titulo": "Minha conversa de teste"
}
```

### Listar sessoes

`GET /api/v1/chat/sessions`

### Enviar mensagem

`POST /api/v1/chat/message`

```json
{
  "session_id": "ID_DA_SESSAO",
  "message": "Me explique fracao de um jeito simples"
}
```

### Ler historico

`GET /api/v1/chat/history/ID_DA_SESSAO`

### Registrar feedback

`POST /api/v1/chat/sessions/ID_DA_SESSAO/feedback`

```json
{
  "message_id": "ID_DA_MENSAGEM_DO_ASSISTENTE",
  "rating": "positive",
  "comment": "Resposta clara"
}
```

### Encerrar sessao

`DELETE /api/v1/chat/sessions/ID_DA_SESSAO`

## 7. Validar o Ollama

Se voce ja tiver Ollama local:

```powershell
ollama pull llama3.1:8b
```

Ou, com Docker:

```powershell
docker compose --profile ai up -d ollama
docker exec -it avamj-ollama ollama pull llama3.1:8b
```

Com o Ollama disponivel em `http://localhost:11434`, o chatbot passa a tentar a resposta pelo modelo configurado. Se o servico nao estiver ativo, o backend nao quebra: ele devolve resposta de fallback.

## 8. Verificacao rapida de codigo

```powershell
@'
import compileall
print("OK" if compileall.compile_dir("app", quiet=1) else "FAIL")
'@ | python -
```

```powershell
@'
import compileall
print("OK" if compileall.compile_dir("alembic", quiet=1) else "FAIL")
'@ | python -
```
