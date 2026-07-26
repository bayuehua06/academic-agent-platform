"""文献检索库全局注册表（入口 URL 来自 .env；项目只勾选 id）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from app.core.config import get_settings


@dataclass(frozen=True)
class LiteratureProvider:
    """单个检索库的全局定义。"""

    id: str
    name: str
    entry_url: str
    implemented: bool


def parse_database_ids(raw: Optional[str | list]) -> List[str]:
    """解析逗号分隔或 list 为规范化 id 列表。"""
    if raw is None:
        return []
    if isinstance(raw, list):
        items = [str(x).strip().lower() for x in raw]
    else:
        items = [p.strip().lower() for p in str(raw).split(",")]
    out: List[str] = []
    seen: set[str] = set()
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def default_database_ids() -> List[str]:
    """新建项目默认启用的库。"""
    settings = get_settings()
    ids = parse_database_ids(settings.literature_default_databases)
    return ids or ["ieee"]


def get_provider_registry() -> Dict[str, LiteratureProvider]:
    """返回当前环境可用的检索库注册表。"""
    settings = get_settings()
    return {
        "ieee": LiteratureProvider(
            id="ieee",
            name="IEEE Xplore",
            entry_url=(settings.literature_db_ieee_url or "").strip()
            or "https://library.aut.ac.nz/databases/ieee-xplore",
            implemented=True,
        ),
        "acm": LiteratureProvider(
            id="acm",
            name="ACM Digital Library",
            entry_url=(settings.literature_db_acm_url or "").strip()
            or "https://library.aut.ac.nz/databases/acm-digital-library",
            implemented=True,
        ),
    }


def list_providers() -> List[dict]:
    """API 友好列表。"""
    return [
        {
            "id": p.id,
            "name": p.name,
            "entry_url": p.entry_url,
            "implemented": p.implemented,
        }
        for p in get_provider_registry().values()
    ]


def resolve_providers_for_project(project_databases: Optional[list]) -> List[LiteratureProvider]:
    """按项目勾选解析 provider；空则用默认。"""
    registry = get_provider_registry()
    ids = parse_database_ids(project_databases) or default_database_ids()
    providers: List[LiteratureProvider] = []
    for pid in ids:
        if pid not in registry:
            raise ValueError(f"未知检索库: {pid!r}（可选: {', '.join(registry)}）")
        providers.append(registry[pid])
    return providers
