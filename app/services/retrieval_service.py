import re
import unicodedata
from typing import List

from sqlalchemy.orm import Session

from app.core.chat_settings import RetrievedChunk
from app.core.config import settings
from app.integrations.moodle_client import MoodleClient
from app.models.avaliacao import Avaliacao
from app.models.gestao import Curso, Trilha
from app.models.h5p import AtividadeH5P
from app.models.saeb import Descritor

try:
    from sentence_transformers import SentenceTransformer, util
except Exception:
    SentenceTransformer = None
    util = None


class RetrievalService:
    STOPWORDS = {
        "a",
        "as",
        "o",
        "os",
        "e",
        "de",
        "da",
        "do",
        "das",
        "dos",
        "em",
        "no",
        "na",
        "nos",
        "nas",
        "um",
        "uma",
        "me",
        "te",
        "se",
        "que",
        "como",
        "qual",
        "quais",
        "por",
        "para",
        "sobre",
        "voce",
        "sabe",
    }

    def __init__(self, db: Session | None = None):
        self.db = db
        self.moodle_client = MoodleClient()
        self.enabled = settings.CHAT_ENABLE_SEMANTIC_SEARCH and SentenceTransformer is not None
        self.model = None
        self.base_corpus = [
            {
                "source": "faq",
                "title": "Como estudar melhor",
                "content": "Estude em blocos curtos, revise o conteudo, pratique exercicios e tire duvidas progressivamente.",
                "metadata": {"area": "geral"},
            },
            {
                "source": "faq",
                "title": "O que e fracao",
                "content": "Fracao representa partes de um todo. O numerador indica quantas partes foram consideradas e o denominador em quantas partes o todo foi dividido.",
                "metadata": {"area": "matematica"},
            },
            {
                "source": "faq",
                "title": "Diferenca entre substantivo e adjetivo",
                "content": "Substantivo nomeia seres, objetos, lugares ou ideias. Adjetivo caracteriza o substantivo, indicando qualidade, estado ou caracteristica.",
                "metadata": {"area": "portugues"},
            },
            {
                "source": "faq",
                "title": "Como resolver porcentagem",
                "content": "Para calcular porcentagem, transforme a taxa em fracao sobre 100 e multiplique pelo valor total. Exemplo: 25% de 200 equivale a 25 sobre 100 vezes 200, resultando em 50.",
                "metadata": {"area": "matematica"},
            },
            {
                "source": "faq",
                "title": "Como interpretar problemas de matematica",
                "content": "Leia o enunciado com calma, identifique os dados, descubra o que a questao pede e escolha a operacao correta antes de calcular.",
                "metadata": {"area": "matematica"},
            },
            {
                "source": "faq",
                "title": "Uso da virgula",
                "content": "A virgula pode separar elementos de uma lista, marcar uma pausa curta e isolar expressoes explicativas. Ela nao deve separar sujeito e verbo sem necessidade.",
                "metadata": {"area": "portugues"},
            },
            {
                "source": "faq",
                "title": "Como melhorar interpretacao de texto",
                "content": "Leia o texto por partes, destaque palavras importantes, observe quem fala, onde a historia acontece e relacione as perguntas com trechos do texto.",
                "metadata": {"area": "portugues"},
            },
        ]
        self.corpus_embeddings = None

        if self.enabled:
            self.model = SentenceTransformer(settings.CHAT_EMBEDDING_MODEL)

    def _normalize(self, text: str) -> str:
        value = unicodedata.normalize("NFKD", text.lower())
        return "".join(ch for ch in value if not unicodedata.combining(ch))

    def _tokenize(self, text: str) -> list[str]:
        tokens = re.findall(r"[a-z0-9]+", self._normalize(text))
        return [token for token in tokens if len(token) >= 3 and token not in self.STOPWORDS]

    def _build_dynamic_corpus(self, context: dict | None = None) -> list[dict]:
        corpus = list(self.base_corpus)
        if not self.db:
            return corpus

        for descritor in self.db.query(Descritor).limit(20).all():
            corpus.append(
                {
                    "source": "descritor",
                    "title": f"Descritor {descritor.codigo or descritor.id}",
                    "content": descritor.descricao or "",
                    "metadata": {"disciplina": descritor.disciplina or "geral"},
                }
            )

        for curso in self.db.query(Curso).limit(10).all():
            corpus.append(
                {
                    "source": "curso",
                    "title": f"Curso {curso.nome}",
                    "content": f"Curso disponivel no sistema: {curso.nome}.",
                    "metadata": {"tipo": "curso"},
                }
            )

        for trilha in self.db.query(Trilha).limit(15).all():
            corpus.append(
                {
                    "source": "trilha",
                    "title": f"Trilha {trilha.nome}",
                    "content": f"Trilha de aprendizagem {trilha.nome} para o ano escolar {trilha.ano_escolar or 'geral'}.",
                    "metadata": {"tipo": "trilha", "ano_escolar": trilha.ano_escolar},
                }
            )

        for atividade in self.db.query(AtividadeH5P).filter(AtividadeH5P.ativo == True).limit(20).all():
            corpus.append(
                {
                    "source": "atividade",
                    "title": f"Atividade {atividade.titulo}",
                    "content": f"Atividade do tipo {atividade.tipo} chamada {atividade.titulo}.",
                    "metadata": {"tipo": atividade.tipo},
                }
            )

        for avaliacao in self.db.query(Avaliacao).limit(10).all():
            corpus.append(
                {
                    "source": "avaliacao",
                    "title": f"Avaliacao {avaliacao.titulo or avaliacao.id}",
                    "content": avaliacao.descricao or f"Avaliacao cadastrada no sistema com titulo {avaliacao.titulo or avaliacao.id}.",
                    "metadata": {"tipo": "avaliacao"},
                }
            )

        pedagogical = (context or {}).get("pedagogical", {})
        if pedagogical:
            corpus.append(
                {
                    "source": "contexto_aluno",
                    "title": "Contexto atual do aluno",
                    "content": (
                        f"Aproveitamento atual: {pedagogical.get('aproveitamento_pct', 0)}%. "
                        f"Conteudos concluidos: {pedagogical.get('conteudos_concluidos', 0)}. "
                        f"XP total: {pedagogical.get('xp_total', 0)}. "
                        f"Trilhas sugeridas: {', '.join(pedagogical.get('trilhas_sugeridas', [])) or 'nenhuma informada'}."
                    ),
                    "metadata": {"tipo": "contexto"},
                }
            )

        for content in self.moodle_client.fetch_learning_content()[:20]:
            corpus.append(
                {
                    "source": "moodle",
                    "title": content.get("title") or "Conteudo do Moodle",
                    "content": (
                        f"Curso: {content.get('course', 'Nao informado')}. "
                        f"Secao: {content.get('section', 'Nao informada')}. "
                        f"Descricao: {content.get('description', '')}"
                    ).strip(),
                    "metadata": {
                        "tipo": content.get("modname", "recurso"),
                        "course": content.get("course"),
                        "url": content.get("url"),
                    },
                }
            )

        return corpus

    def search(self, query: str, top_k: int | None = None, context: dict | None = None) -> List[RetrievedChunk]:
        top_k = top_k or settings.CHAT_RETRIEVAL_TOP_K
        corpus = self._build_dynamic_corpus(context)
        if not self.enabled or not self.model or util is None:
            return self.keyword_fallback(query, top_k, corpus)

        corpus_embeddings = self.model.encode(
            [item["content"] for item in corpus],
            convert_to_tensor=True,
        )
        query_embedding = self.model.encode(query, convert_to_tensor=True)
        hits = util.semantic_search(query_embedding, corpus_embeddings, top_k=top_k)[0]
        results = []
        for hit in hits:
            item = corpus[hit["corpus_id"]]
            results.append(
                RetrievedChunk(
                    source=item["source"],
                    title=item["title"],
                    content=item["content"],
                    score=float(hit["score"]),
                    metadata=item["metadata"],
                )
            )
        return results

    def keyword_fallback(self, query: str, top_k: int, corpus: list[dict]) -> List[RetrievedChunk]:
        query_terms = self._tokenize(query)
        scored = []
        for item in corpus:
            text = self._normalize(f'{item["title"]} {item["content"]}')
            score = sum(2 for term in query_terms if term in text)
            if item["source"] == "contexto_aluno" and any(term in text for term in query_terms):
                score += 3
            if item["source"] in {"descritor", "atividade", "trilha"} and any(term in text for term in query_terms):
                score += 1
            if score > 0:
                scored.append((score, item))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            RetrievedChunk(
                source=item["source"],
                title=item["title"],
                content=item["content"],
                score=float(score),
                metadata=item["metadata"],
            )
            for score, item in scored[:top_k]
        ]
