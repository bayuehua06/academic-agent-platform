# Database Schema

数据库：PostgreSQL 16（`docker-compose.yml` 服务名 `db`）。  
ORM：SQLAlchemy Async（`backend/app/db/models.py`）。开发环境可用 `create_all`；结构变更以本文为准。

扩展：`pgcrypto`（`gen_random_uuid`，见 `backend/app/db/init.sql`）。

> **2026-07-26 重构**：删除 `notebooklm_inputs`；新增 `project_source_documents`；`projects` 增加定稿缓存字段。详见 `docs/agent-input-redesign-discussion.md`。

## ER 概览

```
users 1──* projects 1──* project_source_documents
                 │
                 ├──* literatures
                 └──* draft_versions
```

## 表结构

### users

| 列 | 类型 | 约束 | 说明 |
|----|------|------|------|
| id | UUID | PK | 用户 ID |
| username | VARCHAR(50) | UNIQUE NOT NULL | 用户名 |
| email | VARCHAR(255) | UNIQUE NOT NULL | 邮箱 |
| password_hash | VARCHAR(255) | NOT NULL | Bcrypt 哈希 |
| created_at | TIMESTAMPTZ | default now() | |

### projects

| 列 | 类型 | 约束 | 说明 |
|----|------|------|------|
| id | UUID | PK | |
| user_id | UUID | FK → users ON DELETE CASCADE | |
| title | VARCHAR(255) | NOT NULL | |
| assessment_summary | TEXT | | **定稿**：全部 A 材料合并摘要；A 变更后重生成 |
| paper_outline | JSONB | | **定稿**：锁定后的章节骨架 `[{level, heading, key_points}]`；C 变更/锁定后重生成 |
| outline_locked_at | TIMESTAMPTZ | | 大纲锁定时间 |
| specific_requirements | TEXT | | **定稿**：D；D 变更后更新 |
| zotero_collection_id | VARCHAR(100) | | |
| status | VARCHAR(50) | default `INITIALIZING` | |
| created_at | TIMESTAMPTZ | default now() | |
| updated_at | TIMESTAMPTZ | default now(), on update | |

**已删除**：`assessment_requirements`（原文改由 source documents 承载）。

**status**：`INITIALIZING` | `FETCHING_PAPERS` | `DRAFTING` | `COMPLETED`

**Agent 取数**：A/C/D 读本表定稿列；B 查 `project_source_documents` 中 `role=BACKGROUND`。

### project_source_documents

| 列 | 类型 | 约束 | 说明 |
|----|------|------|------|
| id | UUID | PK | |
| project_id | UUID | FK → projects ON DELETE CASCADE | |
| role | VARCHAR(20) | NOT NULL | `ASSESSMENT` \| `BACKGROUND` \| `OUTLINE` \| `SPECIFIC` |
| source_type | VARCHAR(20) | NOT NULL | `PASTE` \| `UPLOAD` \| `NOTEBOOKLM` |
| title | VARCHAR(255) | | 展示名 |
| notebook_url | VARCHAR(500) | | 仅 NOTEBOOKLM |
| original_filename | VARCHAR(255) | | 仅 UPLOAD |
| content_type | VARCHAR(100) | | MIME |
| storage_path | VARCHAR(500) | | 原文件落盘路径 |
| raw_text | TEXT | | 解析/抓取全文 |
| summary_text | TEXT | | Summarizer 自由文本摘要 |
| summary_json | JSONB | | 可选松散结构；OUTLINE 解析树可暂存于此 |
| status | VARCHAR(30) | NOT NULL default `PENDING` | `PENDING` \| `PARSED` \| `SUMMARIZED` \| `FAILED` |
| error_message | TEXT | | |
| created_at | TIMESTAMPTZ | default now() | |
| updated_at | TIMESTAMPTZ | default now() | |
| summarized_at | TIMESTAMPTZ | | |

索引：`(project_id, role)`。

**已删除表**：`notebooklm_inputs`（Notebook → `role=BACKGROUND` + `source_type=NOTEBOOKLM`）。

### literatures

| 列 | 类型 | 约束 | 说明 |
|----|------|------|------|
| id | UUID | PK | |
| project_id | UUID | FK → projects ON DELETE CASCADE | |
| zotero_item_key | VARCHAR(100) | | |
| title | TEXT | NOT NULL | |
| authors | JSONB | | |
| year | VARCHAR(10) | | |
| doi | VARCHAR(255) | | |
| abstract | TEXT | | |
| relevance_score | FLOAT | | |
| selected_for_draft | BOOLEAN | default TRUE | |
| created_at | TIMESTAMPTZ | default now() | |

### draft_versions

| 列 | 类型 | 约束 | 说明 |
|----|------|------|------|
| id | UUID | PK | |
| project_id | UUID | FK → projects ON DELETE CASCADE | |
| version_number | INT | NOT NULL | |
| content_markdown | TEXT | NOT NULL | |
| apa_references_block | TEXT | | |
| source_type | VARCHAR(20) | default `AGENT_GEN` | `AGENT_GEN` \| `MANUAL_IMPORT` |
| changelog | TEXT | | |
| created_at | TIMESTAMPTZ | default now() | |

## 定稿刷新规则（应用层）

| 触发 | 更新 |
|------|------|
| A 增删改 / 重摘要 | → `projects.assessment_summary` |
| C 上传或锁定 | → `projects.paper_outline` + `outline_locked_at` |
| D 增删改 | → `projects.specific_requirements` |
| 仅 B 变更 | 只更新 documents 行；**不**改 projects 三列 |

## 连接配置

```
DATABASE_URL=postgresql+asyncpg://academic:academic_secret@localhost:5432/academic_agent
```

Summarizer：`OPENAI_API_KEY` + `OPENAI_MODEL=gpt-4o-mini`。
