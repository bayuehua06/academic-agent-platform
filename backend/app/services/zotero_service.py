"""Zotero 集成服务（pyzotero）。"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class ZoteroService:
    """封装 Zotero API：按 DOI 添加条目并归档到 Collection。"""

    def __init__(
        self,
        library_id: Optional[str] = None,
        api_key: Optional[str] = None,
        library_type: Optional[str] = None,
    ) -> None:
        self.library_id = library_id or settings.zotero_library_id
        self.api_key = api_key or settings.zotero_api_key
        self.library_type = library_type or settings.zotero_library_type
        self._client = None

    @property
    def is_configured(self) -> bool:
        return bool(self.library_id and self.api_key)

    def _get_client(self):
        if self._client is not None:
            return self._client
        if not self.is_configured:
            raise RuntimeError("Zotero 未配置：请设置 ZOTERO_LIBRARY_ID 与 ZOTERO_API_KEY")
        from pyzotero import zotero

        self._client = zotero.Zotero(self.library_id, self.library_type, self.api_key)
        return self._client

    def add_item_by_doi(
        self,
        doi: str,
        collection_id: Optional[str] = None,
        fallback_meta: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """
        通过 DOI 添加文献到 Zotero，返回 item_key。

        若 DOI 检索失败，使用 fallback_meta 手动创建条目。
        """
        if not self.is_configured:
            logger.warning("Zotero 未配置，跳过同步 DOI=%s", doi)
            return None

        zot = self._get_client()
        item_key: Optional[str] = None

        try:
            # pyzotero 支持通过 DOI 创建条目（需 Zotero 翻译器服务）
            created = zot.create_items([{"itemType": "journalArticle", "DOI": doi}])
            if created and created.get("successful"):
                item_key = next(iter(created["successful"].values()))["key"]
        except Exception as exc:  # noqa: BLE001
            logger.warning("DOI 自动创建失败 (%s): %s，尝试手动条目", doi, exc)

        if not item_key and fallback_meta:
            item_key = self._create_manual_item(fallback_meta, collection_id)
            return item_key

        if item_key and collection_id:
            self._add_to_collection(item_key, collection_id)

        return item_key

    def _create_manual_item(
        self,
        meta: Dict[str, Any],
        collection_id: Optional[str] = None,
    ) -> Optional[str]:
        """根据元数据手动创建 journalArticle 条目。"""
        zot = self._get_client()
        template = zot.item_template("journalArticle")
        template["title"] = meta.get("title", "Untitled")
        template["DOI"] = meta.get("doi", "")
        template["abstractNote"] = meta.get("abstract", "")
        template["date"] = str(meta.get("year", ""))

        creators = []
        for name in meta.get("authors") or []:
            parts = str(name).rsplit(" ", 1)
            if len(parts) == 2:
                creators.append(
                    {"creatorType": "author", "firstName": parts[0], "lastName": parts[1]}
                )
            else:
                creators.append({"creatorType": "author", "name": name})
        template["creators"] = creators

        if collection_id:
            template["collections"] = [collection_id]

        try:
            result = zot.create_items([template])
            if result and result.get("successful"):
                return next(iter(result["successful"].values()))["key"]
        except Exception as exc:  # noqa: BLE001
            logger.error("手动创建 Zotero 条目失败: %s", exc)
        return None

    def _add_to_collection(self, item_key: str, collection_id: str) -> None:
        """将已有条目加入指定 Collection。"""
        try:
            zot = self._get_client()
            zot.addto_collection(collection_id, zot.item(item_key))
        except Exception as exc:  # noqa: BLE001
            logger.warning("添加到 Collection 失败: %s", exc)

    def list_collection_items(self, collection_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """列出 Collection 中的条目。"""
        if not self.is_configured:
            return []
        zot = self._get_client()
        return zot.collection_items(collection_id, limit=limit)


# 模块级单例，便于服务层调用
zotero_service = ZoteroService()
