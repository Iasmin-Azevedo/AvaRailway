# Validação de exportações — PoC Paracuru

Inventário cruzado: **módulo exigido no checklist** × **formato disponível** × **rota/ ação**.

Formatos:
- **CSV** — planilha editável (UTF-8, separador `;` onde indicado; abre no Excel)
- **PDF** — download direto ou via **Imprimir → Salvar como PDF** do navegador
- **Print** — botão Imprimir / PDF do navegador em telas de relatório

---

## Avaliação objetiva / correção de gabaritos

| Export | Rota | Status | Observação |
|--------|------|--------|------------|
| Modelo CSV importação | `GET /admin/correcao-gabaritos/modelo.csv` | OK | Template para importação manual |
| Notas por aluno CSV | `GET /admin/correcao-gabaritos/export.csv?aplicacao_id=` | OK | Após OCR ou CSV |
| Folhas gabarito PDF | `GET /admin/correcao-gabaritos/folhas.pdf?aplicacao_id=` | OK | Vários alunos por página A4 |
| Folhas por aluno ZIP | `...folhas.pdf?formato=zip` | OK | Um PDF por participação |
| Impressão caderno prova | `/professor/provas/{id}/visualizar` → Imprimir | OK | `@media print` |

---

## Relatórios SME

| Export | Rota | Status |
|--------|------|--------|
| CSV desempenho institucional | `/admin/relatorios-sme/export.csv?tipo=avaliacao_institucional` | OK |
| CSV larga escala | `?tipo=avaliacao_larga_escala` | OK |
| CSV formação BNCC | `?tipo=formacao_bncc` | OK |
| CSV avaliação semestral | `?tipo=avaliacao_semestral` | OK |
| PDF relatório | Tela relatório → **Imprimir / PDF** | OK |

Tela: [`/admin/relatorios-sme`](../app/templates/admin/relatorios_sme.html)

---

## Avaliação semestral (gestores)

| Export | Rota | Status |
|--------|------|--------|
| CSV consolidado | `GET /admin/avaliacao-semestral/export.csv` | OK |

---

## Formação BNCC

| Export | Rota | Status |
|--------|------|--------|
| Certificado PDF | `GET /admin/formacao-bncc/certificado/{participante_id}.pdf` | OK |
| CSV formação (SME) | `/admin/relatorios-sme/export.csv?tipo=formacao_bncc` | OK |

---

## Gestor escolar

| Export | Rota | Status |
|--------|------|--------|
| CSV progresso escolas | `/gestor/relatorios/export.csv?tipo=progresso_escolas` | OK |
| CSV descritores | `?tipo=descritores` | OK |
| CSV risco alunos | `?tipo=risco_alunos` | OK |
| PDF relatório | `/gestor/relatorios?tipo=...&imprimir=1` | OK |

---

## Coordenador

| Export | Rota | Status |
|--------|------|--------|
| CSV monitoramento turmas | `/coordenador/relatorios/export.csv?tipo=monitoramento_turmas` | OK |
| CSV risco turmas | `?tipo=risco_turmas` | OK |
| PDF relatório | `/coordenador/relatorios?imprimir=1` | OK |

---

## Professor

| Export | Rota | Status |
|--------|------|--------|
| CSV descritores turma | `/professor/relatorios/export.csv?tipo=descritores_turma` | OK (API) |
| CSV progresso alunos | `?tipo=alunos_progresso` | OK (API) |
| PDF relatório | `/professor/relatorios?imprimir=1` | OK |

*Nota: alguns botões CSV na UI do professor estão comentados; rotas backend existem e podem ser usadas na demo via link direto ou reativar botão se necessário.*

---

## Lacuna conhecida

| Item checklist | Situação | Posicionamento na demo |
|----------------|----------|------------------------|
| Planilha **XLSX** | Não implementado | CSV editável atende o requisito funcional |
| Gráficos exportáveis | Gráficos na tela; export via print/PDF ou CSV dos dados | Mostrar gráfico na tela + CSV de backing |

---

## Checklist rápido pré-demo (exports)

- [ ] Baixar `export.csv` de uma aplicação com notas
- [ ] Baixar folhas PDF de uma aplicação
- [ ] Baixar um CSV em `/admin/relatorios-sme`
- [ ] Baixar certificado PDF em formação BNCC
- [ ] Imprimir um relatório gestor como PDF

---

## Teste automatizado de rotas (smoke)

As rotas acima são registradas em `app/routers/licitacao_router.py` e `app/main.py`. Testes de serviço em `tests/test_licitacao_modules.py` cobrem fluxo de notas e formação.
