"""草稿版本号（major.minor）与展示标签。"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DraftVersion
from app.services.draft_sections import apply_section_overrides  # noqa: F401


def format_display_label(major: int, minor: int) -> str:
    """minor==0 → '9'；否则 → '9.1'。"""
    if minor <= 0:
        return str(major)
    return f"{major}.{minor}"


def labels_from_draft(draft: DraftVersion) -> tuple[int, int, str]:
    """兼容旧行：无 major 时用 version_number。"""
    major = int(draft.major if draft.major is not None else draft.version_number)
    minor = int(draft.minor if draft.minor is not None else 0)
    return major, minor, format_display_label(major, minor)


async def next_version_number(db: AsyncSession, project_id) -> int:
    result = await db.execute(
        select(func.coalesce(func.max(DraftVersion.version_number), 0)).where(
            DraftVersion.project_id == project_id
        )
    )
    return int(result.scalar_one()) + 1


async def next_agent_major(db: AsyncSession, project_id) -> int:
    """Agent 新稿：新的 major，minor=0。"""
    result = await db.execute(
        select(func.coalesce(func.max(DraftVersion.major), 0)).where(
            DraftVersion.project_id == project_id
        )
    )
    max_major = result.scalar_one()
    if max_major is None or int(max_major) == 0:
        result2 = await db.execute(
            select(func.coalesce(func.max(DraftVersion.version_number), 0)).where(
                DraftVersion.project_id == project_id
            )
        )
        return int(result2.scalar_one()) + 1
    return int(max_major) + 1


async def next_minor_for_major(db: AsyncSession, project_id, major: int) -> int:
    result = await db.execute(
        select(func.coalesce(func.max(DraftVersion.minor), -1)).where(
            DraftVersion.project_id == project_id,
            DraftVersion.major == major,
        )
    )
    current = result.scalar_one()
    if current is None:
        return 1
    return int(current) + 1
