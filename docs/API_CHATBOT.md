# Chatbot do AVA MJ

## Ideia geral

O chatbot foi estruturado para funcionar como parte do backend do AVA MJ, e nao como um endpoint isolado. Isso significa que a conversa pode carregar contexto do usuario, manter historico e registrar feedback para evolucoes futuras.

## Prefixo de rotas

`/api/v1/chat`

## Autenticacao

Todos os endpoints exigem usuario autenticado.

O acesso pode ser feito por:

- cookie `access_token`;
- header `Authorization: Bearer <token>`.

## Endpoints

### Listar sessoes

`GET /sessions`

Retorna as conversas do usuario autenticado, da mais recente para a mais antiga.

### Criar sessao

`POST /sessions`

Exemplo:

```json
{
  "titulo": "Nova conversa"
}
```

Resposta esperada:

```json
{
  "id": "uuid",
  "perfil": "aluno",
  "titulo": "Nova conversa",
  "status": "ativa",
  "created_at": "2026-03-27T11:00:00",
  "updated_at": "2026-03-27T11:00:00"
}
```

### Enviar mensagem

`POST /message`

Exemplo:

```json
{
  "session_id": "uuid",
  "message": "Como estudar melhor?"
}
```

Resposta esperada:

```json
{
  "session_id": "uuid",
  "user_message": "Como estudar melhor?",
  "assistant_message": "Estude em blocos curtos...",
  "assistant_message_id": "uuid",
  "message_type": "general",
  "created_at": "2026-03-27T11:01:00",
  "used_context": ["Como estudar melhor"],
  "retrieval_count": 1
}
```

### Buscar historico

`GET /history/{session_id}`

Retorna as mensagens daquela conversa.

### Enviar feedback

`POST /sessions/{session_id}/feedback`

Exemplo:

```json
{
  "message_id": "uuid",
  "rating": "positive",
  "comment": "Muito bom"
}
```

### Encerrar sessao

`DELETE /sessions/{session_id}`

## Como o chatbot responde

O fluxo da resposta segue esta ordem:

1. identifica o tipo da mensagem;
2. monta contexto do usuario;
3. recupera trechos de apoio quando fizer sentido;
4. busca memoria resumida da conversa;
5. tenta responder via Ollama;
6. se o Ollama nao estiver disponivel, responde com fallback local.

## Observacoes de uso

- o backend ja esta preparado para usar `llama3.1:8b`;
- a URL do provedor e configurada por variavel de ambiente;
- o sistema guarda sessoes, mensagens, memoria e feedback;
- isso deixa a base pronta para melhorar o chat sem quebrar o frontend.
