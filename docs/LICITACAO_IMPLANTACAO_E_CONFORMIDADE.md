# Licitação: Implantação e Conformidade

## Objetivo
Este documento consolida a forma recomendada de operação do AVA MJ para atendimento à licitação, com foco em implantação, hospedagem, backup, LGPD e auditoria.

## Implantação
- Prazo-alvo operacional: até 30 dias corridos após assinatura.
- Ordem recomendada:
  1. Configuração de infraestrutura e `.env`.
  2. Banco e migrações (`alembic upgrade head`).
  3. Cadastro de escolas, turmas, usuários e vínculos.
  4. Publicação dos módulos da licitação:
     - avaliação institucional;
     - correção de gabaritos;
     - formação BNCC Computação.
  5. Teste assistido com SME.
  6. Capacitação presencial e devolutiva inicial.

## Hospedagem
- Backend preparado para operação em nuvem com `DATABASE_URL`, `ALLOWED_ORIGINS`, `COOKIE_SECURE` e diretórios externos para conteúdo H5P e uploads.
- Recomenda-se ambiente com HTTPS, banco gerenciado e rotina de monitoramento.
- Conteúdos H5P e uploads de usuários devem permanecer fora do ciclo de deploy quando a infraestrutura permitir.

## Backup e restauração
- Política mínima recomendada:
  - backup diário do banco;
  - retenção semanal e mensal;
  - verificação periódica de restauração.
- Itens críticos de backup:
  - banco transacional;
  - diretório de H5P;
  - uploads de usuários;
  - documentação operacional e arquivos de importação relevantes.

## LGPD
- O sistema opera com acesso por perfil e escopo.
- O tratamento de dados deve respeitar:
  - minimização de dados;
  - controle de acesso por necessidade;
  - auditoria de ações críticas;
  - retenção coerente com a finalidade administrativa e pedagógica.

## Auditoria
- Eventos mínimos recomendados:
  - login e refresh de sessão;
  - criação e atualização de ciclos/instrumentos/aplicações;
  - importação de gabaritos;
  - criação de programas e turmas de formação;
  - atualização de devolutivas e progresso.

## Evidências para aceite operacional
- Usuários com acesso por perfil.
- Painel SME funcional.
- Exportação em CSV e impressão/PDF.
- Fluxo de avaliação institucional operacional.
- Fluxo de correção por planilha operacional.
- Formação BNCC com turmas, participantes e devolutiva.

## Pacote de fechamento PoC Paracuru
- [`CHECKLIST_POC_MATRIZ.md`](./CHECKLIST_POC_MATRIZ.md) — checklist × evidências (URL, demo, export).
- [`ROTEIRO_POC_PARACURU.md`](./ROTEIRO_POC_PARACURU.md) — roteiro executivo por perfil (45–60 min).
- [`EXPORTS_POC_VALIDACAO.md`](./EXPORTS_POC_VALIDACAO.md) — inventário de CSV/PDF/impressão.
- [`OCR_VALIDACAO_LOTE_POC.md`](./OCR_VALIDACAO_LOTE_POC.md) — validação OCR em lote real.
- [`MOBILE_POSICIONAMENTO_POC.md`](./MOBILE_POSICIONAMENTO_POC.md) — web responsivo vs app nativo.
