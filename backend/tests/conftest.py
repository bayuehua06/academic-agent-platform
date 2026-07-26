"""测试公共夹具：SQLite 内存库 + FastAPI 依赖覆盖。"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

from app.api import api_router
from app.core.config import get_settings
from app.core.database import Base, get_db
from app.core.security import create_access_token, get_password_hash
from app.db.models import User
from app.services.zotero_service import zotero_service


# ---------- SQLite 兼容 PostgreSQL 专用类型 ----------


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type: Any, _compiler: Any, **_kw: Any) -> str:
    return "JSON"


@compiles(UUID, "sqlite")
def _compile_uuid_sqlite(_type: Any, _compiler: Any, **_kw: Any) -> str:
    return "CHAR(36)"


@pytest.fixture(autouse=True)
def _isolate_external_credentials(monkeypatch: pytest.MonkeyPatch):
    """测试不触达真实 Zotero / AUT（避免本机 .env 凭据干扰）。"""
    for key in (
        "ZOTERO_LIBRARY_ID",
        "ZOTERO_API_KEY",
        "AUT_USERNAME",
        "AUT_PASSWORD",
    ):
        monkeypatch.setenv(key, "")
    get_settings.cache_clear()
    zotero_service.library_id = ""
    zotero_service.api_key = ""
    zotero_service._client = None
    yield
    get_settings.cache_clear()


@pytest.fixture
async def db_engine():
    """每个测试使用独立内存 SQLite（StaticPool 保证同库连接）。"""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # SQLite 外键
    @event.listens_for(engine.sync_engine, "connect")
    def _fk_pragma(dbapi_conn, _connection_record):  # noqa: ANN001
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    # 注册模型 metadata
    from app.db import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine
    await engine.dispose()


@pytest.fixture
async def session_factory(db_engine):
    return async_sessionmaker(
        bind=db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


@pytest.fixture
async def app(session_factory) -> FastAPI:
    """构造不依赖真实 PostgreSQL 的测试应用。"""
    test_app = FastAPI(title="Academic Agent Platform Test")
    test_app.include_router(api_router, prefix="/api")

    @test_app.get("/health")
    async def health() -> dict:
        return {"status": "ok", "app": "test"}

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    test_app.dependency_overrides[get_db] = override_get_db
    return test_app


@pytest.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def test_user(session_factory) -> User:
    """预置测试用户。"""
    async with session_factory() as session:
        user = User(
            username="tester",
            email="tester@example.com",
            password_hash=get_password_hash("secret123"),
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        # 脱离会话后仍可用的简单属性副本
        return user


@pytest.fixture
def auth_headers(test_user: User) -> dict[str, str]:
    token = create_access_token(subject=str(test_user.id))
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def auth_client(client: AsyncClient, auth_headers: dict[str, str]) -> AsyncClient:
    """带鉴权头的客户端（复用同一 AsyncClient，通过默认 headers）。"""
    client.headers.update(auth_headers)
    return client
