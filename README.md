# AVA MJ - Explicacao do Sistema

## 1) O que e este sistema

O AVA MJ e uma plataforma educacional digital para apoiar escolas e redes de ensino.

Em termos simples, ele funciona como um ambiente onde:

- alunos entram com login e realizam trilhas/missoes;
- professores e gestores acompanham resultados;
- a equipe pode medir evolucao de aprendizagem com mais clareza.

## 2) Qual problema ele resolve

Hoje, muitas redes tem dificuldade para:

- acompanhar desempenho de forma continua;
- transformar dados em acao pedagogica;
- manter o aluno engajado no estudo.

O AVA MJ foi desenhado para organizar esse processo com:

- experiencia gamificada para o aluno;
- indicadores e relatorios para equipe pedagogica;
- base tecnica para integracao com Moodle e IA.

## 3) Como o sistema funciona no dia a dia

Fluxo resumido:

1. A pessoa cria conta e entra no sistema.
2. O sistema identifica o perfil dela (aluno, professor, gestor, admin).
3. Cada perfil vai para sua tela inicial.
4. No caso do aluno, ele acessa trilhas e missoes.
5. O progresso fica registrado para analise posterior.

## 4) O que ja esta pronto neste momento

Atualmente, estao implementados:

- pagina inicial institucional;
- login e cadastro;
- redirecionamento por perfil no login;
- area inicial do aluno;
- tela visual da "Missao 1" (layout completo);
- menu mobile com hamburguer e acessibilidade inicial (A+, A-, alto contraste);
- botao de sair (logout), que encerra a sessao.

## 5) Perfis de acesso (visao funcional)

- **Aluno**: acessa trilhas, missoes e progresso.
- **Professor**: estrutura de tela inicial pronta (base para evolucao).
- **Gestor**: estrutura de tela inicial pronta (base para evolucao).
- **Admin**: estrutura de tela inicial pronta (base para evolucao).

## 6) Seguranca e sessao (sem detalhes tecnicos excessivos)

- O login gera uma credencial de sessao.
- Essa sessao e armazenada com protecao no navegador.
- O botao "Sair" remove a sessao.
- Rotas e dados podem ser controlados por perfil de usuario.

## 7) O que a lideranca ganha com esse projeto

- Visibilidade: acompanhamento estruturado da aprendizagem.
- Escalabilidade: base para crescer por escola, turma e rede.
- Governanca: padrao unico de acesso e navegacao por perfil.
- Potencial pedagogico: caminho para intervencao orientada por dados.

## 8) Como abrir e demonstrar rapidamente

Para apresentacao interna, o roteiro sugerido e:

1. Abrir pagina inicial.
2. Mostrar login e cadastro.
3. Entrar como aluno.
4. Exibir tela inicial do aluno.
5. Clicar em "Comecar Aventura" e mostrar a Missao 1.
6. Demonstrar menu mobile e recursos de acessibilidade.
7. Mostrar logout.

## 9) Proximos passos recomendados

- Conectar missoes com banco de dados real (conteudo dinamico).
- Transformar telas de professor e gestor em paineis operacionais.
- Definir indicadores de sucesso pedagogico (KPI educacional).
- Formalizar trilha de implantacao por rede/escola.

## 10) Resumo executivo

O AVA MJ ja possui uma base funcional consistente para autenticacao, navegacao por perfil e experiencia inicial do aluno.
Com a evolucao das camadas de conteudo e analytics, ele pode se tornar um instrumento de gestao pedagogica em larga escala.
# AVA MJ Backend

Backend em `FastAPI` para o sistema AVA MJ, com API + templates Jinja2 para telas web (login, cadastro, aluno, professor, gestor e admin).

## Stack

- Python 3.11+
- FastAPI + Uvicorn
- SQLAlchemy
- MySQL (via PyMySQL)
- Jinja2 (templates server-side)
- JWT (autenticacao)
- SlowAPI (rate limit)

## Estrutura principal

```text
app/
  core/           # config, banco, seguranca
  models/         # modelos SQLAlchemy
  repositories/   # acesso ao banco
  services/       # regras de negocio
  routers/        # rotas API e paginas
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

## Instalacao

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
- `GET /aluno/missao1` -> tela visual da missao 1
- `GET /professor` -> home professor (placeholder)
- `GET /gestor` -> home gestor (placeholder)
- `GET /admin` -> home admin (placeholder)

## Rotas de autenticacao

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

Parametros obrigatorios para criar aluno:

- `nome`
- `email`
- `senha`
- `turma_id`
- `ano`

## Observacoes

- Arquivos estaticos sao servidos em `/static` a partir de `app/templates/static`.
- As tabelas sao criadas no startup (`Base.metadata.create_all`).
- O projeto usa `bcrypt==4.0.1` para compatibilidade com `passlib==1.7.4`.
