"""FastAPI application assembly (cahier des charges §21)."""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .db import init_db
from .routers import (
    analytics,
    appointments,
    auth,
    conversations,
    knowledge,
    leads,
    public,
    rules,
    tenants,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    logging.getLogger("ai_receptionist").info(
        "AI Receptionist démarré (env=%s)", settings.environment
    )
    yield


app = FastAPI(
    title="AI Receptionist API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API = settings.api_prefix
app.include_router(auth.router, prefix=API)
app.include_router(tenants.router, prefix=API)
app.include_router(knowledge.router, prefix=API)
app.include_router(rules.router, prefix=API)
app.include_router(conversations.router, prefix=API)
app.include_router(leads.router, prefix=API)
app.include_router(appointments.router, prefix=API)
app.include_router(analytics.router, prefix=API)
app.include_router(public.router, prefix=API)


@app.get("/health")
async def health():
    from .db import engine

    return {
        "status": "ok",
        "database": engine.dialect.name,
        "llm_provider": settings.llm_provider,
        "environment": settings.environment,
    }


# Embeddable widget (§15) — drop <script src=".../widget.js" data-slug="..."></script>
_WIDGET_PATH = Path(__file__).parent / "static" / "widget.js"
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


@app.get("/widget.js", include_in_schema=False)
async def widget_js():
    return FileResponse(_WIDGET_PATH, media_type="application/javascript")
