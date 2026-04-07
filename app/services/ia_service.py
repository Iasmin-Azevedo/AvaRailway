import asyncio
import json
import re
import unicodedata

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
    GENERIC_MARKERS = (
        "estou pronto para ajudar",
        "mande a pergunta em uma frase",
        "posso te ajudar com base no seu contexto atual",
        "se voce quiser",
        "eu respondo de forma objetiva",
    )
    STOPWORDS = {
        "o", "a", "os", "as", "um", "uma", "de", "da", "do", "das", "dos", "e",
        "é", "em", "para", "por", "com", "que", "como", "qual", "quais", "me",
        "te", "se", "eu", "voce", "você", "isso", "isto", "sobre",
    }

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

        result = None
        result = await self._chat_with_httpx(payload)
        if result and self.is_weak_answer(payload.question, result.answer):
            result = None

        if not result and settings.CHAT_USE_LANGCHAIN and ChatOllama is not None:
            result = await self._chat_with_langchain(payload)
            if result and self.is_weak_answer(payload.question, result.answer):
                result = None

        if not result:
            result = self._fallback_answer(payload)

        if not result:
            result = IAChatResult(
                answer="Nao consegui responder agora. Tente reformular sua pergunta.",
                provider="fallback",
                model=None,
            )

        result.used_context = [chunk["title"] for chunk in payload.retrieved_chunks]
        return result

    async def _chat_with_langchain(self, payload: IAChatPayload) -> IAChatResult | None:
        try:
            model = ChatOllama(
                base_url=settings.OLLAMA_BASE_URL,
                model=settings.OLLAMA_MODEL,
                temperature=0.1,
                num_predict=settings.OLLAMA_NUM_PREDICT,
                num_ctx=settings.OLLAMA_CONTEXT_LENGTH,
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
                timeout=settings.OLLAMA_READ_TIMEOUT_SECONDS,
            )
            content = getattr(response, "content", "")
            if isinstance(content, list):
                content = " ".join(str(item) for item in content)
            answer = str(content).strip()
            if not answer:
                return None
            return IAChatResult(
                answer=answer,
                provider="ollama_langchain",
                model=settings.OLLAMA_MODEL,
            )
        except Exception:
            return None

    async def _chat_with_httpx(self, payload: IAChatPayload) -> IAChatResult | None:
        messages = [{"role": "system", "content": payload.system_prompt}]
        for item in payload.history:
            role = "assistant" if item["sender"] == "assistant" else "user"
            messages.append({"role": role, "content": item["message_text"]})
        messages.append({"role": "user", "content": payload.question})

        request_body = {
            "model": settings.OLLAMA_MODEL,
            "messages": messages,
            "stream": True,
            "options": {
                "temperature": 0.1,
                "num_predict": settings.OLLAMA_NUM_PREDICT,
                "num_ctx": settings.OLLAMA_CONTEXT_LENGTH,
            },
        }

        try:
            chunks: list[str] = []
            timeout = httpx.Timeout(
                connect=float(settings.OLLAMA_CONNECT_TIMEOUT_SECONDS),
                read=float(settings.OLLAMA_READ_TIMEOUT_SECONDS),
                write=30.0,
                pool=10.0,
            )
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
            if not answer:
                return None
            return IAChatResult(
                answer=answer,
                provider="ollama_http",
                model=settings.OLLAMA_MODEL,
            )
        except Exception:
            return None

    def is_low_information_answer(self, answer: str) -> bool:
        normalized = " ".join(answer.lower().split())
        if len(normalized) < 40:
            return True
        return any(marker in normalized for marker in self.GENERIC_MARKERS)

    def is_weak_answer(self, question: str, answer: str) -> bool:
        if self.is_low_information_answer(answer):
            return True

        question_terms = self._extract_terms(question)
        if not question_terms:
            return False

        answer_terms = self._extract_terms(answer)
        overlap = question_terms.intersection(answer_terms)
        return len(overlap) == 0

    def _extract_terms(self, text: str) -> set[str]:
        normalized = unicodedata.normalize("NFKD", text.lower())
        normalized = normalized.encode("ascii", "ignore").decode("ascii")
        terms = set(re.findall(r"[a-z0-9]{4,}", normalized))
        return {term for term in terms if term not in self.STOPWORDS}

    def _fallback_answer(self, payload: IAChatPayload) -> IAChatResult:
        if payload.retrieved_chunks:
            top = payload.retrieved_chunks[0]
            response = f"{top['content']}"
            response += " Se quiser, eu posso explicar isso em passos curtos."
            return IAChatResult(
                answer=response,
                provider="fallback_context",
                model=None,
            )

        if "?" in payload.question:
            return IAChatResult(
                answer=(
                    "Ainda nao encontrei base suficiente para responder essa pergunta com seguranca. "
                    "Estou em treinamento e prefiro nao inventar uma resposta."
                ),
                provider="fallback_training",
                model=None,
            )

        return IAChatResult(
            answer="Escreva sua duvida em uma frase curta que eu tento te ajudar.",
            provider="fallback_prompt",
            model=None,
        )

    async def runtime_status(self) -> dict:
        llm_provider = "ollama_langchain" if settings.CHAT_USE_LANGCHAIN and ChatOllama is not None else "ollama_http"
        reachable = False
        try:
            timeout = httpx.Timeout(
                connect=float(settings.OLLAMA_CONNECT_TIMEOUT_SECONDS),
                read=5.0,
                write=5.0,
                pool=5.0,
            )
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(f"{settings.OLLAMA_BASE_URL}/api/tags")
                response.raise_for_status()
                reachable = True
        except Exception:
            reachable = False

        return {
            "nlu_provider": settings.CHAT_NLU_PROVIDER,
            "llm_provider": llm_provider,
            "llm_model": settings.OLLAMA_MODEL,
            "llm_available": reachable,
            "fallback_enabled": settings.ENABLE_CHAT_FALLBACK,
        }
