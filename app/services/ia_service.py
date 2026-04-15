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
    TRUSTED_SOURCE_LABELS = {
        "contexto_aluno": "Contexto do aluno",
        "atividade": "Atividade cadastrada",
        "trilha": "Trilha de aprendizagem",
        "avaliacao": "Avaliação cadastrada",
        "descritor": "Descritor pedagógico",
        "curso": "Curso cadastrado",
        "faq": "Base pedagógica interna",
        "moodle": "Conteúdo Moodle integrado",
    }

    def gerar_feedback(self, acertos: int, total: int):
        percentual = (acertos / total) * 100 if total else 0
        if percentual == 100:
            return "Parabens! Voce dominou esse conteudo completamente."
        if percentual >= 70:
            return "Muito bom! Voce entendeu a maior parte, mas revise os erros."
        return "Parece que você teve dificuldades. Que tal revisarmos o material base?"

    def _normalize_spaces(self, text: str) -> str:
        return " ".join((text or "").strip().split())

    def _ensure_terminal_punctuation(self, text: str) -> str:
        if not text:
            return text
        if text.endswith((".", "!", "?")):
            return text
        return f"{text}."

    def _polish_answer(self, answer: str, profile: str) -> str:
        text = self._normalize_spaces(answer)
        if not text:
            return text
        text = text.replace(" ,", ",").replace(" .", ".").replace(" !", "!").replace(" ?", "?").replace(" ;", ";")
        if text and text[0].islower():
            text = text[0].upper() + text[1:]
        text = self._ensure_terminal_punctuation(text)
        # Evita respostas extensas e dispersas para aluno.
        if str(profile).lower() == "aluno" and len(text) > 900:
            text = text[:900].rsplit(" ", 1)[0].strip() + "..."
        return text

    def _source_label(self, source: str) -> str:
        return self.TRUSTED_SOURCE_LABELS.get((source or "").strip().lower(), "Fonte interna")

    def _build_sources_footer(self, chunks: list[dict]) -> str:
        if not chunks:
            return ""
        refs = []
        for chunk in chunks[:2]:
            title = (chunk.get("title") or "Fonte sem título").strip()
            label = self._source_label(chunk.get("source") or "")
            refs.append(f"{label}: {title}")
        return " Fontes consultadas: " + " | ".join(refs) + "."

    def _has_explicit_source_reference(self, answer: str, chunks: list[dict]) -> bool:
        normalized = " ".join((answer or "").lower().split())
        if "fonte" in normalized or "fontes" in normalized:
            return True
        for chunk in chunks[:2]:
            title = (chunk.get("title") or "").strip().lower()
            if title and title in normalized:
                return True
        return False

    def _build_grounded_answer_from_chunks(self, question: str, chunks: list[dict], profile: str) -> str:
        top = chunks[0]
        top_content = (top.get("content") or "").strip()
        topic = self._infer_topic(question)
        role = str(profile or "").strip().lower()

        if role == "aluno":
            intro = "Com base nas fontes internas disponíveis, a resposta mais segura é:"
            if topic in {"matematica", "portugues"}:
                body = (
                    f" {top_content} "
                    "Se quiser, eu organizo em passos curtos com um exemplo simples."
                )
            else:
                body = f" {top_content} "
            return intro + body + self._build_sources_footer(chunks)

        return (
            "Com base nas fontes internas disponíveis, a melhor síntese é: "
            + top_content
            + self._build_sources_footer(chunks)
        )

    def _needs_grounding_rewrite(self, payload: IAChatPayload, answer: str) -> bool:
        if self.is_weak_answer(payload.question, answer):
            return True
        if payload.retrieved_chunks and not self._has_explicit_source_reference(answer, payload.retrieved_chunks):
            return True
        normalized = " ".join((answer or "").lower().split())
        if "não sei" in normalized and payload.retrieved_chunks:
            return True
        return False

    def _infer_topic(self, question: str) -> str:
        q = self._normalize_spaces(question).lower()
        if any(term in q for term in ("fracao", "fração", "porcentagem", "matematica", "matemática", "equacao", "equação")):
            return "matematica"
        if any(term in q for term in ("portugues", "português", "texto", "gramatica", "gramática", "virgula", "vírgula")):
            return "portugues"
        if any(term in q for term in ("atividade", "tarefa", "exercicio", "exercício")):
            return "atividade"
        if any(term in q for term in ("aula ao vivo", "ao vivo", "meet", "jitsi", "agenda")):
            return "aula_ao_vivo"
        if any(term in q for term in ("plataforma", "sistema", "login", "dashboard", "perfil")):
            return "plataforma"
        return "geral"

    def build_guided_training_answer(self, question: str, profile: str) -> str:
        topic = self._infer_topic(question)
        role = str(profile or "").strip().lower()
        if role == "aluno":
            if topic == "matematica":
                return (
                    "Ainda não encontrei base local suficiente para responder isso com total segurança. "
                    "Posso te ajudar de um jeito útil agora: 1) identificamos os dados da questão, "
                    "2) escolhemos a operação correta, 3) resolvemos passo a passo com exemplo simples."
                )
            if topic == "portugues":
                return (
                    "Ainda estou em treinamento para esse tipo de pergunta com base local completa. "
                    "Mesmo assim, posso te orientar com um roteiro prático: 1) ler com calma, "
                    "2) destacar palavras-chave, 3) responder usando trecho do texto."
                )
            return (
                "Ainda estou em treinamento para esse caso e prefiro não improvisar. "
                "Se você reformular em uma pergunta mais direta sobre atividade, aula ao vivo, "
                "Matemática ou Português, eu te ajudo com mais precisão."
            )

        if role == "professor":
            return (
                "Ainda não encontrei base local suficiente para responder com segurança total. "
                "Posso apoiar com um caminho objetivo: delimitar turma, indicador e período, "
                "e então montar uma resposta precisa sem inventar dados."
            )

        return (
            "Ainda não encontrei base local suficiente para responder com segurança total. "
            "Posso continuar se você informar mais contexto objetivo (perfil, turma, tema e período)."
        )

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

        if payload.retrieved_chunks and self._needs_grounding_rewrite(payload, result.answer):
            result = IAChatResult(
                answer=self._build_grounded_answer_from_chunks(
                    payload.question,
                    payload.retrieved_chunks,
                    payload.profile,
                ),
                provider="grounded_rewrite",
                model=result.model,
            )
        elif payload.retrieved_chunks and not self._has_explicit_source_reference(result.answer, payload.retrieved_chunks):
            result.answer = result.answer + self._build_sources_footer(payload.retrieved_chunks)

        result.answer = self._polish_answer(result.answer, payload.profile)
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
            response = (
                f"Com base no que tenho aqui, a melhor referência inicial é: {top['content']} "
                "Se quiser, organizo essa explicação em passos curtos com exemplo prático."
            )
            return IAChatResult(
                answer=response,
                provider="fallback_context",
                model=None,
            )

        if "?" in payload.question:
            return IAChatResult(
                answer=self.build_guided_training_answer(payload.question, payload.profile),
                provider="fallback_training",
                model=None,
            )

        return IAChatResult(
            answer="Escreva sua dúvida em uma frase curta que eu tento te ajudar.",
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
