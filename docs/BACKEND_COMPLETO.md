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
- fallback local quando o provedor de IA nao responder.

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
