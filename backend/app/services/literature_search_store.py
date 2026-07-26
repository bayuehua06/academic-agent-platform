"""文献检索会话（MVP：进程内内存；重启清空）。"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


class LiteratureSearchStore:
    """按 run_id 保存候选结果。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._runs: Dict[str, Dict[str, Any]] = {}

    def create(
        self,
        *,
        project_id: str,
        outline_heading: str,
        query: str,
        providers: List[str],
        candidates: List[Dict[str, Any]],
        status: str = "completed",
        error: Optional[str] = None,
    ) -> Dict[str, Any]:
        run_id = str(uuid.uuid4())
        record = {
            "id": run_id,
            "project_id": project_id,
            "outline_heading": outline_heading,
            "query": query,
            "providers": providers,
            "status": status,
            "error": error,
            "candidates": candidates,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            self._runs[run_id] = record
        return record

    def get(self, run_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._runs.get(run_id)


literature_search_store = LiteratureSearchStore()
