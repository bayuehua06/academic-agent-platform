"""Zotero 集成服务（pyzotero）。"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class ZoteroService:
    """封装 Zotero API：连通检测、Collection 结构、条目写入。"""

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

    def ping(self) -> Dict[str, Any]:
        """
        真实连通检测。

        Returns:
            含 ok / configured / library 摘要或 error 的字典。
        """
        if not self.is_configured:
            return {
                "ok": False,
                "configured": False,
                "error": "未配置 ZOTERO_LIBRARY_ID 或 ZOTERO_API_KEY",
            }
        try:
            zot = self._get_client()
            # 轻量调用：取库内集合数量/前几条
            collections = zot.collections()
            key_count = len(collections) if isinstance(collections, list) else 0
            return {
                "ok": True,
                "configured": True,
                "library_id": self.library_id,
                "library_type": self.library_type,
                "collection_count": key_count,
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("Zotero ping 失败: %s", exc)
            return {
                "ok": False,
                "configured": True,
                "library_id": self.library_id,
                "library_type": self.library_type,
                "error": str(exc),
            }

    def list_collections(self, limit: int = 100) -> List[Dict[str, Any]]:
        """列出库内集合（调试用）。"""
        if not self.is_configured:
            return []
        zot = self._get_client()
        raw = zot.collections(limit=limit)
        out: List[Dict[str, Any]] = []
        for item in raw or []:
            data = item.get("data") if isinstance(item, dict) else None
            if not data:
                continue
            out.append(
                {
                    "key": data.get("key"),
                    "name": data.get("name"),
                    "parentCollection": data.get("parentCollection") or False,
                }
            )
        return out

    def collection_exists(self, collection_key: str) -> bool:
        """校验集合是否可读。"""
        key = (collection_key or "").strip()
        if not key or not self.is_configured:
            return False
        try:
            self._get_client().collection(key)
            return True
        except Exception:  # noqa: BLE001
            return False

    def list_accessible_top_collections(self) -> List[Dict[str, Any]]:
        """
        聚合当前 API Key 可访问的顶层 Collections：个人库 + 各 Group。

        依赖 .env 中的个人 ZOTERO_LIBRARY_ID（用于 groups 发现入口）。
        """
        api_key = self.api_key or settings.zotero_api_key
        user_id = (settings.zotero_library_id or "").strip()
        if not api_key or not user_id:
            raise RuntimeError("Zotero 未配置：需要 ZOTERO_API_KEY 与个人 ZOTERO_LIBRARY_ID")

        out: List[Dict[str, Any]] = []

        def _append_tops(
            svc: "ZoteroService",
            library_type: str,
            library_id: str,
            library_name: str,
        ) -> None:
            for row in svc.list_collections(limit=200):
                parent = row.get("parentCollection")
                if parent:
                    continue
                key = row.get("key")
                if not key:
                    continue
                out.append(
                    {
                        "key": key,
                        "name": (row.get("name") or "").strip() or key,
                        "library_type": library_type,
                        "library_id": str(library_id),
                        "library_name": library_name,
                    }
                )

        user_svc = ZoteroService(library_id=user_id, library_type="user", api_key=api_key)
        _append_tops(user_svc, "user", user_id, "My Library")

        try:
            groups = user_svc._get_client().groups() or []
        except Exception as exc:  # noqa: BLE001
            logger.warning("列举 Zotero groups 失败: %s", exc)
            groups = []

        for group in groups:
            if not isinstance(group, dict):
                continue
            data = group.get("data") if isinstance(group.get("data"), dict) else {}
            gid = group.get("id") or data.get("id")
            if gid is None:
                continue
            gname = (data.get("name") or group.get("name") or f"Group {gid}").strip()
            try:
                gsvc = ZoteroService(
                    library_id=str(gid), library_type="group", api_key=api_key
                )
                _append_tops(gsvc, "group", str(gid), gname)
            except Exception as exc:  # noqa: BLE001
                logger.warning("跳过不可访问 Group %s: %s", gid, exc)

        return out

    def find_child_collection(
        self, name: str, parent_key: Optional[str] = None
    ) -> Optional[str]:
        """按名称查找子集合（parent_key 为 None 时查顶层）。"""
        zot = self._get_client()
        for item in zot.collections() or []:
            data = item.get("data") or {}
            if (data.get("name") or "").strip() != name.strip():
                continue
            parent = data.get("parentCollection") or False
            if parent_key is None:
                if not parent:
                    return data.get("key")
            elif parent == parent_key:
                return data.get("key")
        return None

    def ensure_collection(self, name: str, parent_key: Optional[str] = None) -> str:
        """
        确保名为 name 的集合存在；已存在则返回 key，否则创建。

        Args:
            name: 集合名称
            parent_key: 父集合 key；None 表示顶层

        Returns:
            集合 key
        """
        existing = self.find_child_collection(name, parent_key)
        if existing:
            return existing

        zot = self._get_client()
        payload: Dict[str, Any] = {"name": name.strip()}
        if parent_key:
            payload["parentCollection"] = parent_key

        result = zot.create_collections([payload])
        if not result or not result.get("successful"):
            failed = (result or {}).get("failed") or (result or {}).get("unchanged")
            raise RuntimeError(f"创建 Zotero Collection 失败: {name!r} → {failed}")
        created = next(iter(result["successful"].values()))
        key = created.get("key") if isinstance(created, dict) else None
        if not key:
            raise RuntimeError(f"创建 Collection 未返回 key: {name!r}")
        return key

    def ensure_project_structure(
        self,
        project_title: str,
        chapter_headings: List[str],
        existing_root_key: Optional[str] = None,
    ) -> Tuple[str, Dict[str, str]]:
        """
        确保「项目顶层 Collection + 章节 Subcollection」。

        Returns:
            (root_collection_key, {heading: subcollection_key})
        """
        root_key = existing_root_key
        if root_key:
            # 校验仍存在；不存在则重建
            try:
                zot = self._get_client()
                zot.collection(root_key)
            except Exception:  # noqa: BLE001
                logger.warning("已存 zotero_collection_id 无效，将重建: %s", root_key)
                root_key = None

        if not root_key:
            root_key = self.ensure_collection(project_title.strip(), parent_key=None)

        sub_map: Dict[str, str] = {}
        for heading in chapter_headings:
            h = (heading or "").strip()
            if not h:
                continue
            sub_map[h] = self.ensure_collection(h, parent_key=root_key)
        return root_key, sub_map

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

    def create_item_from_meta(
        self,
        meta: Dict[str, Any],
        collection_id: Optional[str] = None,
    ) -> Optional[str]:
        """按元数据创建条目并可选加入集合；优先 DOI。"""
        doi = (meta.get("doi") or "").strip()
        if doi:
            key = self.add_item_by_doi(doi, collection_id=collection_id, fallback_meta=meta)
            if key:
                return key
        return self._create_manual_item(meta, collection_id)

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
        template["url"] = meta.get("url", "")
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
        """列出 Collection 中的条目（含附件等原始返回）。"""
        if not self.is_configured:
            return []
        zot = self._get_client()
        return zot.collection_items(collection_id, limit=limit)

    def list_child_collections(self, parent_key: str) -> List[Dict[str, str]]:
        """列出某集合下的直接子集合：[{key, name}, ...]。"""
        zot = self._get_client()
        out: List[Dict[str, str]] = []
        for item in zot.collections() or []:
            data = item.get("data") or {}
            if data.get("parentCollection") == parent_key:
                key = data.get("key")
                if not key:
                    continue
                out.append({"key": key, "name": (data.get("name") or "").strip()})
        return out

    def fetch_project_collection_items(
        self, root_collection_key: str, limit_per_collection: int = 200
    ) -> List[Dict[str, Any]]:
        """
        拉取项目顶层 Collection + 各章节子集合中的文献条目。

        返回规范化字典列表（去重 by zotero_item_key；子集合优先保留章节名）。
        """
        if not self.is_configured:
            raise RuntimeError("Zotero 未配置")
        root = (root_collection_key or "").strip()
        if not root:
            raise ValueError("root_collection_key 不能为空")

        by_key: Dict[str, Dict[str, Any]] = {}

        def _ingest(collection_key: str, outline_heading: Optional[str]) -> None:
            for raw in self.list_collection_items(collection_key, limit=limit_per_collection):
                meta = self._normalize_item(raw)
                if not meta:
                    continue
                item_key = meta["zotero_item_key"]
                meta["zotero_subcollection_key"] = collection_key
                meta["outline_heading"] = outline_heading
                # 已在子集合中的条目优先保留章节 heading
                if item_key in by_key and by_key[item_key].get("outline_heading") and not outline_heading:
                    continue
                by_key[item_key] = meta

        _ingest(root, None)
        for child in self.list_child_collections(root):
            _ingest(child["key"], child["name"] or None)

        return list(by_key.values())

    @staticmethod
    def _normalize_item(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """将 pyzotero 条目转为写作可用元数据；跳过附件/笔记。"""
        data = raw.get("data") if isinstance(raw, dict) else None
        if not isinstance(data, dict):
            return None
        item_type = (data.get("itemType") or "").strip()
        if item_type in {"attachment", "note", "annotation"}:
            return None
        key = data.get("key") or raw.get("key")
        if not key:
            return None
        title = (data.get("title") or "").strip() or "Untitled"
        authors: List[str] = []
        for creator in data.get("creators") or []:
            if not isinstance(creator, dict):
                continue
            if creator.get("name"):
                authors.append(str(creator["name"]).strip())
                continue
            first = (creator.get("firstName") or "").strip()
            last = (creator.get("lastName") or "").strip()
            full = f"{first} {last}".strip()
            if full:
                authors.append(full)
        date = str(data.get("date") or data.get("issueDate") or "").strip()
        year = None
        for token in date.replace("/", "-").split("-"):
            token = token.strip()
            if len(token) >= 4 and token[:4].isdigit():
                year = token[:4]
                break
        doi = (data.get("DOI") or data.get("doi") or "").strip() or None
        abstract = (data.get("abstractNote") or "").strip() or None
        url = (data.get("url") or "").strip() or None
        return {
            "zotero_item_key": key,
            "title": title,
            "authors": authors,
            "year": year,
            "doi": doi,
            "abstract": abstract,
            "url": url,
        }

    def list_pdf_attachment_keys(self, item_key: str) -> List[str]:
        """返回父条目下可下载的 PDF 附件 key（优先 application/pdf / .pdf）。"""
        key = (item_key or "").strip()
        if not key or not self.is_configured:
            return []
        try:
            children = self._get_client().children(key) or []
        except Exception as exc:  # noqa: BLE001
            logger.warning("Zotero children 失败 item=%s: %s", key, exc)
            return []
        pdf_keys: List[str] = []
        for child in children:
            data = child.get("data") if isinstance(child, dict) else None
            if not isinstance(data, dict):
                continue
            if (data.get("itemType") or "").strip() != "attachment":
                continue
            content_type = (data.get("contentType") or "").lower()
            filename = (data.get("filename") or data.get("title") or "").lower()
            link_mode = (data.get("linkMode") or "").strip()
            # linked_url 无本地文件可 dump
            if link_mode in {"linked_url"}:
                continue
            if "pdf" in content_type or filename.endswith(".pdf"):
                att_key = data.get("key") or child.get("key")
                if att_key:
                    pdf_keys.append(str(att_key))
        return pdf_keys

    def download_file_bytes(self, attachment_key: str) -> bytes:
        """下载附件二进制（pyzotero file）。"""
        key = (attachment_key or "").strip()
        if not key or not self.is_configured:
            return b""
        try:
            data = self._get_client().file(key)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Zotero file 下载失败 attachment=%s: %s", key, exc)
            return b""
        if isinstance(data, (bytes, bytearray)):
            return bytes(data)
        if isinstance(data, str):
            return data.encode("utf-8", errors="ignore")
        return b""


# 模块级单例，便于服务层调用
zotero_service = ZoteroService()


def zotero_for_project(project: Any) -> ZoteroService:
    """
    按项目绑定的 library 返回客户端；无项目级配置时回退全局单例（便于测试 patch）。

    project 需具备 zotero_library_id / zotero_library_type 属性（可为 ORM）。
    """
    lib_id = (getattr(project, "zotero_library_id", None) or "").strip()
    lib_type = (getattr(project, "zotero_library_type", None) or "").strip()
    if not lib_id:
        lib_id = (settings.zotero_library_id or "").strip()
    if not lib_type:
        lib_type = (settings.zotero_library_type or "user").strip() or "user"

    singleton_id = (zotero_service.library_id or settings.zotero_library_id or "").strip()
    singleton_type = (zotero_service.library_type or settings.zotero_library_type or "user").strip()
    if lib_id == singleton_id and lib_type == singleton_type:
        return zotero_service

    api_key = zotero_service.api_key or settings.zotero_api_key
    return ZoteroService(library_id=lib_id, library_type=lib_type, api_key=api_key)
