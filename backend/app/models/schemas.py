"""Pydantic v2 Schema 定义。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
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
    literature_databases: Optional[List[str]] = None


class ProjectUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    zotero_collection_id: Optional[str] = None
    literature_databases: Optional[List[str]] = None
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
    confirmed_facts: Optional[str] = None
    zotero_collection_id: Optional[str] = None
    zotero_binding_mode: Optional[str] = None
    zotero_library_type: Optional[str] = None
    zotero_library_id: Optional[str] = None
    literature_databases: Optional[List[str]] = None
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
    zotero_subcollection_key: Optional[str] = None
    outline_heading: Optional[str] = None
    source_query: Optional[str] = None
    title: str
    authors: Optional[List[str]] = None
    year: Optional[str] = None
    doi: Optional[str] = None
    abstract: Optional[str] = None
    landing_url: Optional[str] = None
    evidence_tier: Optional[str] = None
    evidence_source: Optional[str] = None
    evidence_fetched_at: Optional[datetime] = None
    relevance_score: Optional[float] = None
    selected_for_draft: bool
    confirmed_at: Optional[datetime] = None
    created_at: datetime
    # 展示/Attach 分配（非 ORM 列，由 API 组装）
    assigned_headings: List[str] = []
    collection_path: Optional[str] = None


class LiteratureUpdate(BaseModel):
    selected_for_draft: Optional[bool] = None
    relevance_score: Optional[float] = None


class LiteratureImportItem(BaseModel):
    """确认入库的单篇文献元数据。"""

    title: str
    authors: Optional[List[str]] = None
    year: Optional[str] = None
    doi: Optional[str] = None
    url: Optional[str] = None
    abstract: Optional[str] = None
    relevance_score: Optional[float] = None


class LiteratureImportRequest(BaseModel):
    """将确认文献写入 Zotero（create=章节子集合；attach=指定 target）。"""

    outline_heading: str
    items: List[LiteratureImportItem]
    source_query: Optional[str] = None
    # attach 模式必填：绑定根或其直接子集合 key
    target_collection_key: Optional[str] = None


class ZoteroBindingRequest(BaseModel):
    """绑定项目文献范围：新建结构或挂接已有 Collection。"""

    mode: str = Field(..., pattern="^(create|attach)$")
    collection_key: Optional[str] = None
    library_type: Optional[str] = Field(None, pattern="^(user|group)$")
    library_id: Optional[str] = None


class LiteratureAssignmentPut(BaseModel):
    """整章覆盖该章的文献分配。"""

    literature_ids: List[UUID] = Field(default_factory=list)


class LiteratureAssignmentsOut(BaseModel):
    """按章聚合的分配视图。"""

    sections: List[dict]  # [{outline_heading, literature_ids: [...]}, ...]
    unassigned_count: int = 0
    total_count: int = 0


# ---------- Drafts ----------


class DraftVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    version_number: int
    major: Optional[int] = None
    minor: int = 0
    display_label: str = "1"
    parent_version_id: Optional[UUID] = None
    base_version_id: Optional[UUID] = None
    content_markdown: str
    apa_references_block: Optional[str] = None
    source_type: str
    changelog: Optional[str] = None
    created_at: datetime
    # 确认工作区时附带（非 ORM 字段）
    citation_warnings: Optional[List[str]] = None
    directives_persisted: Optional[int] = None
    references_matched: Optional[int] = None


class DraftWorkingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    base_version_id: UUID
    base_display_label: Optional[str] = None
    content_markdown: str
    section_overrides: Optional[dict] = None
    pending_directives: Optional[list] = None
    working_facts: Optional[str] = None
    stale_headings: Optional[List[str]] = None
    status: str
    source_filename: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    # P1：分节 diff
    sections: Optional[List[dict]] = None
    # 大纲 heading → key_points（硬输入种子，供 UI）
    outline_seeds: Optional[dict] = None


class PolishSectionRequest(BaseModel):
    heading: str = Field(..., min_length=1)
    instruction: str = Field(..., min_length=1)
    literature_ids: Optional[List[UUID]] = None
    # 可选：用编辑器里未保存的节正文作为精修输入（含标题行更佳）
    section_markdown: Optional[str] = None
    # 多轮：以上一预览候选为底
    base_markdown: Optional[str] = None
    # 近几轮指令（可选上下文）
    prior_instructions: Optional[List[str]] = None


class PolishSectionPreview(BaseModel):
    heading: str
    preview_markdown: str
    mode: str
    model: Optional[str] = None
    locked_count: int = 0
    openai_configured: bool = False
    error: Optional[str] = None
    line_diff: Optional[List[dict]] = None


class AcceptSectionRequest(BaseModel):
    heading: str = Field(..., min_length=1)
    preview_markdown: str = Field(..., min_length=1)
    instruction: str = Field(..., min_length=1)


class WorkingFactsUpdate(BaseModel):
    working_facts: str = ""


class SectionDirectiveOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    outline_heading: str
    directive_text: str
    instruction: Optional[str] = None
    source_working_id: Optional[UUID] = None
    confirmed_version_id: Optional[UUID] = None
    active: bool
    created_at: datetime
    updated_at: datetime


class SectionDirectiveUpdate(BaseModel):
    directive_text: Optional[str] = None
    instruction: Optional[str] = None
    active: Optional[bool] = None


class SectionDiffRequest(BaseModel):
    heading: str = Field(..., min_length=1)


class DraftExportRequest(BaseModel):
    version_id: Optional[UUID] = None
    format: str = Field("docx", pattern="^(docx|pdf)$")


class AgentRunRequest(BaseModel):
    """触发 LangGraph 学术写作工作流。"""

    max_papers: int = Field(5, ge=1, le=20)
    skip_search: bool = False
    # False：校验失败不自动 repair，由前端询问后再调 repair-agent-draft
    auto_repair: bool = False


class AgentRepairRequest(BaseModel):
    """对已生成草稿做一轮自动补写/压缩。"""

    version_id: UUID


class AgentProgressOut(BaseModel):
    """run-agent 进程内进度（前端轮询）。"""

    project_id: str
    stage: str
    label: str
    detail: str = ""
    percent: Optional[int] = None
    updated_at: Optional[str] = None
    running: bool = False


class AgentRunResultOut(DraftVersionOut):
    """run-agent / repair 结果：草稿 + 校验信息（兼容 DraftVersion 字段）。"""

    verify_ok: Optional[bool] = None
    verification_issues: List[str] = Field(default_factory=list)
    repair_available: bool = False
    writer_word_count: Optional[int] = None
    writer_word_target: Optional[Dict[str, Any]] = None
    repaired: bool = False
