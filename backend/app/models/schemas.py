"""Pydantic v2 Schema 定义。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# ---------- Auth ----------


class UserRegister(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=128)


class UserLogin(BaseModel):
    username: str
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    username: str
    email: EmailStr
    created_at: datetime


# ---------- Projects ----------


class ProjectCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    zotero_collection_id: Optional[str] = None


class ProjectUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    zotero_collection_id: Optional[str] = None
    status: Optional[str] = None
    # 定稿字段：Phase 2+ 主要由 refresh 写入；允许手工微调
    assessment_summary: Optional[str] = None
    paper_outline: Optional[Any] = None
    specific_requirements: Optional[str] = None


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    title: str
    assessment_summary: Optional[str] = None
    paper_outline: Optional[Any] = None
    outline_locked_at: Optional[datetime] = None
    specific_requirements: Optional[str] = None
    zotero_collection_id: Optional[str] = None
    status: str
    created_at: datetime
    updated_at: datetime
    literature_count: int = 0
    source_document_count: int = 0
    latest_version: Optional[int] = None
    outline_ready: bool = False
    assessment_ready: bool = False


# ---------- Source documents ----------


class SourceDocumentCreate(BaseModel):
    """粘贴创建源文档。"""

    role: str = Field(..., description="ASSESSMENT | BACKGROUND | OUTLINE | SPECIFIC")
    source_type: str = Field("PASTE", description="PASTE | UPLOAD | NOTEBOOKLM")
    title: Optional[str] = None
    raw_text: Optional[str] = None
    notebook_url: Optional[str] = None


class SourceDocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    role: str
    source_type: str
    title: Optional[str] = None
    notebook_url: Optional[str] = None
    original_filename: Optional[str] = None
    content_type: Optional[str] = None
    storage_path: Optional[str] = None
    raw_text: Optional[str] = None
    summary_text: Optional[str] = None
    summary_json: Optional[Any] = None
    status: str
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    summarized_at: Optional[datetime] = None


class OutlineLockRequest(BaseModel):
    """将指定 OUTLINE 源文档锁定为 projects.paper_outline。"""

    source_id: Optional[UUID] = None


class NotebookSyncCreate(BaseModel):
    """抓取 NotebookLM 对话，写入 BACKGROUND + NOTEBOOKLM 源文档。"""

    notebook_url: str
    use_browser: bool = True


# ---------- Literature ----------


class LiteratureOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    zotero_item_key: Optional[str] = None
    title: str
    authors: Optional[List[str]] = None
    year: Optional[str] = None
    doi: Optional[str] = None
    abstract: Optional[str] = None
    relevance_score: Optional[float] = None
    selected_for_draft: bool
    created_at: datetime


class LiteratureUpdate(BaseModel):
    selected_for_draft: Optional[bool] = None
    relevance_score: Optional[float] = None


# ---------- Drafts ----------


class DraftVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    version_number: int
    content_markdown: str
    apa_references_block: Optional[str] = None
    source_type: str
    changelog: Optional[str] = None
    created_at: datetime


class DraftExportRequest(BaseModel):
    version_id: Optional[UUID] = None
    format: str = Field("docx", pattern="^(docx|pdf)$")


class AgentRunRequest(BaseModel):
    """触发 LangGraph 学术写作工作流。"""

    max_papers: int = Field(5, ge=1, le=20)
    skip_search: bool = False
