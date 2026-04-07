# Backend do AVA MJ

## Visao geral

Esta etapa do projeto deixou o backend mais proximo de uma base pronta para continuidade do produto. A ideia foi manter o que ja existia funcionando para as telas atuais e, ao mesmo tempo, fechar pontos tecnicos que fariam falta na integracao com frontend, operacao local e evolucao do chatbot.

## O que foi organizado

### Nucleo da aplicacao

- configuracao centralizada em `app/core/config.py`;
- conexao de banco preparada para SQLite em desenvolvimento e MySQL em cenarios mais proximos de producao;
- logging basico em `app/core/logging_config.py`;
- health check em `GET /health`;
- tratamento padronizado de erros para respostas mais previsiveis.

### Autenticacao e acesso

- login com `access token`;
- renovacao com `refresh token`;
- cookies configuraveis por ambiente;
- validacao do usuario autenticado;
- restricao por perfil para as areas de aluno, professor, gestor, coordenador e admin;
- auditoria basica de login na tabela `auditoria_logs`.

### Chatbot

O modulo de chatbot foi estruturado para nao ser apenas um endpoint solto. Agora ele tem:

- sessoes por usuario;
- historico persistido;
- memoria resumida de conversa;
- classificacao simples da intencao da mensagem;
- contexto ligado ao perfil do usuario;
- feedback de resposta;
- suporte a Ollama quando o servico estiver disponivel;
- fallback local quando o provedor de IA nao responder;
- fluxo guiado para duvidas de matematica;
- atalhos para solicitar contato com professor;
- registro de solicitacoes de apoio enviadas pelo chatbot.

### Aulas ao vivo e agenda

O backend tambem passou a contar com uma estrutura leve para aulas ao vivo:

- agendamento de videoconferencias pelo professor;
- armazenamento de titulo, disciplina, turma, horario e link externo;
- exibicao da agenda para o aluno na propria plataforma;
- visualizacao das proximas aulas ao vivo no painel do professor;
- mecanismo de solicitacao de apoio ao professor a partir do chatbot.

### Operacao e ambiente

- `.env.example` com variaveis de configuracao;
- `Dockerfile` para subir o backend;
- `docker-compose.yml` com backend, MySQL e perfil opcional para Ollama;
- migracao Alembic para as tabelas do chatbot.

## Endpoints principais

### Sistema

- `GET /`
- `GET /health`
- `GET /login`
- `GET /cadastro`

### Autenticacao

- `POST /auth/login`
- `POST /auth/refresh`
- `GET /auth/logout`

### Chatbot

- `GET /api/v1/chat/sessions`
- `POST /api/v1/chat/sessions`
- `POST /api/v1/chat/message`
- `GET /api/v1/chat/history/{session_id}`
- `POST /api/v1/chat/sessions/{session_id}/feedback`
- `DELETE /api/v1/chat/sessions/{session_id}`

### Aulas ao vivo e suporte

- `POST /api/v1/live-support/live-classes`
- `GET /api/v1/live-support/live-classes/upcoming`
- `POST /api/v1/live-support/teacher-help-requests`
- `GET /api/v1/live-support/teacher-help-requests`

## Seguranca que ja esta no codigo

- senhas com `bcrypt`;
- autenticacao com JWT;
- refresh token;
- validacao com `Pydantic`;
- cookies `httponly`;
- `CORS` configuravel;
- respostas de erro padronizadas;
- `GZip` habilitado;
- base de `rate limiting` com `SlowAPI`.

## O que ainda e evolucao futura

Alguns itens do documento tecnico sao mais amplos e normalmente entram numa fase seguinte de produto e infraestrutura:

- pipeline CI/CD;
- ambiente com Nginx e balanceamento;
- Redis para cache;
- testes de carga com Locust;
- observabilidade mais avancada;
- consolidacao total dos relatorios pedagogicos previstos no documento.

Nada disso impede a entrega atual do backend, mas vale manter essa diferenca clara: parte do que foi pedido no documento ja esta refletida no codigo, e parte ja ficou preparada para a proxima fase.

## Atualizacoes recentes no chatbot

- deteccao de saudacoes curtas e respostas mais naturais;
- bloqueio de ofensas, discriminacao e pedidos de alteracao do sistema;
- recuperacao de fontes e contexto pedagogico;
- apoio especifico para perguntas matematicas com fluxo guiado;
- atalho para escalar a conversa e encaminhar pedido ao professor.
- identificacao de disciplina principal, com foco inicial em Matematica e Lingua Portuguesa;
- retorno de opcoes para o aluno seguir com o chat ou solicitar apoio do professor da materia;
- resposta explicita de que o sistema ainda esta em treinamento quando nao houver base suficiente;
- reducao de respostas vagas ou repetitivas por meio de verificacao de baixa informacao.
- camada NLU opcional para melhorar entendimento inicial da mensagem, com fallback local quando o provedor externo nao estiver configurado.

## Fundamentacao tecnica

Para sustentar a organizacao do backend com base tecnica mais explicita, o projeto pode ser relacionado a referencias consolidadas de arquitetura, modelagem e persistencia:

- `Clean Architecture`, de Robert C. Martin, como base para separacao entre rotas, servicos, repositorios e regras de negocio;
- `Architecture Patterns with Python`, de Harry Percival e Bob Gregory, como base pratica para organizacao do codigo em Python;
- `Designing Data-Intensive Applications`, de Martin Kleppmann, como apoio para persistencia, integracao e confiabilidade do sistema;
- `Domain-Driven Design`, de Eric Evans, como referencia para modelagem do dominio pedagogico.

## Diretrizes de codigo

- o backend deve manter padrao profissional e objetivo;
- nao devem ser utilizados emojis em codigo, comentarios ou mensagens tecnicas internas;
- comentarios devem ser curtos e usados apenas quando ajudarem a esclarecer a intencao da logica;
- ajustes de organizacao devem preservar o comportamento ja validado do sistema.

## Fundamentacao para o chatbot

Para orientar a evolucao do chatbot com base mais solida, o projeto pode adotar o uso de modelos de linguagem combinados com recuperacao de contexto e fontes rastreaveis.

Como referencias tecnicas para essa linha, destacam-se:

- `Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks` (NeurIPS 2020), como base para respostas apoiadas por conteudo recuperado;
- estudos sobre LLMs em contexto educacional publicados em periodicos como `npj Science of Learning`, `Nature Machine Intelligence` e `npj Artificial Intelligence`.

O detalhamento dessas referencias foi reunido em `docs/FUNDAMENTACAO_TECNICA_E_CHATBOT.md`.
