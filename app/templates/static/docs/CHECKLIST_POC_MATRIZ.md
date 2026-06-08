# Matriz checklist PoC Paracuru — evidências

Documento de fechamento: cada item do checklist oficial mapeado para **URL**, **ação de demo** e **export/evidência**.

Legenda de status:
- **OK** — demonstrável hoje
- **PARCIAL** — funciona com ressalva documentada
- **N/A PoC** — fora do escopo desta PoC (com alternativa apresentável)

---

## 3. Sistema / funcionalidade — demonstração mínima

| Check | Item | Status | URL / tela | Como demonstrar | Export / evidência |
|-------|------|--------|------------|-----------------|-------------------|
| ☐→✅ | Monitoramento de gestão (SME) | OK | `/admin/gestao-integrada` | KPIs rede, três módulos estratégicos | `/admin/relatorios-sme` (CSV) |
| ☐→✅ | Correção avaliação larga escala | OK | `/admin/correcao-gabaritos` | Banco → prova → aplicação → OCR/CSV → notas | PDF folhas, CSV notas |
| ☐→✅ | BNCC Computação | OK | `/admin/formacao-bncc` | Programas, turmas, progresso, certificado | PDF certificado |
| ☐→✅ | Aulas presenciais/remotas | OK | `/aluno/matematica`, `/coordenador/lives` | Trilhas, H5P, live classroom | Relatórios participação |
| ☐→✅ | Sala de aula e avaliação | OK | `/professor`, `/professor/provas` | Turmas, provas, aplicações, notas | Impressão prova, CSV |
| ☐→⚠️ | App iOS/Android | PARCIAL | `/login` (mobile) | **Web responsivo** no navegador móvel | Ver `MOBILE_POSICIONAMENTO_POC.md` |
| ☐→✅ | Gestão administrativa | OK | `/admin`, `/admin/usuarios` | Usuários, perfis, escolas, turmas | CSV relatórios SME |

---

## 4. Perfis de usuários

| Perfil | Status | URL entrada | O que mostrar |
|--------|--------|-------------|---------------|
| Gestor SME | OK | `/admin/gestao-integrada` | Painel rede, relatórios, correção, semestral, BNCC |
| Gestor escolar | OK | `/gestor` | Escola, turmas, proficiência, alertas, relatórios |
| Professor | OK | `/professor` | Provas, aplicações, H5P, formação BNCC |
| Aluno | OK | `/aluno` | Trilhas, provas, atividades, progresso (celular) |
| Coordenador | OK | `/coordenador` | Turma, lives, formação, relatórios |

**Logins demo:** ver [`ROTEIRO_POC_PARACURU.md`](./ROTEIRO_POC_PARACURU.md) (seed padrão: admin@avajmj.com, gestor@avamj.com, etc.).

---

## 5. Demonstração do sistema de avaliação

| Funcionalidade | Status | URL | Demo | Export |
|----------------|--------|-----|------|--------|
| Gestão unidades | OK | `/admin/escolas` | Cadastrar/listar escolas | — |
| Lotação alunos | OK | `/admin/turmas`, `/admin/usuarios` | Aluno vinculado à turma/escola | — |
| Geração gabaritos | OK | `/admin/correcao-gabaritos` | **Gabarito completo** ou por aluno (ZIP) | PDF / ZIP |
| Leitor múltiplos gabaritos | OK | Mesma tela → upload OCR | Preview editável → confirmar | — |
| Identificação aluno/turma | OK | QR + participação # | Preview mostra aluno e #participação | — |
| Geração notas | OK | Após import OCR/CSV | Resultados por turma/aluno | `/admin/correcao-gabaritos/export.csv` |
| Exportação resultados | OK | `/admin/relatorios-sme` | CSV + impressão/PDF relatórios | CSV, Imprimir/PDF |

**Validação OCR:** [`OCR_VALIDACAO_LOTE_POC.md`](./OCR_VALIDACAO_LOTE_POC.md) — 4 folhas reais 100%; lote ampliado 28 folhas ~95,5%.

---

## 6. Plataforma de Gestão Escolar — avaliação de gestores

| Módulo | Status | URL | Export |
|--------|--------|-----|--------|
| Avaliação semestral gestores | OK | `/admin/avaliacao-semestral` | `/admin/avaliacao-semestral/export.csv` |
| Avaliação coordenadores | OK | `/gestor/avaliacao-semestral`, `/coordenador` | CSV SME `tipo=avaliacao_semestral` |
| Avaliação PDT | OK | Perfil professor (`TeacherRole.PDT`) | Mesmo ciclo semestral |
| Painel SME | OK | `/admin/gestao-integrada`, `/admin/relatorios-sme` | CSV consolidado |
| Relatórios consolidados | OK | `/admin/relatorios-sme` | 4 tipos CSV + print |
| Capacitação + devolutiva | OK | `/admin/devolutiva-poc`, `/admin/formacao-bncc` | PDF certificado, devolutiva texto |

---

## 7. Correção de gabaritos em larga escala

| Item | Status | URL | Export |
|------|--------|-----|--------|
| Correção eficiente | OK | `/admin/correcao-gabaritos` | — |
| Resultados gerais | OK | `/admin/relatorios-sme?tipo=avaliacao_larga_escala` | CSV |
| Resultados por turma | OK | `/professor/aplicacoes-prova`, gestor avaliações | CSV / print |
| Resultados por aluno | OK | Notas individuais na aplicação | `export.csv` por aplicação |
| Exportação | OK | Vários pontos acima | CSV + PDF |
| Devolutiva pedagógica | OK | `/admin/devolutiva-poc` | Narrativa no roteiro |

---

## 8. Plataforma aulas presenciais e remotas

| Funcionalidade | Status | URL | Export |
|----------------|--------|-----|--------|
| AVA / cursos | OK | `/admin/cursos`, `/aluno/matematica` | — |
| Conteúdos digitais | OK | H5P, trilhas, PDFs | — |
| Suporte técnico | OK | `/aluno/suporte`, `/admin/suporte` | Chamados |
| Acesso remoto | OK | Login multi-perfil | — |
| Gestão turmas | OK | `/admin/turmas`, professor turmas | CSV gestor |
| Certificação | OK | `/admin/formacao-bncc` | PDF certificado |
| Relatórios | OK | Por perfil (`/gestor/relatorios`, etc.) | CSV + print |

---

## Itens com ressalva (falar na demo)

1. **App nativo iOS/Android:** não há app nas lojas; demonstrar **PWA/responsivo** (ver doc mobile).
2. **Planilha editável:** entregue como **CSV UTF-8** (abre no Excel/LibreOffice); não há XLSX nativo.
3. **OCR:** validado em lote; contingência = correção manual no preview + CSV.

---

## Documentos relacionados

- [`ROTEIRO_POC_PARACURU.md`](./ROTEIRO_POC_PARACURU.md) — roteiro executivo por perfil
- [`EXPORTS_POC_VALIDACAO.md`](./EXPORTS_POC_VALIDACAO.md) — inventário de exports
- [`MOBILE_POSICIONAMENTO_POC.md`](./MOBILE_POSICIONAMENTO_POC.md) — posicionamento mobile
- [`OCR_VALIDACAO_LOTE_POC.md`](./OCR_VALIDACAO_LOTE_POC.md) — validação OCR
