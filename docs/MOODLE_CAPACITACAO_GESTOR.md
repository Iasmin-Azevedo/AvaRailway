# Moodle: capacitação docente (catálogo + liberação pelo gestor)

Este guia explica como configurar o Moodle e o ficheiro `.env` do AVA MJ para:

1. **Sincronizar** a lista de cursos do Moodle para a base do AVA MJ.
2. O **gestor** atribuir cursos a professores no painel **Cursos Moodle (capacitação)** (`/gestor/moodle/cursos`).
3. O **professor** ver apenas os cursos atribuídos, no cartão **Cursos de formação (Moodle)** do painel.

Documentação geral do produto: [MOODLE_INTEGRACAO.md](MOODLE_INTEGRACAO.md).

---

## Variáveis no `.env`

| Variável | Obrigatório | Descrição |
|----------|-------------|-----------|
| `MOODLE_URL` | Sim | URL base do Moodle, **sem** barra final. Ex.: `https://moodle.escola.edu.br` |
| `MOODLE_TOKEN` | Sim | Token do webservice (utilizador técnico no Moodle; ver secção abaixo). |
| `MOODLE_AUTO_ENROL_ON_ASSIGN` | Não | `false` (padrão) ou `true`. Se `true`, ao atribuir um curso a um professor, o AVA tenta **inscrevê-lo como aluno** no curso no Moodle (função `enrol_manual_enrol_users`). Requer `moodle_user_id` preenchido no utilizador professor (cadastro no admin). |
| `MOODLE_STUDENT_ROLE_ID` | Não | ID numérico do papel **Aluno** no Moodle. Muitas instalações usam **5**; **confirme na sua instalação** (ver secção “Papel de aluno”). |

Exemplo (valores fictícios):

```env
MOODLE_URL=https://moodle.exemplo.edu.br
MOODLE_TOKEN=a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6
MOODLE_AUTO_ENROL_ON_ASSIGN=false
MOODLE_STUDENT_ROLE_ID=5
```

**Segurança:** não commite o `.env`. Em produção use HTTPS no Moodle e no AVA MJ. O token tem poderes amplos conforme as funções que associar ao serviço externo.

---

## Onde obter `MOODLE_URL`

- É o endereço que os utilizadores usam para abrir o Moodle no browser (página inicial do site).
- No `.env`, use apenas a origem: `https://dominio` (sem `/login` e sem barra no fim).

---

## Onde obter `MOODLE_TOKEN` (e configurar o webservice)

Os passos variam ligeiramente entre Moodle 4.x e 4.4+, mas a lógica é a mesma. Referências oficiais (inglês):

- [Web services](https://docs.moodle.org/en/Web_services)
- [Creating a web service](https://docs.moodle.org/en/Creating_a_web_service)
- [List of web service functions](https://docs.moodle.org/dev/Web_service_API_functions) (procurar `core_course_get_courses`, `enrol_manual_enrol_users`)

### 1. Ativar protocolos e webservices

1. Entre como **administrador** no Moodle.
2. **Administração do site** → **Geral** → **Funcionalidades avançadas** (ou **Experimental**): ative **Web services** (se aplicável à sua versão).
3. **Administração do site** → **Servidor** → **Web services** → **Overview**: confirme que os webservices estão ativos.
4. Em **Manage protocols**, ative **REST** (é o que o AVA MJ usa: `.../webservice/rest/server.php`).

### 2. Criar um utilizador dedicado (recomendado)

- Crie um utilizador, por exemplo `ws_avamj`, com email válido.
- Atribua um papel que consiga **listar cursos** (muitas redes usam **Gestor da plataforma** ou política mínima definida pela TI). O token herda as permissões deste utilizador **e** as funções que adicionar ao serviço externo.

### 3. Criar um serviço externo e adicionar funções

1. **Administração do site** → **Servidor** → **Web services** → **External services** → **Add**.
2. Nome: por exemplo `AVA MJ`.
3. Marque **Enabled** e, se existir a opção, **Authorized users only** (recomendado).
4. Em **Functions**, adicione pelo menos:
   - **`core_course_get_courses`** — obrigatória para sincronizar o catálogo no AVA MJ.
5. Se usar `MOODLE_AUTO_ENROL_ON_ASSIGN=true`, adicione também:
   - **`enrol_manual_enrol_users`** — inscrição manual como aluno no curso.

### 4. Autorizar o utilizador no serviço (se “Authorized users only”)

- Na edição do serviço externo, secção **Authorised users** (ou equivalente), adicione o utilizador `ws_avamj`.

### 5. Gerar o token

1. **Administração do site** → **Utilizadores** → **Tokens** (ou **Server → Web services → Manage tokens**).
2. Crie um token para o utilizador `ws_avamj` associado ao serviço externo **AVA MJ**.
3. Copie o token e coloque em `MOODLE_TOKEN` no `.env` do AVA MJ.

Em algumas versões o caminho é: **Administração do site** → **Plugins** → **Web services** → **Manage tokens**.

---

## Papel de aluno (`MOODLE_STUDENT_ROLE_ID`)

O valor **5** é comum para o papel **student** em instalações padrão, **não é garantido**.

Para confirmar no Moodle:

- **Administração do site** → **Utilizadores** → **Permissões** → **Definir papéis**: veja o ID na URL ao editar o papel (`.../admin/roles/manage.php?action=view&roleid=X`), ou
- Consulta à base de dados: tabela `mdl_role`, colunas `id` e `shortname` (procurar `student`).

Ajuste `MOODLE_STUDENT_ROLE_ID` no `.env` se for diferente.

---

## Fluxo no AVA MJ

1. Administrador configura `.env` e reinicia a API.
2. Executa migrações: `alembic upgrade head` (cria tabelas `moodle_course_catalog` e `gestor_professor_moodle_course`).
3. **Gestor** acede a **Cursos Moodle (capacitação)** e clica em **Sincronizar agora**.
4. **Gestor** atribui curso + professor.
5. **Professor** vê os cursos no painel; o link abre `MOODLE_URL/course/view.php?id=...` num novo separador.

O professor continua a precisar de **conta no Moodle** e **permissão de acesso ao curso** para concluir atividades lá dentro, a menos que use apenas o catálogo como referência. Com `MOODLE_AUTO_ENROL_ON_ASSIGN=true` e `moodle_user_id` correto, o AVA tenta inscrever o professor como **aluno** na atribuição.

---

## Resolução de problemas

| Sintoma | Verificar |
|---------|-----------|
| Erro ao sincronizar | `MOODLE_URL`, `MOODLE_TOKEN`, função `core_course_get_courses` no serviço, utilizador autorizado, REST ativo. |
| Lista vazia após sync | Cursos ocultos no Moodle podem vir com `visible=0`; o AVA lista apenas cursos com `visible` no catálogo para atribuição. Confirme no Moodle se há cursos visíveis. |
| Inscrição automática falha | Função `enrol_manual_enrol_users`, método de inscrição **manual** ativo no curso, `moodle_user_id` do professor, `MOODLE_STUDENT_ROLE_ID` correto. |

---

## Comando de migração

Na raiz do projeto:

```bash
alembic upgrade head
```

(Use o mesmo `DATABASE_URL` do `.env`.)
