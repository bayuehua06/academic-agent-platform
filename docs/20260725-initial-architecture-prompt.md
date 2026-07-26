# Role & Goal
你是一位精通 Python、LangGraph、FastAPI、Next.js 与 PostgreSQL 的资深全栈系统架构师与 AI 工程师。
你的任务是从零构建一个名为 **"Academic-Agent-Platform"** 的学术辅助平台。该系统能够读取 Google NotebookLM 的输入，自动在学术数据库（如 IEEE Xplore、Google Scholar）检索文献并同步至本地 Zotero，使用 LangGraph 生成符合 APA 7th 规范的论文草稿，提供版本控制、Word/PDF 导档与逆向 Word 导入 Markdown 功能，并附带可视化管理后台与用户鉴权。

---

## 🛠️ System Architecture & Tech Stack

- **Frontend (Management Dashboard):** Next.js (App Router), Tailwind CSS, Shadcn UI
- **Backend API:** FastAPI, SQLAlchemy (Async), Pydantic v2
- **Agent Framework:** LangGraph, LangChain, `browser-use` (Playwright-based), `pyzotero`
- **Database:** PostgreSQL (using Pgvector readiness if needed)
- **Document Conversion Engine:** Pandoc, `python-docx`, `pypandoc`
- **Authentication:** JWT / OAuth2 with password hashing (Passlib/Bcrypt)

---

## 📁 Project Directory Structure

请严格按照以下目录结构组织代码：

academic-agent-platform/
├── backend/
│   ├── app/
│   │   ├── api/                  # FastAPI 路由 (auth, projects, drafts, zotero, notebook)
│   │   ├── core/                 # 配置, 数据库连接, 安全鉴权 (JWT)
│   │   ├── db/                   # SQLAlchemy 模型与 Migration 脚本
│   │   ├── models/               # Pydantic Schema 定义
│   │   ├── services/             # 业务逻辑 (Zotero, NotebookLM Parser, Pandoc Processor)
│   │   └── agents/               # LangGraph Agent 架构
│   │       ├── state.py          # LangGraph State 定义
│   │       ├── nodes/            # Agent 节点 (researcher, writer, apa_formatter)
│   │       └── graph.py          # LangGraph 工作流组装
│   ├── main.py                   # FastAPI 应用入口
│   └── requirements.txt
├── frontend/                     # Next.js 控制面板
│   ├── src/
│   │   ├── app/                  # (auth), dashboard, projects/[id]
│   │   ├── components/           # UI 组件 (DraftViewer, VersionHistory, ZoteroList)
│   │   └── lib/                  # API fetcher & utils
├── docker-compose.yml            # PostgreSQL 服务配置
└── README.md

---

## 🗄️ PostgreSQL Database Schema (DDL)

请在 `backend/app/db/` 中使用 SQLAlchemy (Async) 实现以下数据表结构：

```sql
-- 1. Users Table
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 2. Projects Table
CREATE TABLE projects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    assessment_requirements TEXT,
    zotero_collection_id VARCHAR(100),
    status VARCHAR(50) DEFAULT 'INITIALIZING', -- INITIALIZING, FETCHING_PAPERS, DRAFTING, COMPLETED
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 3. NotebookLM Inputs Table
CREATE TABLE notebooklm_inputs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    notebook_url VARCHAR(500),
    raw_transcript TEXT,
    extracted_summary TEXT,
    synced_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 4. Literatures Table (Zotero Integration)
CREATE TABLE literatures (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    zotero_item_key VARCHAR(100),
    title TEXT NOT NULL,
    authors JSONB, -- e.g., ["Author A", "Author B"]
    year VARCHAR(10),
    doi VARCHAR(255),
    abstract TEXT,
    relevance_score FLOAT,
    selected_for_draft BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 5. Draft Versions Table
CREATE TABLE draft_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    version_number INT NOT NULL,
    content_markdown TEXT NOT NULL,
    apa_references_block TEXT,
    source_type VARCHAR(20) DEFAULT 'AGENT_GEN', -- 'AGENT_GEN' or 'MANUAL_IMPORT'
    changelog TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

Core Modules & Design Guidelines
1. LangGraph Academic Workflow (backend/app/agents/)
构建带有中断与状态恢复能力的 LangGraph 状态图：

State (state.py): 存储 project_id, assessment_requirements, notebook_context, sources (文献数据), draft_markdown, apa_references。

Node 1: Requirement Analyzer: 结合 assessment_requirements 和 notebooklm_inputs 中的 Transcript，输出核心检索关键词与论文写作大纲。

Node 2: Literature Searcher (researcher.py):

集成 browser-use 库，支持通过已登录的 Chrome Profile (配置路径可选) 或 API 搜索 IEEE Xplore / Google Scholar。

提取论文的 Title, Abstract, Authors, Year, DOI。

Zotero Integration: 使用 pyzotero API，根据提取到的 DOI 自动添加文献条目并归档至特定的 Zotero Collection，将返回的 item_key 存入数据库。

Node 3: APA Writer (writer.py):

严格按照 APA 7th 规范在正文中插入 In-text Citations：单作者 (Smith, 2024)，双作者 (Zhang & Li, 2024)，三作者及以上 (Wang et al., 2023)。

Node 4: APA Formatter (apa_formatter.py):

根据文献元数据自动生成符合 APA 7th 排版规则（作者姓氏首字母排序、挂起缩进、 italics 格式等）的 Markdown 格式 References 列表。

2. Document Import & Export Engine (backend/app/services/pandoc.py)
Export (Markdown -> Word / PDF):

使用 pypandoc 读取 content_markdown 与 apa_references_block，转换导出为 .docx 或 .pdf。支持注入 APA 7th CSL (apa.csl) 样式文件。

Import (Word -> Markdown):

提供 /api/drafts/import-docx 接口。使用 python-docx / pypandoc 解析用户上传修改后的 .docx 文件，转为 Markdown。

自动递增生成新的 draft_versions 记录，source_type 标记为 'MANUAL_IMPORT'，version_number +1。

3. NotebookLM Sync Service (backend/app/services/notebooklm.py)
MVP 模式: 提供手动粘贴或 Markdown 文件上传接口，提取对话要点与最新约束条件。

扩展模式 (Playwright): 预留 browser-use / Playwright 自动抓取任务接口，传入 notebook_url 后复用 Cookie 提取最新 DOM 对话记录并更新至 notebooklm_inputs 表。

4. Management Dashboard (Frontend)
开发单页与项目详情看板：

Dashboard Overview: 包含用户登录/注册，展示所有 Project 卡片（状态标签、最新同步时间、文献数量、最新版本号）。

Project Detail Page:

Tab 1: Inputs & Assessment: 显示 NotebookLM 抓取要点与 Assessment 要求（支持在线修改与重同步）。

Tab 2: Literature Library: 显示自动同步到 Zotero 的文献列表、DOI 链接、摘要与相关度评分。

Tab 3: Draft & Versions: 渲染当前 Markdown 论文草稿，支持版本历史对比、下载 .docx/.pdf，以及上传修改后的 Word 文件反向更新版本。

🚀 Execution Steps for Cursor
首先生成 docker-compose.yml 启动 PostgreSQL 数据库，并搭建 backend/ 目录下的 FastAPI 脚手架与 SQLAlchemy 模型。

实现 backend/app/core/security.py 完成基础的用户登录注册 JWT 鉴权功能。

编写 backend/app/services/ 中的 zotero_service.py 和 pandoc_service.py 基础工具模块。

在 backend/app/agents/ 中搭建 LangGraph 图结构，实现从文献检索、Zotero DOI 写入到 APA 7th 论文撰写的核心节点。

完成 FastAPI 路由，连接 Backend 与数据库。

构建 Next.js 前端，连接 API 实现完整的论文管理与版本控制闭环。

请根据上述架构，一步步开始生成完整、无死锁且规范的代码！

项目请创建在github目录下，项目名为academic-agent-platform。等基本框架完成后，我们要checkin到github，就像当先github目录下其他项目一样