"""run-agent 进程内进度（供前端轮询；单进程部署有效）。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

# project_id -> progress payload
_PROGRESS: Dict[str, Dict[str, Any]] = {}

STAGE_LABELS = {
    "starting": "正在启动学术 Agent…",
    "sync_zotero": "正在从 Zotero 同步文献…",
    "evidence": "正在构建引用证据（摘要 / 落地页 / PDF）…",
    "drafting": "Writer 正在分节撰写草稿…",
    "saving": "正在保存草稿版本…",
    "done": "已完成",
    "error": "运行失败",
}


def set_agent_progress(
    project_id: Any,
    stage: str,
    *,
    detail: str = "",
    percent: Optional[int] = None,
) -> None:
    pid = str(project_id)
    label = STAGE_LABELS.get(stage) or stage
    _PROGRESS[pid] = {
        "project_id": pid,
        "stage": stage,
        "label": label,
        "detail": (detail or "").strip(),
        "percent": percent,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "running": stage not in {"done", "error"},
    }


def clear_agent_progress(project_id: Any) -> None:
    _PROGRESS.pop(str(project_id), None)


def get_agent_progress(project_id: Any) -> Optional[Dict[str, Any]]:
    return _PROGRESS.get(str(project_id))
