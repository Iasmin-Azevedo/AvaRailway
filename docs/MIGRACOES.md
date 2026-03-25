# Migrações do banco (Alembic) — AVA MJ

## O que foi configurado

- **Alembic**: controle de versão do banco (novas tabelas e alterações).
- **Migração 001**: cria tabelas `escolas`, `turmas`, `cursos`, `trilhas`, `atividades_h5p`, `progresso_h5p` e atualiza a coluna `role` da tabela `usuarios` para aceitar as roles `coordenador` e `admin`.

## Como usar

### 1. Instalar dependência

```bash
pip install alembic
# ou
pip install -r requirements.txt
```

### 2. Aplicar migrações (atualizar o banco)

Na raiz do projeto (onde está o `alembic.ini`), **com o venv do projeto ativado**:

```bash
python -m alembic upgrade head
```

Se o comando `alembic` não for reconhecido no Windows, use sempre `python -m alembic` (garante que usa o Alembic do venv ativo). Se der erro de "No module named alembic", instale no venv do AvaMJ:

```bash
.\venv\Scripts\python.exe -m pip install alembic
```

Isso vai:

- Criar as novas tabelas se ainda não existirem.
- No **MySQL**: se a coluna `usuarios.role` for ENUM, alterá-la para incluir `coordenador` e `admin`.
- No **PostgreSQL**: adicionar os valores `coordenador` e `admin` ao tipo enum de `role`.
- Garantir a FK de `alunos.turma_id` para `turmas.id`, se ainda não existir.

### 3. Ver status

```bash
python -m alembic current
```

### 4. Ver histórico

```bash
python -m alembic history
```

### 5. Reverter a última migração (cuidado)

```bash
python -m alembic downgrade -1
```

## Observações

- A URL do banco é lida do `.env` (`DATABASE_URL`), via `app.core.config.settings`.
- O `main.py` continua com `Base.metadata.create_all(bind=engine)` na subida da aplicação; as migrações servem para evoluir o banco de forma controlada (incluindo quando a tabela já existe).
- Se você **nunca rodou migrações** e o banco já tem as tabelas criadas pelo `create_all`, pode rodar `alembic upgrade head` sem problema: a migração só cria tabelas que ainda não existem e só altera `role` se for ENUM no MySQL.

## Criar uma nova migração no futuro

```bash
python -m alembic revision -m "descricao_da_alteracao"
```

Edite o arquivo em `alembic/versions/` e preencha `upgrade()` e `downgrade()`. Depois:

```bash
python -m alembic upgrade head
```
