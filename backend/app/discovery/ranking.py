"""Embedding-based re-rank: cosine similarity between a query text (a topic
string, or a profile signal) and each candidate paper's abstract, via the AI
Provider Layer's ``embed`` -- never keyword match (docs/ARCHITECTURE.md's
Phase 5 decisions). A provider that raises ``NotSupportedError`` on
``embed`` propagates unhandled -- no silent fallback to a different provider.

``cosine_similarity`` is public (not module-private) because
``app.graph.service`` (Phase 7's library-wide literature graph) imports it
for the same pairwise-similarity math -- promoted rather than duplicated,
per ARCHITECTURE.md's Phase 7 decisions.
"""

import math
from dataclasses import dataclass

from app.papers.arxiv_client import ArxivMetadata
from app.providers.base import AIProvider

_TOP_N_DEFAULT = 15


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _embedding_text(paper: ArxivMetadata) -> str:
    # Falls back to the title only when arXiv genuinely has no abstract for
    # an entry (rare) -- never fabricates one; the persisted `abstract`
    # field still stores whatever arXiv actually returned (possibly "").
    return paper.abstract or paper.title


@dataclass(frozen=True)
class RankedPaper:
    paper: ArxivMetadata
    relevance_score: float


async def rank_candidates_by_topic(
    provider: AIProvider, topic: str, candidates: list[ArxivMetadata], *, embed_model: str, top_n: int = _TOP_N_DEFAULT
) -> list[RankedPaper]:
    """Re-ranks ``candidates`` by cosine similarity of their abstract
    embedding against the topic string's own embedding, descending, top
    ``top_n``. One batched ``embed`` call (topic + every candidate) --
    ``NotSupportedError`` propagates to the caller unhandled."""
    if not candidates:
        return []

    texts = [topic] + [_embedding_text(c) for c in candidates]
    embeddings = await provider.embed(texts, model=embed_model)
    topic_vector, candidate_vectors = embeddings[0], embeddings[1:]

    ranked = [
        RankedPaper(paper=candidate, relevance_score=cosine_similarity(topic_vector, vector))
        for candidate, vector in zip(candidates, candidate_vectors, strict=True)
    ]
    ranked.sort(key=lambda item: item.relevance_score, reverse=True)
    return ranked[:top_n]


@dataclass(frozen=True)
class RankedRecommendation:
    paper: ArxivMetadata
    relevance_score: float
    # The single profile signal (one interest or goal string) whose
    # embedding was closest to this paper -- what the explanation text is
    # grounded in, never a generic combined-profile score.
    matched_signal_kind: str
    matched_signal_text: str


async def rank_candidates_for_profile(
    provider: AIProvider,
    interests: list[str],
    goals: list[str],
    candidates: list[ArxivMetadata],
    *,
    embed_model: str,
    top_n: int = _TOP_N_DEFAULT,
) -> list[RankedRecommendation]:
    """Ranks ``candidates`` against the profile's individual interest/goal
    strings (never a single blended "profile vector") so each
    recommendation's relevance score and explanation are traceable to one
    concrete signal the user actually entered."""
    signals: list[tuple[str, str]] = [(text, "interest") for text in interests] + [
        (text, "goal") for text in goals
    ]
    if not signals or not candidates:
        return []

    texts = [text for text, _kind in signals] + [_embedding_text(c) for c in candidates]
    embeddings = await provider.embed(texts, model=embed_model)
    signal_vectors = embeddings[: len(signals)]
    candidate_vectors = embeddings[len(signals) :]

    ranked: list[RankedRecommendation] = []
    for candidate, vector in zip(candidates, candidate_vectors, strict=True):
        similarities = [cosine_similarity(vector, signal_vector) for signal_vector in signal_vectors]
        best_index = max(range(len(similarities)), key=lambda i: similarities[i])
        best_text, best_kind = signals[best_index]
        ranked.append(
            RankedRecommendation(
                paper=candidate,
                relevance_score=similarities[best_index],
                matched_signal_kind=best_kind,
                matched_signal_text=best_text,
            )
        )

    ranked.sort(key=lambda item: item.relevance_score, reverse=True)
    return ranked[:top_n]
