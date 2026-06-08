# Posicionamento mobile — PoC Paracuru

## Decisão oficial para a demonstração

**O AVA MJ na PoC Paracuru é apresentado como plataforma web responsiva**, acessível por navegador em desktop, tablet e smartphone (iOS e Android).

**Não há aplicativo nativo** publicado na App Store ou Google Play nesta fase da PoC.

---

## Como atender o item do checklist na proposta

| Texto do checklist | Como demonstrar na PoC |
|--------------------|------------------------|
| Aplicativo iOS e Android | Acesso via **Safari (iOS)** e **Chrome (Android)** |
| Login | `/login` em viewport mobile |
| Visualização cursos/aulas | `/aluno`, trilhas, H5P, provas |
| Responsividade | Layout adaptativo + menu mobile + touch targets ≥ 44px |

**Frase sugerida na apresentação:**

> "O acesso móvel é feito pela plataforma web responsiva, compatível com iOS e Android, sem necessidade de instalação de app nativo. Isso reduz custo de manutenção e permite atualizações imediatas para toda a rede."

---

## Evidências técnicas no produto

- CSS responsivo em `app/templates/static/css/style.css` (`@media max-width`, safe-area, touch targets)
- Menu mobile e acessibilidade (A+/contraste) em `base_dashboard.html` e telas aluno
- Telas aluno otimizadas: `aluno/dashboard.html`, `aluno/trilhas.html`, `aluno/prova.html`
- Roteiro de demo mobile em [`ROTEIRO_POC_PARACURU.md`](./ROTEIRO_POC_PARACURU.md) — seção **Aluno no celular**

---

## PWA (opcional futuro)

A arquitetura atual (FastAPI + templates + static) **permite evolução para PWA** (manifest + service worker) sem reescrever o backend. Isso **não é requisito** para fechar a PoC atual.

---

## O que **não** prometer na demo

- App nativo offline completo
- Push notifications nativas (iOS/Android)
- Publicação em lojas de aplicativos

---

## Roteiro mobile (5 min)

1. Abrir `/login` no celular (ou DevTools → iPhone/Android).
2. Entrar como aluno demo.
3. Navegar trilha Matemática → atividade ou prova.
4. Mostrar menu hambúrguer e legibilidade em tela pequena.
5. (Opcional) Abrir chamado de suporte em `/aluno/suporte`.

---

## Referência cruzada

- Matriz checklist: [`CHECKLIST_POC_MATRIZ.md`](./CHECKLIST_POC_MATRIZ.md) — item "App iOS/Android" marcado como **PARCIAL** com esta justificativa.
