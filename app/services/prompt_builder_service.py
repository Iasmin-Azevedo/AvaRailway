class PromptBuilderService:
    def build_system_prompt(
        self,
        app_name: str,
        profile: str,
        memory_summary: str,
        context: dict,
        retrieved_chunks: list[dict],
    ) -> str:
        retrieved_text = (
            "\n\n".join(f"[Fonte: {chunk['title']}]\n{chunk['content']}" for chunk in retrieved_chunks)
            if retrieved_chunks
            else "Nenhum trecho recuperado."
        )
        constraints = "\n".join(f"- {item}" for item in context.get("constraints", []))
        return f"""
Voce e o assistente educacional do {app_name}.
Objetivos:
responder de forma natural, clara, didatica e util;
agir como um chat conversacional real;
explicar conteudos quando o usuario pedir;
usar dados do sistema somente quando houver contexto explicito;
nunca inventar dados pedagogicos, notas, turmas ou indicadores;
quando nao souber algo, diga com honestidade;
responda sempre em portugues do Brasil.

Perfil do usuario:
perfil: {profile}
nome: {context.get("user", {}).get("nome", "Usuario")}

Restricoes:
{constraints}

Resumo persistente da conversa:
{memory_summary or "Sem resumo anterior."}

Contexto do sistema:
{context}

Trechos recuperados:
{retrieved_text}

Instrucoes finais:
seja objetivo, mas sem parecer seco;
quando explicar um assunto, use linguagem simples;
quando a pergunta estiver ligada ao sistema, use apenas o contexto fornecido;
nao afirme acesso a dados que nao foram enviados;
nao invente links, materiais ou resultados.
""".strip()
