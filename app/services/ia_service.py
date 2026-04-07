import asyncio
import json

import httpx

from app.core.config import settings
from app.schemas.chat_schema import IAChatPayload, IAChatResult

try:
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
    from langchain_ollama import ChatOllama
except Exception:  # pragma: no cover - dependencia opcional
    AIMessage = HumanMessage = SystemMessage = None
    ChatOllama = None


class IAService:
    OLLAMA_TIMEOUT_SECONDS = 45
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

        answer = None
        if settings.CHAT_USE_LANGCHAIN and ChatOllama is not None:
            answer = await self._chat_with_langchain(payload)

        if not answer:
            answer = await self._chat_with_httpx(payload)

        if not answer:
            answer = self._fallback_answer(payload)

        if not answer:
            answer = "Nao consegui responder agora. Tente reformular sua pergunta."

        return IAChatResult(
            answer=answer,
            used_context=[chunk["title"] for chunk in payload.retrieved_chunks],
        )

    async def _chat_with_langchain(self, payload: IAChatPayload) -> str | None:
        try:
            model = ChatOllama(
                base_url=settings.OLLAMA_BASE_URL,
                model=settings.OLLAMA_MODEL,
                temperature=0.1,
                num_predict=180,
            )
            messages = [SystemMessage(content=payload.system_prompt)]
            for item in payload.history:
                if item["sender"] == "assistant":
                    messages.append(AIMessage(content=item["message_text"]))
                else:
                    messages.append(HumanMessage(content=item["message_text"]))
            messages.append(HumanMessage(content=payload.question))
            response = await asyncio.wait_for(
                model.ainvoke(messages),
                timeout=self.OLLAMA_TIMEOUT_SECONDS,
            )
            content = getattr(response, "content", "")
            if isinstance(content, list):
                content = " ".join(str(item) for item in content)
            return str(content).strip() or None
        except Exception:
            return None

    async def _chat_with_httpx(self, payload: IAChatPayload) -> str | None:
        messages = [{"role": "system", "content": payload.system_prompt}]
        for item in payload.history:
            role = "assistant" if item["sender"] == "assistant" else "user"
            messages.append({"role": role, "content": item["message_text"]})
        messages.append({"role": "user", "content": payload.question})

        request_body = {
            "model": settings.OLLAMA_MODEL,
            "messages": messages,
            "stream": True,
            "options": {"temperature": 0.1, "num_predict": 180},
        }

        try:
            chunks: list[str] = []
            timeout = httpx.Timeout(connect=10.0, read=self.OLLAMA_TIMEOUT_SECONDS, write=30.0, pool=10.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream(
                    "POST",
                    f"{settings.OLLAMA_BASE_URL}/api/chat",
                    json=request_body,
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        data = json.loads(line)
                        message = data.get("message", {}) or {}
                        content = message.get("content")
                        if content:
                            chunks.append(str(content))
                        if data.get("done"):
                            break
            answer = "".join(chunks).strip()
            return answer or None
        except Exception:
            return None

    def is_low_information_answer(self, answer: str) -> bool:
        normalized = " ".join(answer.lower().split())
        if len(normalized) < 40:
            return True
        return any(marker in normalized for marker in self.GENERIC_MARKERS)

    def _fallback_answer(self, payload: IAChatPayload) -> str:
        if payload.retrieved_chunks:
            top = payload.retrieved_chunks[0]
            response = f"{top['content']}"
            response += " Se quiser, eu posso explicar isso em passos curtos."
            return response

        if "?" in payload.question:
            return (
                "Ainda nao encontrei base suficiente para responder essa pergunta com seguranca. "
                "Estou em treinamento e prefiro nao inventar uma resposta."
            )

        return "Escreva sua duvida em uma frase curta que eu tento te ajudar."
