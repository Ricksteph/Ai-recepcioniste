"""Knowledge Base ingestion pipeline (§8.2):
Source → extraction → cleaning → segmentation → embeddings → indexation.
Every chunk is stored with its tenant_id: retrieval can never cross tenants (§24).
"""
import logging

import httpx
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..llm.orchestrator import embed
from ..models import KnowledgeChunk, KnowledgeSource
from .chunking import (
    chunk_text,
    extract_csv,
    extract_docx,
    extract_html,
    extract_pdf,
    extract_xlsx,
)

logger = logging.getLogger("ai_receptionist.rag")

WEB_FETCH_TIMEOUT = 20


def extract_content(source: KnowledgeSource, data: bytes | None) -> str:
    if source.type in ("manual", "faq", "txt", "markdown"):
        return source.content or ""
    if data is None:
        return ""
    if source.type == "pdf":
        return extract_pdf(data)
    if source.type == "docx":
        return extract_docx(data)
    if source.type == "xlsx":
        return extract_xlsx(data)
    if source.type == "csv":
        return extract_csv(data)
    if source.type == "web":
        return extract_html(data.decode("utf-8", errors="replace"))
    return data.decode("utf-8", errors="replace")


async def fetch_url(url: str) -> bytes | None:
    try:
        async with httpx.AsyncClient(timeout=WEB_FETCH_TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "AI-Receptionist-Bot/1.0"})
            resp.raise_for_status()
            return resp.content
    except httpx.HTTPError as exc:
        logger.warning("Fetch impossible %s : %s", url, exc)
        return None


async def ingest_source(
    db: AsyncSession, source: KnowledgeSource, *, file_data: bytes | None = None
) -> int:
    """(Re)build the chunks + embeddings for one source. Returns the chunk count."""
    source.status = "processing"
    source.error = ""
    await db.commit()

    try:
        if source.type == "web" and not file_data:
            file_data = await fetch_url(source.url)
            if file_data is None:
                raise ValueError(f"Impossible de récupérer la page {source.url}")

        raw = extract_content(source, file_data)
        if not raw or not raw.strip():
            raise ValueError("Document vide ou extraction impossible")

        chunks = chunk_text(raw)
        if not chunks:
            raise ValueError("Aucun contenu indexable après nettoyage")

        # replace previous chunks (idempotent re-ingestion)
        await db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.source_id == source.id))

        vectors = await embed(chunks)
        for i, (content, vec) in enumerate(zip(chunks, vectors)):
            db.add(
                KnowledgeChunk(
                    tenant_id=source.tenant_id,
                    source_id=source.id,
                    position=i,
                    content=content,
                    embedding=_serialize(vec),
                )
            )
        source.chunk_count = len(chunks)
        source.status = "ready"
        source.error = ""
        await db.commit()
        return len(chunks)
    except Exception as exc:  # noqa: BLE001 — ingestion failures must be visible, not fatal
        logger.exception("Ingestion échouée pour %s", source.name)
        source.status = "error"
        source.error = str(exc)[:1000]
        await db.commit()
        return 0


def _serialize(vec: list[float]):
    """pgvector accepts lists directly; SQLite stores a JSON string."""
    from ..db import is_postgres

    if is_postgres():
        return vec
    import json

    return json.dumps(vec)


async def source_stats(db: AsyncSession, tenant_id: str) -> dict:
    total = (await db.execute(
        select(func.count()).select_from(KnowledgeSource).where(KnowledgeSource.tenant_id == tenant_id)
    )).scalar() or 0
    ready = (await db.execute(
        select(func.count()).select_from(KnowledgeSource).where(
            KnowledgeSource.tenant_id == tenant_id, KnowledgeSource.status == "ready"
        )
    )).scalar() or 0
    chunk_count = (await db.execute(
        select(func.count()).select_from(KnowledgeChunk).where(KnowledgeChunk.tenant_id == tenant_id)
    )).scalar() or 0
    return {"total": total, "ready": ready, "chunks": chunk_count}
