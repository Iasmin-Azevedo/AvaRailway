import httpx

from app.core.config import settings
from app.schemas.chat_schema import IAChatPayload, IAChatResult


class IAService:
    GENERIC_MARKERS = (
        "estou pronto para ajudar",
        "mande a pergunta em uma frase",
        "posso te ajudar com base no seu contexto atual",
        "se voce quiser",
        "eu respondo de forma objetiva",
    )

    def gerar_feedback(self, acertos: int, total: int):
        percentual = (acertos / total) * 100 if total else 0
        if percentual == 100:
            return "Parabens! Voce dominou esse conteudo completamente."
        if percentual >= 70:
            return "Muito bom! Voce entendeu a maior parte, mas revise os erros."
        return "Parece que voce teve dificuldades. Que tal revisarmos o material base?"

    async def chat(self, payload: IAChatPayload | dict) -> IAChatResult:
        if isinstance(payload, dict):
            payload = IAChatPayload(**payload)

        messages = [{"role": "system", "content": payload.system_prompt}]
        for item in payload.history:
            role = "assistant" if item["sender"] == "assistant" else "user"
            messages.append({"role": role, "content": item["message_text"]})
        messages.append({"role": "user", "content": payload.question})

        request_body = {
            "model": settings.OLLAMA_MODEL,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0.3, "num_predict": 500},
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{settings.OLLAMA_BASE_URL}/api/chat",
                    json=request_body,
                )
                response.raise_for_status()
                data = response.json()
            answer = data.get("message", {}).get("content", "").strip()
        except Exception:
            answer = self._fallback_answer(payload)

        if not answer:
            answer = "Nao consegui gerar uma resposta agora. Tente reformular a pergunta."

        return IAChatResult(
            answer=answer,
            used_context=[chunk["title"] for chunk in payload.retrieved_chunks],
        )

    def is_low_information_answer(self, answer: str) -> bool:
        normalized = " ".join(answer.lower().split())
        if len(normalized) < 40:
            return True
        return any(marker in normalized for marker in self.GENERIC_MARKERS)

    def _fallback_answer(self, payload: IAChatPayload) -> str:
        if payload.retrieved_chunks:
            top = payload.retrieved_chunks[0]
            response = f"{top['content']}"
            if payload.context.get("pedagogical", {}).get("aproveitamento_pct") is not None:
                response += (
                    f" No seu contexto atual, o sistema registra aproveitamento de "
                    f"{payload.context['pedagogical'].get('aproveitamento_pct', 0)}%."
                )
            response += " Se quiser, posso explicar isso em etapas mais simples ou relacionar com uma atividade do sistema."
            return response

        pedagogical = payload.context.get("pedagogical", {})
        if pedagogical.get("aproveitamento_pct") is not None:
            return (
                "Posso te ajudar com base no seu contexto atual. "
                f"Seu aproveitamento registrado esta em {pedagogical.get('aproveitamento_pct', 0)}%. "
                "Se me disser a duvida, eu explico de forma objetiva."
            )

        if "?" in payload.question:
            return (
                "Ainda nao encontrei base suficiente para responder essa pergunta com seguranca. "
                "Estou em treinamento e prefiro nao improvisar uma resposta sem contexto confiavel."
            )

        return "Pode me dizer sua duvida de forma mais direta para eu tentar te ajudar melhor?"
