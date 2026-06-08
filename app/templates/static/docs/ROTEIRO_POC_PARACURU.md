# Roteiro de demonstração — PoC Paracuru/CE

**Duração total:** 45–60 minutos  
**Dispositivos:** desktop (SME, gestor, professor) + celular (aluno)  
**Documentos de apoio:** [`CHECKLIST_POC_MATRIZ.md`](./CHECKLIST_POC_MATRIZ.md) · [`EXPORTS_POC_VALIDACAO.md`](./EXPORTS_POC_VALIDACAO.md) · [`MOBILE_POSICIONAMENTO_POC.md`](./MOBILE_POSICIONAMENTO_POC.md) · [`OCR_VALIDACAO_LOTE_POC.md`](./OCR_VALIDACAO_LOTE_POC.md)

---

## Abertura (2 min)

**Mensagem:** "O AVA MJ integra monitoramento da SME, correção em larga escala, formação BNCC e ambiente virtual — com dados que viram decisão pedagógica, não só planilha."

---

## 1. Secretaria / SME (15 min)

| Tempo | Passo | URL | O que mostrar | Fala pedagógica |
|-------|-------|-----|---------------|-----------------|
| 2 min | Painel integrado | `/admin/gestao-integrada` | KPIs rede, três módulos | "Visão única da rede: avaliação, larga escala e formação." |
| 2 min | Escolas e turmas | `/admin/escolas`, `/admin/turmas` | Cadastro e vínculos | "Cada resultado pode ser lido por escola e turma." |
| 6 min | Correção larga escala | `/admin/correcao-gabaritos` | Aplicação → **Gabarito completo** → upload OCR → preview → confirmar | "Correção em massa com identificação automática do aluno via QR." |
| 2 min | Export notas | Botão **Exportar notas** | CSV por aluno | "Planilha editável para prestação de contas e análise." |
| 2 min | Relatórios SME | `/admin/relatorios-sme` | CSV + imprimir | "Consolidado para decisão da Secretaria." |
| 1 min | Avaliação semestral | `/admin/avaliacao-semestral` | Ciclo e export CSV | "Gestores e coordenadores avaliados no mesmo ecossistema." |

**Contingência OCR:** se alguma alternativa não vier marcada no preview, ajustar nos botões A–E e confirmar (não interromper a demo). Fallback: importação CSV.

---

## 2. Gestor escolar (10 min)

| Tempo | Passo | URL | O que mostrar | Fala pedagógica |
|-------|-------|-----|---------------|-----------------|
| 3 min | Painel | `/gestor` | Indicadores da escola | "O gestor vê a unidade, não só a rede." |
| 2 min | Proficiência / alertas | `/gestor/proficiencia`, `/gestor/alertas` | Engajamento e risco | "Antecipação de intervenção." |
| 3 min | Relatórios | `/gestor/relatorios` | CSV + imprimir PDF | "Devolutiva para equipe pedagógica da escola." |
| 2 min | Semestral | `/gestor/avaliacao-semestral` | Preenchimento / devolutiva | "Ciclo formativo dos gestores escolares." |

Login sugerido: `gestor@avamj.com`

---

## 3. Coordenador (5 min)

| Tempo | Passo | URL | Fala pedagógica |
|-------|-------|-----|-----------------|
| 2 min | Painel | `/coordenador` | "Monitoramento das turmas sob sua coordenação." |
| 2 min | Análise turma | `/coordenador/turmas/{id}/analise` | "Onde a turma precisa de reforço." |
| 1 min | Lives / BNCC | `/coordenador/lives`, formação BNCC | "Presencial + remoto no mesmo ambiente." |

Login: `coordenador@avamj.com`

---

## 4. Professor (10 min)

| Tempo | Passo | URL | Fala pedagógica |
|-------|-------|-----|-----------------|
| 2 min | Painel | `/professor` | "Turmas, provas e formação docente." |
| 4 min | Provas | `/professor/provas` → Ver prova → Aplicar à turma | "Do banco à aplicação na turma." |
| 2 min | Notas | `/professor/aplicacoes-prova` | "Retorno por aluno após correção." |
| 2 min | H5P / formação | `/professor/atividades`, `/professor/formacao-bncc` | "Conteúdo interativo e BNCC computação." |

Login: `professor@avamj.com`

---

## 5. Aluno no celular (10 min)

| Tempo | Passo | URL | Fala pedagógica |
|-------|-------|-----|-----------------|
| 1 min | Login mobile | `/login` | "Acesso iOS/Android via navegador responsivo — sem app nativo na PoC." |
| 4 min | Trilha | `/aluno/matematica` | "Jornada gamificada e missões." |
| 3 min | Prova / H5P | Prova agendada ou `/aluno/atividade/{id}` | "Avaliação e prática no mesmo fluxo." |
| 2 min | Suporte (opcional) | `/aluno/suporte` | "Canal de atendimento ao usuário." |

Login: aluno seed ou conta demo cadastrada.

**Mobile:** ver [`MOBILE_POSICIONAMENTO_POC.md`](./MOBILE_POSICIONAMENTO_POC.md).

---

## 6. BNCC, certificação e devolutiva (5 min — pode ser dentro do bloco SME)

| Passo | URL | O que mostrar |
|-------|-----|---------------|
| Formação | `/admin/formacao-bncc` | Programas, turmas, progresso |
| Certificado | Botão PDF por participante | Emissão automática ao concluir |
| Devolutiva PoC | `/admin/devolutiva-poc` | Narrativa pós-capacitação para SME |

**Fala:** "A plataforma fecha o ciclo: formação → certificação → devolutiva para gestão."

---

## Sequência de contingência (cola rápida)

| Problema | Ação |
|----------|------|
| OCR não marca alternativa | Corrigir no preview (botões A–E) → Confirmar |
| QR não lido | Informar participação manual no preview |
| OCR indisponível (zbar) | Importar CSV modelo |
| Tela lenta | Pular para aplicação já corrigida + export CSV |
| Pergunta sobre app nativo | Web responsiva; ver doc mobile |
| Dados vazios na demo | Rodar `python scripts/seed_demo_paracuru.py` antes da apresentação |

## Suporte técnico (2 min — opcional)

| Passo | URL | Ação |
|-------|-----|------|
| Abrir chamado | `/suporte/chamado` | Criar ticket como aluno/gestor |
| Atender | `/admin/suporte` | Responder e marcar resolvido |

---

## Checklist rápido (marcar antes da demo)

- [x] Gestão unidades e lotação
- [x] Geração folhas PDF + QR
- [x] Leitor OCR múltiplas folhas (validado — ver OCR_VALIDACAO_LOTE_POC.md)
- [x] Notas escola / turma / aluno + export CSV
- [x] Avaliação semestral gestores/coordenadores/PDT
- [x] BNCC + certificado + devolutiva
- [x] Responsivo iOS/Android (web; sem app nativo)

---

## Logins padrão (seed)

| Perfil | E-mail | Senha (seed) |
|--------|--------|--------------|
| Admin/SME | admin@avajmj.com | (ver seed / `.env`) |
| Gestor | gestor@avamj.com | idem |
| Coordenador | coordenador@avamj.com | idem |
| Professor | professor@avamj.com | idem |

---

## Encerramento (2 min)

**Mensagem:** "Demonstramos gestão consolidada, correção em larga escala com OCR, formação BNCC com certificado, perfis da rede e acesso mobile — com exportação para prestação de contas e devolutiva pedagógica."
