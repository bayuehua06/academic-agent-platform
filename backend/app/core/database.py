"""异步数据库连接与会话管理。"""

from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    """SQLAlchemy 声明式基类。"""

    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖：提供异步数据库会话。"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def _hard_cut_draft_columns(conn) -> None:
    """开发环境硬切：为已有 draft_versions / draft_workings 补列。"""
    dialect = conn.engine.dialect.name
    if dialect == "sqlite":
        # 测试库走 create_all；此处仅防手动 sqlite
        stmts = [
            "ALTER TABLE draft_versions ADD COLUMN major INTEGER",
            "ALTER TABLE draft_versions ADD COLUMN minor INTEGER DEFAULT 0",
            "ALTER TABLE draft_versions ADD COLUMN parent_version_id CHAR(36)",
            "ALTER TABLE draft_versions ADD COLUMN base_version_id CHAR(36)",
            "ALTER TABLE draft_workings ADD COLUMN working_facts TEXT",
            "ALTER TABLE draft_workings ADD COLUMN stale_headings TEXT",
            "ALTER TABLE projects ADD COLUMN confirmed_facts TEXT",
            "ALTER TABLE projects ADD COLUMN zotero_binding_mode VARCHAR(20)",
            "ALTER TABLE projects ADD COLUMN zotero_library_type VARCHAR(20)",
            "ALTER TABLE projects ADD COLUMN zotero_library_id VARCHAR(100)",
            "ALTER TABLE literatures ADD COLUMN landing_url VARCHAR(1000)",
            "ALTER TABLE literatures ADD COLUMN evidence_text TEXT",
            "ALTER TABLE literatures ADD COLUMN evidence_tier VARCHAR(30)",
            "ALTER TABLE literatures ADD COLUMN evidence_source VARCHAR(30)",
            "ALTER TABLE literatures ADD COLUMN evidence_content_key VARCHAR(500)",
            "ALTER TABLE literatures ADD COLUMN evidence_fetched_at TIMESTAMP",
        ]
        for sql in stmts:
            try:
                await conn.execute(text(sql))
            except Exception:  # noqa: BLE001
                pass
        return

    # PostgreSQL
    stmts = [
        "ALTER TABLE draft_versions ADD COLUMN IF NOT EXISTS major INTEGER",
        "ALTER TABLE draft_versions ADD COLUMN IF NOT EXISTS minor INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE draft_versions ADD COLUMN IF NOT EXISTS parent_version_id UUID",
        "ALTER TABLE draft_versions ADD COLUMN IF NOT EXISTS base_version_id UUID",
        # 回填：旧版本 major=version_number, minor=0
        "UPDATE draft_versions SET major = version_number WHERE major IS NULL",
        "ALTER TABLE draft_workings ADD COLUMN IF NOT EXISTS working_facts TEXT",
        "ALTER TABLE draft_workings ADD COLUMN IF NOT EXISTS stale_headings JSONB",
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS confirmed_facts TEXT",
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS zotero_binding_mode VARCHAR(20)",
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS zotero_library_type VARCHAR(20)",
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS zotero_library_id VARCHAR(100)",
        "ALTER TABLE literatures ADD COLUMN IF NOT EXISTS landing_url VARCHAR(1000)",
        "ALTER TABLE literatures ADD COLUMN IF NOT EXISTS evidence_text TEXT",
        "ALTER TABLE literatures ADD COLUMN IF NOT EXISTS evidence_tier VARCHAR(30)",
        "ALTER TABLE literatures ADD COLUMN IF NOT EXISTS evidence_source VARCHAR(30)",
        "ALTER TABLE literatures ADD COLUMN IF NOT EXISTS evidence_content_key VARCHAR(500)",
        "ALTER TABLE literatures ADD COLUMN IF NOT EXISTS evidence_fetched_at TIMESTAMPTZ",
    ]
    for sql in stmts:
        await conn.execute(text(sql))


async def init_db() -> None:
    """创建所有表（开发环境；生产建议使用 Alembic）。"""
    from app.db import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        try:
            await _hard_cut_draft_columns(conn)
        except Exception:  # noqa: BLE001
            # 表尚不存在等边角；create_all 已覆盖新库
            pass
