"""Knowledge Base endpoints: upload documents, web import, FAQ/manual text, lifecycle."""
import binascii

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import audit
from ..db import get_session
from ..deps import CurrentUser, require_admin, require_agent, tenant_scope
from ..models import KnowledgeChunk, KnowledgeSource
from ..rag.ingest import ingest_source
from ..schemas import SourceIn, SourceOut, SourcePatch

router = APIRouter(prefix="/knowledge", tags=["knowledge"])

MAX_FILE_BYTES = 10 * 1024 * 1024

_EXT_TYPES = {
    ".pdf": "pdf", ".docx": "docx", ".xlsx": "xlsx", ".csv": "csv",
    ".txt": "txt", ".md": "markdown",
}


def _out(s: KnowledgeSource) -> SourceOut:
    return SourceOut(
        id=s.id, type=s.type, name=s.name, url=s.url, status=s.status,
        enabled=s.enabled, error=s.error, chunk_count=s.chunk_count,
        created_at=s.created_at, updated_at=s.updated_at,
    )


async def _run_ingestion(source_id: str) -> None:
    from ..db import SessionLocal

    async with SessionLocal() as session:
        source = await session.get(KnowledgeSource, source_id)
        if source:
            await ingest_source(session, source)


@router.get("/sources", response_model=list[SourceOut])
async def list_sources(
    db: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_agent),
):
    tenant_id = tenant_scope(user)
    rows = (
        await db.execute(
            select(KnowledgeSource)
            .where(KnowledgeSource.tenant_id == tenant_id)
            .order_by(KnowledgeSource.created_at.desc())
        )
    ).scalars().all()
    return [_out(s) for s in rows]


@router.post("/sources", response_model=SourceOut, status_code=201)
async def create_source(
    payload: SourceIn,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_admin),
):
    tenant_id = tenant_scope(user)
    if payload.type == "web" and not payload.url.startswith("http"):
        raise HTTPException(400, "Une source web nécessite une URL valide (http/https)")
    if payload.type in ("manual", "faq", "txt", "markdown") and not payload.content.strip():
        raise HTTPException(400, "Le contenu est vide")
    source = KnowledgeSource(
        tenant_id=tenant_id, type=payload.type, name=payload.name,
        url=payload.url, content=payload.content, status="pending",
    )
    db.add(source)
    await db.commit()
    await db.refresh(source)
    background.add_task(_run_ingestion, source.id)
    await audit(
        db, action="knowledge.source_created", tenant_id=tenant_id, user_id=user.id,
        actor=user.email, object_type="knowledge_source", object_id=source.id,
        details={"type": source.type, "name": source.name},
    )
    return _out(source)


@router.post("/sources/upload", response_model=SourceOut, status_code=201)
async def upload_source(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    name: str = Form(""),
    db: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_admin),
):
    tenant_id = tenant_scope(user)
    filename = file.filename or "document"
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    file_type = _EXT_TYPES.get(ext)
    if not file_type:
        raise HTTPException(400, f"Format non supporté : {ext or 'inconnu'} (PDF, DOCX, XLSX, CSV, TXT, MD)")
    data = await file.read()
    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(413, "Fichier trop volumineux (max 10 Mo)")
    source = KnowledgeSource(
        tenant_id=tenant_id, type=file_type, name=name or filename,
        content=binascii.hexlify(b"").decode(), status="pending",
    )
    # store raw text for text-ish formats so re-ingestion needs no file
    if file_type in ("txt", "markdown", "csv"):
        source.content = data.decode("utf-8", errors="replace")
    else:
        source.content = ""
    db.add(source)
    await db.commit()
    await db.refresh(source)
    background.add_task(_reingest_with_data, source.id, data)
    await audit(
        db, action="knowledge.source_uploaded", tenant_id=tenant_id, user_id=user.id,
        actor=user.email, object_type="knowledge_source", object_id=source.id,
        details={"type": file_type, "name": source.name, "bytes": len(data)},
    )
    return _out(source)


async def _reingest_with_data(source_id: str, data: bytes) -> None:
    from ..db import SessionLocal

    async with SessionLocal() as session:
        source = await session.get(KnowledgeSource, source_id)
        if source:
            await ingest_source(session, source, file_data=data)


@router.post("/sources/{source_id}/reingest", response_model=SourceOut)
async def reingest(
    source_id: str,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_admin),
):
    tenant_id = tenant_scope(user)
    source = await db.get(KnowledgeSource, source_id)
    if not source or source.tenant_id != tenant_id:
        raise HTTPException(404, "Source introuvable")
    if source.type == "web":
        background.add_task(_run_ingestion, source.id)
    elif source.content and source.type in ("txt", "markdown", "csv", "manual", "faq"):
        background.add_task(_run_ingestion, source.id)
    else:
        raise HTTPException(
            400,
            "Réimport d'un fichier binaire : supprimez et rechargez le document.",
        )
    source.status = "pending"
    await db.commit()
    await audit(
        db, action="knowledge.source_reingested", tenant_id=tenant_id, user_id=user.id,
        actor=user.email, object_type="knowledge_source", object_id=source.id,
    )
    return _out(source)


@router.patch("/sources/{source_id}", response_model=SourceOut)
async def patch_source(
    source_id: str,
    payload: SourcePatch,
    db: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_admin),
):
    tenant_id = tenant_scope(user)
    source = await db.get(KnowledgeSource, source_id)
    if not source or source.tenant_id != tenant_id:
        raise HTTPException(404, "Source introuvable")
    if payload.name is not None:
        source.name = payload.name
    if payload.url is not None:
        source.url = payload.url
    if payload.content is not None:
        source.content = payload.content
    if payload.enabled is not None:
        source.enabled = payload.enabled
    await db.commit()
    await audit(
        db, action="knowledge.source_updated", tenant_id=tenant_id, user_id=user.id,
        actor=user.email, object_type="knowledge_source", object_id=source.id,
        details={"enabled": source.enabled},
    )
    return _out(source)


@router.delete("/sources/{source_id}", status_code=204)
async def delete_source(
    source_id: str,
    db: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_admin),
):
    tenant_id = tenant_scope(user)
    source = await db.get(KnowledgeSource, source_id)
    if not source or source.tenant_id != tenant_id:
        raise HTTPException(404, "Source introuvable")
    await db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.source_id == source_id))
    await db.delete(source)
    await db.commit()
    await audit(
        db, action="knowledge.source_deleted", tenant_id=tenant_id, user_id=user.id,
        actor=user.email, object_type="knowledge_source", object_id=source_id,
        details={"name": source.name},
    )


@router.post("/search")
async def search(
    payload: dict,
    db: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_agent),
):
    """Search endpoint used by the dashboard (tenant-isolated)."""
    from ..rag.retrieval import search_knowledge

    tenant_id = tenant_scope(user)
    query = str(payload.get("query", ""))[:500]
    results = await search_knowledge(db, tenant_id, query, limit=int(payload.get("limit", 8)))
    return {"query": query, "results": results}
