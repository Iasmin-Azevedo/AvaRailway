# AVA MJ - Explicação do Sistema

## 1) O que é este sistema

O AVA MJ é uma plataforma educacional digital para apoiar escolas e redes de ensino.

Em termos simples, ele funciona como um ambiente onde:

- alunos entram com login e realizam trilhas/missões;
- professores e gestores acompanham resultados;
- a equipe pode medir a evolução da aprendizagem com mais clareza.

## 2) Qual problema ele resolve

Hoje, muitas redes têm dificuldade para:

- acompanhar desempenho de forma contínua;
- transformar dados em ação pedagógica;
- manter o aluno engajado no estudo.

O AVA MJ foi desenhado para organizar esse processo com:

- experiência gamificada para o aluno;
- indicadores e relatórios para equipe pedagógica;
- base técnica para integração com Moodle e IA.

## 3) Como o sistema funciona no dia a dia

Fluxo resumido:

1. A pessoa cria conta e entra no sistema.
2. O sistema identifica o perfil dela (aluno, professor, gestor, admin).
3. Cada perfil vai para sua tela inicial.
4. No caso do aluno, ele acessa trilhas e missões.
5. O progresso fica registrado para análise posterior.

## 4) O que já está pronto neste momento

Atualmente, estão implementados:

- página inicial institucional;
- login e cadastro;
- redirecionamento por perfil no login;
- área inicial do aluno;
- tela visual da "Missão 1" (layout completo);
- menu mobile com hambúrguer e acessibilidade inicial (A+, A-, alto contraste);
- botão de sair (logout), que encerra a sessão.

## 5) Perfis de acesso (visão funcional)

- **Aluno**: acessa trilhas, missões e progresso.
- **Professor**: estrutura de tela inicial pronta (base para evolução).
- **Gestor**: estrutura de tela inicial pronta (base para evolução).
- **Admin**: estrutura de tela inicial pronta (base para evolução).

## 6) Segurança e sessão (sem detalhes técnicos excessivos)

- O login gera uma credencial de sessão.
- Essa sessão é armazenada com proteção no navegador.
- O botão "Sair" remove a sessão.
- Rotas e dados podem ser controlados por perfil de usuário.

## 7) O que a liderança ganha com esse projeto

- Visibilidade: acompanhamento estruturado da aprendizagem.
- Escalabilidade: base para crescer por escola, turma e rede.
- Governança: padrão único de acesso e navegação por perfil.
- Potencial pedagógico: caminho para intervenção orientada por dados.

## 8) Como abrir e demonstrar rapidamente

Para apresentação interna, o roteiro sugerido é:

1. Abrir página inicial.
2. Mostrar login e cadastro.
3. Entrar como aluno.
4. Exibir tela inicial do aluno.
5. Clicar em "Começar Aventura" e mostrar a Missão 1.
6. Demonstrar menu mobile e recursos de acessibilidade.
7. Mostrar logout.

## 9) Próximos passos recomendados

- Conectar missões com banco de dados real (conteúdo dinâmico).
- Transformar telas de professor e gestor em painéis operacionais.
- Definir indicadores de sucesso pedagógico (KPI educacional).
- Formalizar trilha de implantação por rede/escola.

## 10) Resumo executivo

O AVA MJ já possui uma base funcional consistente para autenticação, navegação por perfil e experiência inicial do aluno.
Com a evolução das camadas de conteúdo e analytics, ele pode se tornar um instrumento de gestão pedagógica em larga escala.

# AVA MJ Backend

Backend em `FastAPI` para o sistema AVA MJ, com API + templates Jinja2 para telas web (login, cadastro, aluno, professor, gestor e admin).

## Stack

- Python 3.11+
- FastAPI + Uvicorn
- SQLAlchemy
- MySQL (via PyMySQL)
- Jinja2 (templates server-side)
- JWT (autenticação)
- SlowAPI (rate limit)

## Estrutura principal

```text
app/
  core/           # config, banco, segurança
  models/         # modelos SQLAlchemy
  repositories/   # acesso ao banco
  services/       # regras de negócio
  routers/        # rotas API e páginas
  schemas/        # schemas Pydantic
  templates/      # templates Jinja2
  main.py         # app FastAPI
requirements.txt
```

## Requisitos de ambiente

Crie um arquivo `.env` na raiz com:

```env
DATABASE_URL=mysql+pymysql://USUARIO:SENHA@localhost:3306/avamj
SECRET_KEY=sua_chave_secreta
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
MOODLE_URL=https://seu-moodle
MOODLE_TOKEN=seu_token
```

## Instalação

### Windows (PowerShell)

```powershell
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
```

### Linux/macOS

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Executar o projeto

Na raiz do projeto:

```powershell
python -m uvicorn app.main:app --reload
```

Servidor local:

- API/UI: `http://127.0.0.1:8000`
- Swagger: `http://127.0.0.1:8000/docs`

## Rotas web principais

- `GET /` -> landing page
- `GET /login` -> tela de login
- `GET /cadastro` -> tela de cadastro
- `GET /aluno` -> home do aluno
- `GET /aluno/missao1` -> tela visual da missão 1
- `GET /professor` -> home professor (placeholder)
- `GET /gestor` -> home gestor (placeholder)
- `GET /admin` -> home admin (placeholder)

## Rotas de autenticação

- `POST /auth/login`
  - JSON: retorna token
  - Form HTML: autentica, grava cookie `access_token` e redireciona por perfil:
    - aluno -> `/aluno`
    - professor -> `/professor`
    - gestor -> `/gestor`
    - admin -> `/admin`
- `GET /auth/logout` -> remove cookie `access_token` e redireciona para `/login`

## Cadastro de aluno

- Fluxo web: `POST /aluno` (form do cadastro)
- Fluxo API: `POST /alunos/cadastro` (JSON)

Parâmetros obrigatórios para criar aluno:

- `nome`
- `email`
- `senha`
- `turma_id`
- `ano`

## Observações

- Arquivos estáticos são servidos em `/static` a partir de `app/templates/static`.
- As tabelas são criadas no startup (`Base.metadata.create_all`).
- O projeto usa `bcrypt==4.0.1` para compatibilidade com `passlib==1.7.4`.
