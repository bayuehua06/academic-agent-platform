"""SQLAlchemy ORM 模型。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class User(Base):
    """用户表。"""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    projects: Mapped[List["Project"]] = relationship(
        "Project", back_populates="user", cascade="all, delete-orphan"
    )


class Project(Base):
    """学术项目表。"""

    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    # 定稿缓存（A/C/D）；B 在 project_source_documents，Agent 自查
    assessment_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    paper_outline: Mapped[Optional[list | dict]] = mapped_column(JSONB, nullable=True)
    outline_locked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    specific_requirements: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # 确认精修工作区后持久化的跨节 Facts（供下次精修 / run-agent）
    confirmed_facts: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    zotero_collection_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    # create | attach；与 zotero_library_* 共同决定文献范围
    zotero_binding_mode: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    zotero_library_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    zotero_library_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    # 本项目启用的检索库 id 列表，如 ["ieee","acm"]；空则用全局默认
    literature_databases: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="INITIALIZING")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship("User", back_populates="projects")
    source_documents: Mapped[List["ProjectSourceDocument"]] = relationship(
        "ProjectSourceDocument", back_populates="project", cascade="all, delete-orphan"
    )
    literatures: Mapped[List["Literature"]] = relationship(
        "Literature", back_populates="project", cascade="all, delete-orphan"
    )
    draft_versions: Mapped[List["DraftVersion"]] = relationship(
        "DraftVersion", back_populates="project", cascade="all, delete-orphan"
    )
    draft_workings: Mapped[List["DraftWorking"]] = relationship(
        "DraftWorking", back_populates="project", cascade="all, delete-orphan"
    )
    section_directives: Mapped[List["SectionDirective"]] = relationship(
        "SectionDirective", back_populates="project", cascade="all, delete-orphan"
    )
    literature_section_assignments: Mapped[List["LiteratureSectionAssignment"]] = relationship(
        "LiteratureSectionAssignment",
        back_populates="project",
        cascade="all, delete-orphan",
    )


class ProjectSourceDocument(Base):
    """项目源文档（A/B/C/D：粘贴、上传、NotebookLM）。"""

    __tablename__ = "project_source_documents"
    __table_args__ = (Index("ix_psd_project_role", "project_id", "role"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    notebook_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    original_filename: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    content_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    storage_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    raw_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    summary_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    summary_json: Mapped[Optional[dict | list]] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING")
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    summarized_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    project: Mapped["Project"] = relationship("Project", back_populates="source_documents")


class Literature(Base):
    """文献表（Zotero 同步）。"""

    __tablename__ = "literatures"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    zotero_item_key: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    zotero_subcollection_key: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    outline_heading: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    source_query: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    authors: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    year: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    doi: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    abstract: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    landing_url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    # 缓存 PDF/URL 抽取全文；按章 excerpt 仍现算，不落库
    evidence_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    evidence_tier: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    evidence_source: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    evidence_content_key: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    evidence_fetched_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    relevance_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    selected_for_draft: Mapped[bool] = mapped_column(Boolean, default=True)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    project: Mapped["Project"] = relationship("Project", back_populates="literatures")
    section_assignments: Mapped[List["LiteratureSectionAssignment"]] = relationship(
        "LiteratureSectionAssignment",
        back_populates="literature",
        cascade="all, delete-orphan",
    )


class LiteratureSectionAssignment(Base):
    """章节↔文献多对多分配（一篇可属多章；Attach 下为 Writer 真源）。"""

    __tablename__ = "literature_section_assignments"
    __table_args__ = (
        Index(
            "ix_lit_section_assign_project_heading",
            "project_id",
            "outline_heading",
        ),
        Index("ix_lit_section_assign_project_lit", "project_id", "literature_id"),
        Index(
            "uq_lit_section_assign_project_lit_heading",
            "project_id",
            "literature_id",
            "outline_heading",
            unique=True,
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    literature_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("literatures.id", ondelete="CASCADE"), nullable=False
    )
    outline_heading: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    literature: Mapped["Literature"] = relationship(
        "Literature", back_populates="section_assignments"
    )
    project: Mapped["Project"] = relationship(
        "Project", back_populates="literature_section_assignments"
    )


class DraftVersion(Base):
    """论文草稿版本表。"""

    __tablename__ = "draft_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    # 全局递增排序键（1,2,3…）
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    # 展示用 major.minor（9 / 9.1）；旧行可空，读取时回退 version_number
    major: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    parent_version_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("draft_versions.id", ondelete="SET NULL"), nullable=True
    )
    base_version_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("draft_versions.id", ondelete="SET NULL"), nullable=True
    )
    content_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    apa_references_block: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # AGENT_GEN | MANUAL_IMPORT | POLISH_CONFIRM
    source_type: Mapped[str] = mapped_column(String(20), default="AGENT_GEN")
    changelog: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    project: Mapped["Project"] = relationship("Project", back_populates="draft_versions")


class DraftWorking(Base):
    """精修工作区（每项目至多一个 ACTIVE）。确认后生成 minor 版本。"""

    __tablename__ = "draft_workings"
    __table_args__ = (Index("ix_draft_workings_project_status", "project_id", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    base_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("draft_versions.id", ondelete="CASCADE"), nullable=False
    )
    content_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    # { heading: section_markdown } — P2 节精修写入；P0 可为空
    section_overrides: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    # 暂存章节指令，确认时再持久化（P2/P3）
    pending_directives: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    # 工作区已定事实（case / 主张等），精修跨节注入
    working_facts: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # 上游变更后建议再精修的下游 heading 列表
    stale_headings: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    source_filename: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    project: Mapped["Project"] = relationship("Project", back_populates="draft_workings")


class SectionDirective(Base):
    """章节精修指令（确认工作区时由 pending 落库；run-agent 按节注入）。"""

    __tablename__ = "section_directives"
    __table_args__ = (
        Index("ix_section_directives_project_heading", "project_id", "outline_heading"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    outline_heading: Mapped[str] = mapped_column(String(500), nullable=False)
    directive_text: Mapped[str] = mapped_column(Text, nullable=False)
    # 原始用户短指令（可选，便于展示）
    instruction: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_working_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("draft_workings.id", ondelete="SET NULL"), nullable=True
    )
    confirmed_version_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("draft_versions.id", ondelete="SET NULL"), nullable=True
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    project: Mapped["Project"] = relationship("Project", back_populates="section_directives")
