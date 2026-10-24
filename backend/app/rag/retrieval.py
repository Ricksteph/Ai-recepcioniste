"""Tenant-isolated retrieval (§8, §24).

On Postgres: pgvector cosine-distance ordering with an explicit tenant filter.
On SQLite (dev/tests): same tenant filter, cosine computed in-process.
No code path can return another tenant's chunks.
"""
import json
import math

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import is_postgres
from ..llm.orchestrator import embed
from ..models import KnowledgeChunk, KnowledgeSource

# Floor for the local hashing embedding (crude vectors score low on long chunks);
# ordering still puts the best match first, and results are tenant-filtered anyway.
MIN_SCORE = 0.01


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def _deserialize(value, dim_hint: int) -> list[float]:
    if value is None:
        return []
    if isinstance(value, str):
        try:
            return [float(x) for x in json.loads(value)]
        except (ValueError, json.JSONDecodeError):
            return []
    if isinstance(value, (bytes, memoryview)):
        # pgvector binary format is not used here; treat as unsupported
        return []
    return [float(x) for x in value]


async def search_knowledge(
    db: AsyncSession, tenant_id: str, query: str, *, limit: int = 5
) -> list[dict]:
    """Return the top chunks for this tenant only, with source names."""
    if not query.strip():
        return []
    [query_vec] = await embed([query])

    if is_postgres():
        distance = KnowledgeChunk.embedding.cosine_distance(query_vec)
        rows = (
            await db.execute(
                select(KnowledgeChunk, KnowledgeSource.name)
                .join(KnowledgeSource, KnowledgeChunk.source_id == KnowledgeSource.id)
                .where(
                    KnowledgeChunk.tenant_id == tenant_id,
                    KnowledgeSource.enabled.is_(True),
                    KnowledgeChunk.embedding.is_not(None),
                )
                .order_by(distance)
                .limit(limit)
            )
        ).all()
        out = []
        for chunk, source_name in rows:
            score = max(0.0, 1.0 - float(getattr(chunk, "_distance", 0.0) or 0.0))
            out.append(_snippet(chunk, source_name, score, query))
        return out

    # SQLite / fallback: filter by tenant first, then cosine in-process.
    rows = (
        await db.execute(
            select(KnowledgeChunk, KnowledgeSource.name)
            .join(KnowledgeSource, KnowledgeChunk.source_id == KnowledgeSource.id)
            .where(
                KnowledgeChunk.tenant_id == tenant_id,
                KnowledgeSource.enabled.is_(True),
            )
        )
    ).all()
    scored = []
    for chunk, source_name in rows:
        vec = _deserialize(chunk.embedding, len(query_vec))
        if not vec:
            continue
        score = _cosine(query_vec, vec)
        if score >= MIN_SCORE:
            scored.append((score, chunk, source_name))
    scored.sort(key=lambda t: t[0], reverse=True)
    return [_snippet(chunk, name, score, query) for score, chunk, name in scored[:limit]]


def _focus_window(text: str, query: str, window: int = 420) -> str:
    """Return the part of the chunk most relevant to the query terms.

    Without this, a short document packed into one chunk always surfaces its
    head (e.g. the hours section) even for a price question.
    """
    import re as _re

    low = text.lower()
    tokens = [t for t in _re.findall(r"[\wÀ-ÿ]{3,}", query.lower())]
    positions = [low.find(t) for t in tokens]
    positions = [p for p in positions if p >= 0]
    if not positions:
        return text[:window] + ("…" if len(text) > window else "")
    start = max(0, min(positions) - 80)
    if start > 0:
        next_space = text.find(" ", start)
        if next_space != -1 and next_space - start < 25:
            start = next_space + 1  # avoid starting mid-word
    end = min(len(text), start + window)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return prefix + text[start:end].strip() + suffix


def _snippet(chunk: KnowledgeChunk, source_name: str, score: float, query: str = "") -> dict:
    return {
        "chunk_id": chunk.id,
        "source_id": chunk.source_id,
        "name": source_name,
        "content": chunk.content,
        "focus": _focus_window(chunk.content, query) if query else chunk.content[:420],
        "score": round(float(score), 4),
    }
