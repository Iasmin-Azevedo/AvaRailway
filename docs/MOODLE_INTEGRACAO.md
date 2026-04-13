# Integração Moodle (AVA MJ)

## Estado atual

- **Configuração:** `MOODLE_URL`, `MOODLE_TOKEN` e, opcionalmente, `MOODLE_AUTO_ENROL_ON_ASSIGN` e `MOODLE_STUDENT_ROLE_ID` em `.env` (ver `app/core/config.py` e [MOODLE_CAPACITACAO_GESTOR.md](MOODLE_CAPACITACAO_GESTOR.md)).
- **Vínculo do utilizador:** campo `moodle_user_id` no modelo `Usuario`, editável no admin (`usuario_form.html`). Necessário para **inscrição automática** no Moodle ao atribuir curso (`MOODLE_AUTO_ENROL_ON_ASSIGN=true`).
- **Catálogo:** o gestor sincroniza cursos do Moodle para a tabela `moodle_course_catalog` (webservice `core_course_get_courses`). O curso do site com `id == 1` é ignorado na sincronização.
- **Liberação:** o gestor atribui cursos a professores em **Cursos Moodle (capacitação)** (`/gestor/moodle/cursos`); as regras ficam em `gestor_professor_moodle_course` (escopo por escolas do gestor, professores com turma nessas escolas).
- **Painel docente:** o cartão **Cursos de formação (Moodle)** mostra **apenas** cursos atribuídos pelo gestor (com metadados do catálogo), com link `MOODLE_URL/course/view.php?id=...`. Já **não** se usa `core_enrol_get_users_courses` para essa lista.

Guia passo a passo (Moodle + `.env` + token + funções): **[MOODLE_CAPACITACAO_GESTOR.md](MOODLE_CAPACITACAO_GESTOR.md)**.

## Alternativa: gestão só no Moodle

Se preferir não usar o catálogo e as atribuições no AVA MJ, pode manter matrículas apenas no Moodle; neste caso o fluxo “portão” do AVA não se aplica — o produto foi desenhado para o gestor controlar a lista visível no dashboard a partir do AVA.

## Impressão de relatórios (docente)

Relatórios do professor podem ser abertos na mesma rota com `?imprimir=1&tipo=...` (ver `professor_relatorios_page` em `app/main.py`). A rota legada `GET /professor/relatorios/imprimir` redireciona para essa URL.
