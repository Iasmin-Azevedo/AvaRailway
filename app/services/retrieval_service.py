import json
import logging
import re
import unicodedata
from pathlib import Path
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

logger = logging.getLogger("ava_mj_backend.chat_retrieval")


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
        "você",
        "sabe",
    }
    SOURCE_TRUST_WEIGHTS = {
        "contexto_aluno": 1.35,
        "atividade": 1.2,
        "trilha": 1.15,
        "avaliacao": 1.15,
        "descritor": 1.1,
        "curso": 1.05,
        "faq": 1.0,
        "moodle": 0.95,
    }
    SYNONYM_MAP = {
        "matematica": ["mat", "conta", "calculo", "calcular", "equacao", "equações", "fração", "fracao"],
        "portugues": ["port", "texto", "gramatica", "gramática", "interpretação", "interpretacao", "redacao"],
        "atividade": ["tarefa", "exercicio", "exercício", "questao", "questão", "simulado", "prova"],
        "aula_ao_vivo": ["ao vivo", "aula", "meet", "jitsi", "chamada", "sala"],
        "plataforma": ["sistema", "dashboard", "painel", "login", "acesso", "perfil"],
        "desempenho": ["nota", "resultado", "aproveitamento", "progresso", "evolucao", "evolução"],
    }

    def __init__(self, db: Session | None = None):
        self.db = db
        self.moodle_client = MoodleClient()
        self.enabled = settings.CHAT_ENABLE_SEMANTIC_SEARCH and SentenceTransformer is not None
        self.model = None
        self.external_kb_path = Path(__file__).resolve().parent.parent / "data" / "chat_knowledge_base.json"
        self.base_corpus = [
            {
                "source": "faq",
                "title": "Como estudar melhor",
                "content": "Estude em blocos curtos, revise o conteúdo, pratique exercícios e tire dúvidas progressivamente.",
                "metadata": {"area": "geral", "keywords": ["estudar", "estudo", "revisão"]},
            },
            {
                "source": "faq",
                "title": "O que é fração",
                "content": "Fração representa partes de um todo. O numerador indica quantas partes foram consideradas e o denominador em quantas partes o todo foi dividido.",
                "metadata": {"area": "matemática", "keywords": ["fração", "fracao", "numerador", "denominador"]},
            },
            {
                "source": "faq",
                "title": "Diferença entre substantivo e adjetivo",
                "content": "Substantivo nomeia seres, objetos, lugares ou ideias. Adjetivo caracteriza o substantivo, indicando qualidade, estado ou característica.",
                "metadata": {"area": "português", "keywords": ["substantivo", "adjetivo"]},
            },
            {
                "source": "faq",
                "title": "Como resolver porcentagem",
                "content": "Para calcular porcentagem, transforme a taxa em fração sobre 100 e multiplique pelo valor total. Exemplo: 25% de 200 equivale a 25 sobre 100 vezes 200, resultando em 50.",
                "metadata": {"area": "matemática", "keywords": ["porcentagem", "percentual", "por cento"]},
            },
            {
                "source": "faq",
                "title": "Como interpretar problemas de matemática",
                "content": "Leia o enunciado com calma, identifique os dados, descubra o que a questão pede e escolha a operação correta antes de calcular.",
                "metadata": {"area": "matemática", "keywords": ["matemática", "matematica", "problema", "conta"]},
            },
            {
                "source": "faq",
                "title": "Uso da vírgula",
                "content": "A vírgula pode separar elementos de uma lista, marcar uma pausa curta e isolar expressões explicativas. Ela não deve separar sujeito e verbo sem necessidade.",
                "metadata": {"area": "português", "keywords": ["vírgula", "virgula"]},
            },
            {
                "source": "faq",
                "title": "Como melhorar interpretação de texto",
                "content": "Leia o texto por partes, destaque palavras importantes, observe quem fala, onde a história acontece e relacione as perguntas com trechos do texto.",
                "metadata": {"area": "português", "keywords": ["interpretação", "interpretacao", "texto", "leitura"]},
            },
        ]
        self.base_corpus.extend(self._load_external_corpus())
        self.corpus_embeddings = None

        if self.enabled:
            self.model = SentenceTransformer(settings.CHAT_EMBEDDING_MODEL)

    def _load_external_corpus(self) -> list[dict]:
        if not self.external_kb_path.exists():
            return []
        try:
            payload = json.loads(self.external_kb_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Falha ao carregar base externa do chat: %s", exc)
            return []

        rows = payload.get("items", []) if isinstance(payload, dict) else []
        if not isinstance(rows, list):
            return []

        out: list[dict] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            source = (row.get("source") or "kb").strip()
            title = (row.get("title") or "").strip()
            content = (row.get("content") or "").strip()
            metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            if not title or not content:
                continue
            out.append(
                {
                    "source": source,
                    "title": title,
                    "content": content,
                    "metadata": metadata,
                }
            )
        return out

    def _repair_text(self, text: str) -> str:
        try:
            repaired = text.encode("latin1").decode("utf-8")
            if repaired.count("?") <= text.count("?"):
                return repaired
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
        return text

    def _normalize(self, text: str) -> str:
        text = self._repair_text(text)
        value = unicodedata.normalize("NFKD", text.lower())
        return "".join(ch for ch in value if not unicodedata.combining(ch))

    def _tokenize(self, text: str) -> list[str]:
        tokens = re.findall(r"[a-z0-9]+", self._normalize(text))
        return [token for token in tokens if len(token) >= 3 and token not in self.STOPWORDS]

    def _source_weight(self, source: str) -> float:
        return float(self.SOURCE_TRUST_WEIGHTS.get((source or "").strip().lower(), 1.0))

    def _expand_query_terms(self, query: str) -> list[str]:
        base_terms = self._tokenize(query)
        expanded = set(base_terms)
        normalized_query = self._normalize(query)
        for _, aliases in self.SYNONYM_MAP.items():
            alias_tokens = [self._normalize(item) for item in aliases]
            if any(alias in normalized_query for alias in alias_tokens):
                expanded.update(self._tokenize(" ".join(alias_tokens)))
        return list(expanded)

    def _context_relevance_multiplier(self, item: dict, context: dict | None) -> float:
        if not context:
            return 1.0
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        user_profile = str((context.get("user", {}) or {}).get("perfil") or "").strip().lower()
        user_year = (context.get("pedagogical", {}) or {}).get("ano_escolar")
        multiplier = 1.0

        item_profile = str(metadata.get("perfil") or "").strip().lower()
        if item_profile:
            if item_profile in {"geral", "all"}:
                multiplier *= 1.05
            elif user_profile and item_profile == user_profile:
                multiplier *= 1.15
            elif user_profile and item_profile != user_profile:
                multiplier *= 0.82

        item_year = metadata.get("ano_escolar")
        if isinstance(item_year, int) and isinstance(user_year, int):
            if item_year == user_year:
                multiplier *= 1.1
            else:
                multiplier *= 0.9
        return multiplier

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
                    "content": f"Curso disponível no sistema: {curso.nome}.",
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
                    "title": f"Avaliação {avaliacao.titulo or avaliacao.id}",
                    "content": avaliacao.descricao or f"Avaliação cadastrada no sistema com título {avaliacao.titulo or avaliacao.id}.",
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
                        f"Conteúdos concluídos: {pedagogical.get('conteudos_concluidos', 0)}. "
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
                    "title": content.get("title") or "Conteúdo do Moodle",
                    "content": (
                        f"Curso: {content.get('course', 'Não informado')}. "
                        f"Seção: {content.get('section', 'Não informada')}. "
                        f"Descrição: {content.get('description', '')}"
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
        direct_matches = self.direct_match(query, corpus, top_k, context=context)
        if direct_matches:
            return direct_matches
        if not self.enabled or not self.model or util is None:
            return self.keyword_fallback(query, top_k, corpus, context=context)

        corpus_embeddings = self.model.encode(
            [item["content"] for item in corpus],
            convert_to_tensor=True,
        )
        query_embedding = self.model.encode(query, convert_to_tensor=True)
        hits = util.semantic_search(query_embedding, corpus_embeddings, top_k=top_k)[0]
        scored_results: list[tuple[float, RetrievedChunk]] = []
        for hit in hits:
            item = corpus[hit["corpus_id"]]
            raw_score = float(hit["score"])
            adjusted_score = (
                raw_score
                * self._source_weight(item["source"])
                * self._context_relevance_multiplier(item, context)
            )
            if adjusted_score < 0.2:
                continue
            scored_results.append(
                (
                    adjusted_score,
                    RetrievedChunk(
                        source=item["source"],
                        title=item["title"],
                        content=item["content"],
                        score=adjusted_score,
                        metadata=item["metadata"],
                    ),
                )
            )
        scored_results.sort(key=lambda row: row[0], reverse=True)
        return [row[1] for row in scored_results[:top_k]]

    def keyword_fallback(
        self,
        query: str,
        top_k: int,
        corpus: list[dict],
        context: dict | None = None,
    ) -> List[RetrievedChunk]:
        query_terms = self._expand_query_terms(query)
        scored = []
        for item in corpus:
            item_terms = set(self._tokenize(f'{item["title"]} {item["content"]}'))
            score = sum(2 for term in query_terms if term in item_terms)
            if item["source"] == "contexto_aluno" and any(term in item_terms for term in query_terms):
                score += 3
            if item["source"] in {"descritor", "atividade", "trilha"} and any(term in item_terms for term in query_terms):
                score += 1
            score = (
                score
                * self._source_weight(item["source"])
                * self._context_relevance_multiplier(item, context)
            )
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

    def direct_match(
        self,
        query: str,
        corpus: list[dict],
        top_k: int,
        context: dict | None = None,
    ) -> List[RetrievedChunk]:
        normalized_query = self._normalize(query)
        query_terms = self._expand_query_terms(query)
        matches = []

        for item in corpus:
            keywords = (item.get("metadata") or {}).get("keywords") or []
            normalized_keywords = [self._normalize(str(keyword)) for keyword in keywords]
            title_terms = self._tokenize(item.get("title", ""))
            keyword_terms = [term for keyword in normalized_keywords for term in self._tokenize(keyword)]

            has_direct_keyword = any(keyword and keyword in normalized_query for keyword in normalized_keywords)
            has_prefix_match = any(
                query_term.startswith(keyword_term) or keyword_term.startswith(query_term)
                for query_term in query_terms
                for keyword_term in keyword_terms + title_terms
                if query_term and keyword_term
            )

            if has_direct_keyword or has_prefix_match:
                matches.append(
                    RetrievedChunk(
                        source=item["source"],
                        title=item["title"],
                        content=item["content"],
                        score=(
                            100.0
                            * self._source_weight(item["source"])
                            * self._context_relevance_multiplier(item, context)
                        ),
                        metadata=item["metadata"],
                    )
                )

        return matches[:top_k]
