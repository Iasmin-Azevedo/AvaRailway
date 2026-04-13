# Integração Moodle (AVA MJ)

Este documento descreve o comportamento atual e duas linhas de evolução para o gestor “liberar” cursos aos professores.

## Estado atual

- **Configuração:** `MOODLE_URL` e `MOODLE_TOKEN` em `.env` (ver `app/core/config.py`).
- **Vínculo do utilizador:** campo `moodle_user_id` no modelo `Usuario`, editável no admin (`usuario_form.html`).
- **Listagem no painel docente:** `MoodleWsService.list_user_courses` chama `core_enrol_get_users_courses` e devolve **apenas cursos em que o utilizador Moodle já está inscrito** (`app/services/moodle_ws_service.py`).
- **Conclusão:** o AVA MJ **não** aplica hoje regras de “liberação” próprias; reflete as matrículas existentes no Moodle.

## Futuro A — Gestão só no Moodle (menos código)

O gestor (ou coordenação) **inscreve** os professores nos cursos corretos no Moodle (por escola, disciplina ou política da rede). O AVA MJ continua a mostrar o que o webservice devolve.

**Passos típicos:**

1. Criar utilizador de webservice no Moodle e gerar token com permissão para `core_enrol_get_users_courses` (e outras funções que forem necessárias).
2. Garantir que o `moodle_user_id` no AVA MJ corresponde ao ID do utilizador no Moodle.
3. Manter matrículas (`enrol`) atualizadas no Moodle conforme acesso desejado.

**Vantagem:** sem novas tabelas nem telas no AVA MJ. **Limitação:** toda a política de acesso vive no Moodle.

## Futuro B — AVA MJ como “portão” sobre a lista

Objetivo: o gestor define **no AVA MJ** quais cursos Moodle cada professor (ou escola/disciplina) pode **ver** no dashboard, mesmo que o webservice devolva mais cursos.

**Modelo de dados (sugestão):**

- Tabela de regras, por exemplo: `moodle_curso_liberacao` com campos como:
  - identificador do curso no Moodle (`courseid` ou `shortname`, conforme estabilidade desejada);
  - `escola_id` (opcional; `NULL` = todas as escolas);
  - `usuario_id` professor (opcional; `NULL` = todos os professores no âmbito da escola/regra);
  - `disciplina` ou tag opcional, se fizer sentido no produto;
  - `ativo`, datas de vigência, se necessário.

**UI gestor:**

- CRUD para criar/editar/desativar regras (filtros por escola e professor).
- Opcional: importação em lote a partir de planilha.

**Backend:**

- Após `list_user_courses`, aplicar `filtrar(cursos, regras_do_banco)` antes de passar ao template.
- Se for necessário listar cursos **em que o professor ainda não está inscrito**, seria preciso outra chamada WS (ex. listagem administrativa de cursos) com token de maior escopo — isso aumenta risco e complexidade; preferir manter **só** `core_enrol_get_users_courses` e tratar “liberação” como filtro sobre essa lista, a menos que o produto exija o contrário.

**Vantagem:** controle centralizado no AVA MJ. **Custo:** migrações, telas e manutenção das regras.

## Impressão de relatórios (docente)

Relatórios do professor podem ser abertos na mesma rota com `?imprimir=1&tipo=...` (ver `professor_relatorios_page` em `app/main.py`). A rota legada `GET /professor/relatorios/imprimir` redireciona para essa URL.
