"""Test fixtures — isolated SQLite database, ASGI client, no external LLM."""
import os

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_ai_receptionist.db"
os.environ["LLM_PROVIDER"] = "mock"
os.environ["EMBEDDINGS_PROVIDER"] = "local"
os.environ["ENVIRONMENT"] = "test"

import httpx
import pytest

from app.db import SessionLocal, init_db
from app.main import app

API = "/api"


@pytest.fixture(scope="session", autouse=True)
async def _db():
    import pathlib

    db_file = pathlib.Path("test_ai_receptionist.db")
    if db_file.exists():
        db_file.unlink()
    await init_db()
    yield
    if db_file.exists():
        db_file.unlink()


@pytest.fixture()
def client():
    """Context-manager factory: each `async with client as c` gets a fresh client."""
    transport = httpx.ASGITransport(app=app)

    class C:
        async def __aenter__(self):
            self._c = httpx.AsyncClient(transport=transport, base_url="http://test")
            return await self._c.__aenter__()

        async def __aexit__(self, *a):
            return await self._c.__aexit__(*a)

    return C()


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def register(client, slug: str, company: str = "Acme", email: str | None = None):
    email = email or f"admin@{slug}.example.com"
    async with client as c:
        r = await c.post(f"{API}/auth/register", json={
            "company_name": company,
            "slug": slug,
            "email": email,
            "password": "Password123!",
            "full_name": "Admin " + slug,
        })
        assert r.status_code == 201, r.text
        return r.json()


async def wait_sources_ready(client, token: str, timeout: float = 10.0):
    import asyncio

    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        async with client as c:
            r = await c.get(f"{API}/knowledge/sources", headers=auth(token))
            sources = r.json()
        if sources and all(s["status"] in ("ready", "error") for s in sources):
            return sources
        await asyncio.sleep(0.2)
    raise AssertionError("Les sources n'ont pas atteint un statut final")


async def add_faq(client, token: str, content: str, name: str = "FAQ"):
    async with client as c:
        r = await c.post(f"{API}/knowledge/sources", headers=auth(token), json={
            "type": "faq", "name": name, "content": content,
        })
        assert r.status_code == 201, r.text
        return r.json()
