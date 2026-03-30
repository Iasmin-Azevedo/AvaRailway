# Fundamentação Técnica e Diretrizes do Chatbot

## Finalidade

Este documento registra a fundamentação técnica adotada para orientar a organização do backend e a evolução do módulo de chatbot do AVA MJ. O objetivo é manter o código alinhado a referências consolidadas de arquitetura, orientação a objetos, integração de dados e uso responsável de modelos de linguagem.

## Referências para o backend

### Clean Architecture

Como base para a separação entre rotas, serviços, repositórios, modelos e integrações, o projeto se apoia nos princípios descritos por Robert C. Martin em *Clean Architecture*. Essa referência sustenta decisões como isolamento da regra de negócio, independência de framework e redução de acoplamento estrutural.

Referência:
- Robert C. Martin. *Clean Architecture: A Craftsman's Guide to Software Structure and Design*. Pearson, 2017.

### Architecture Patterns with Python

Para a implementação prática em Python, o projeto se aproxima das ideias apresentadas por Harry Percival e Bob Gregory em *Architecture Patterns with Python*. Essa obra fortalece o uso de repositórios, serviços de aplicação, testes e organização orientada ao domínio.

Referência:
- Harry Percival; Bob Gregory. *Architecture Patterns with Python*. O'Reilly Media, 2020.

### Designing Data-Intensive Applications

As decisões relacionadas a persistência própria, sincronização com sistemas externos, confiabilidade e evolução da base de dados encontram apoio em *Designing Data-Intensive Applications*, de Martin Kleppmann.

Referência:
- Martin Kleppmann. *Designing Data-Intensive Applications*. O'Reilly Media, 2017.

## Referências para orientação a objetos e domínio

### Domain-Driven Design

A modelagem das entidades pedagógicas do sistema, como aluno, avaliação, descritor, trilha e interação, pode ser justificada por princípios de modelagem orientada ao domínio.

Referência:
- Eric Evans. *Domain-Driven Design: Tackling Complexity in the Heart of Software*. Addison-Wesley, 2003.

### Object-Oriented Analysis and Design with Applications

Como apoio conceitual para responsabilidade de classes, composição do domínio e clareza estrutural, também é válida a referência clássica de Grady Booch.

Referência:
- Grady Booch. *Object-Oriented Analysis and Design with Applications*. Addison-Wesley, 2007.

## Diretrizes de código adotadas

- O backend deve manter padrão profissional e objetivo.
- Não devem ser utilizados emojis em código, comentários ou mensagens técnicas internas.
- Comentários só devem existir quando forem necessários para esclarecer intenção não evidente.
- Quando comentários forem necessários, devem ser curtos, técnicos e diretamente ligados ao comportamento implementado.
- A lógica já validada do sistema deve ser preservada em refatorações de organização.
- Alterações estruturais devem priorizar legibilidade, rastreabilidade e manutenção sem quebrar requisitos existentes.

## Direção técnica para o chatbot

O chatbot do AVA MJ deve evoluir como um assistente educacional seguro, contextual e orientado por evidências. A melhoria de qualidade não depende apenas do modelo de linguagem, mas da combinação entre contexto pedagógico, recuperação de conteúdo, guardrails de segurança e rastreabilidade das respostas.

### Estratégia recomendada

- uso de LLM para geração da resposta final;
- uso de RAG para recuperar conteúdos reais antes de responder;
- uso de contexto pedagógico por perfil, série e desempenho;
- uso de fontes rastreáveis para reduzir respostas sem base;
- uso de guardrails para bloquear conteúdos ofensivos, perigosos ou incompatíveis com os direitos humanos;
- uso de regras explícitas para impedir qualquer tentativa de alterar o sistema por conversa.

## Base teórica para o uso de RAG e LLMs

### Retrieval-Augmented Generation

O uso de RAG é recomendado para reduzir alucinações e aumentar aderência factual em respostas baseadas em conhecimento específico do domínio.

Referência:
- Patrick Lewis et al. "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks". *NeurIPS 2020*.

### LLMs em contexto educacional

O uso de modelos de linguagem em ambientes educacionais deve considerar adequação pedagógica, segurança, faixa etária, explicabilidade e alinhamento com o contexto de aprendizagem.

Referências:
- "Evaluating large language models in analysing classroom dialogue". *npj Science of Learning*, 2024.
- "Large language models challenge the future of higher education". *Nature Machine Intelligence*, 2023.
- "Classroom AI: large language models as grade-specific teachers". *npj Artificial Intelligence*, 2026.

## Aplicação prática no AVA MJ

No contexto do AVA MJ, a abordagem mais consistente para o chatbot envolve:

- recuperar materiais do Moodle e conteúdos próprios da plataforma;
- considerar dados pedagógicos reais do aluno e do professor;
- adaptar linguagem conforme o perfil e o ano escolar;
- bloquear mensagens ofensivas ou perigosas;
- impedir uso do chat como canal de alteração administrativa;
- registrar fontes de apoio utilizadas na resposta;
- preservar histórico e memória resumida para continuidade da conversa.

## Síntese

Com essa fundamentação, o backend e o chatbot deixam de ser apenas uma implementação funcional e passam a ter uma base técnica explícita, alinhada a literatura reconhecida de arquitetura de software, orientação a objetos, integração de dados e uso responsável de LLMs em contexto educacional.
