from typing import List

from app.core.chat_settings import RetrievedChunk
from app.core.config import settings

try:
    from sentence_transformers import SentenceTransformer, util
except Exception:
    SentenceTransformer = None
    util = None


class RetrievalService:
    def __init__(self):
        self.enabled = settings.CHAT_ENABLE_SEMANTIC_SEARCH and SentenceTransformer is not None
        self.model = None
        self.corpus = [
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
        ]
        self.corpus_embeddings = None

        if self.enabled:
            self.model = SentenceTransformer(settings.CHAT_EMBEDDING_MODEL)
            self.corpus_embeddings = self.model.encode(
                [item["content"] for item in self.corpus],
                convert_to_tensor=True,
            )

    def search(self, query: str, top_k: int | None = None) -> List[RetrievedChunk]:
        top_k = top_k or settings.CHAT_RETRIEVAL_TOP_K
        if not self.enabled or not self.model or util is None:
            return self.keyword_fallback(query, top_k)

        query_embedding = self.model.encode(query, convert_to_tensor=True)
        hits = util.semantic_search(query_embedding, self.corpus_embeddings, top_k=top_k)[0]
        results = []
        for hit in hits:
            item = self.corpus[hit["corpus_id"]]
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

    def keyword_fallback(self, query: str, top_k: int) -> List[RetrievedChunk]:
        query_terms = query.lower().split()
        scored = []
        for item in self.corpus:
            text = f'{item["title"]} {item["content"]}'.lower()
            score = sum(1 for term in query_terms if term in text)
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
