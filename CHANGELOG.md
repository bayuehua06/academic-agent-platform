# Changelog

本文件记录 Academic Agent Platform 的版本与功能变更摘要（功能 / API / 组件 / 数据库）。详细实现见 `docs/`。

## [1.2.0] - 2026-07-26

### 新增 / 变更

- **Z5 按章检索词**：有 OpenAI Key 时按章节 heading / 要点 + A/D 定稿生成检索词；无 Key 或失败时规则回退
- **Writer LLM 长文**：`run-agent` 有 Key 时按锁定大纲分节撰写；从 D+A 抽取通用 HARD CONSTRAINTS（字数/引用/必含/禁止/语言等），原文 D 始终附带；分节扩写 + 成稿校验补写；无 Key / 失败回退模板
- **Writer 独立模型**：`OPENAI_WRITER_MODEL`（默认 `gpt-4o`）；Summarizer / Z5 仍用 `OPENAI_MODEL`（默认 `gpt-4o-mini`）
- **默认学术英文**：摘要跟原文语言、不默认译中；写作默认 English，仅约束明确要求中文时才用中文
- **项目 UX**：仪表盘改名 / 删除；进度状态按就绪度推导（`INITIALIZING` → … → `HAS_DRAFT`，不再误用「已完成」）；Inputs 列表短预览 +「查看全部」

### API

- `POST /api/projects/{id}/literature-search/suggest-query`：Body `{ outline_heading }` → `{ query, mode, openai_configured }`
- `PATCH` / `DELETE /api/projects/{id}`：改名与删除（前端补齐）
- `GET` 项目列表/详情：`status` 为推导展示值；旧 `COMPLETED` 视为 `HAS_DRAFT`
- `run-agent`：草稿 changelog 可含 model / words / target / verify_ok

### 组件 / 服务

- `literature_query.py`（Z5）、`writing_constraints.py`、`writer.py`（分节 / 扩写 / 校验）
- `llm_client.resolve_model(purpose=writer|default)`
- `LiteratureConfirmPanel`：生成本章检索词 / 可选进章自动生成
- Dashboard：改名、删除；进度标签文案

### 配置

- `OPENAI_WRITER_MODEL`（见 `backend/.env.example`）

### 文档

- 更新 README、`api_reference`、`database_schema`、`implementation_status`、`openai-llm-usage`

### 已知限制（本版本）

- Writer / Z5 依赖 OpenAI 额度与网络；失败自动回退
- 检索 run 仍存进程内存；重启后端后候选会话丢失（已确认文献在 Zotero/DB）
- 长稿质量仍受模型与约束抽取影响，需人工审阅

## [1.1.2] - 2026-07-26

### 新增 / 变更

- **ACM Digital Library 检索**：经 AUT Library 入口（Playwright），与 IEEE 共用 AUT 登录
- **多库检索**：项目勾选 `ieee` / `acm`；每个库各取 `max_results`，再按 DOI → 标题去重；响应含 `deduped_count`
- **前端**：文献向导可勾选检索库并写入项目 `literature_databases`

### API

- `GET /api/literature-providers`：ACM `implemented=true`
- `POST .../literature-search/ping`：按项目启用库分别探测 IEEE / ACM
- `POST .../literature-search`：按 `databases`（或项目配置）跑多库；合并去重

### 组件 / 服务

- `acm_aut_search.py`、`aut_library_auth.py`（共用登录）
- `LiteratureConfirmPanel` 检索库多选

### 文档

- 更新 README、`api_reference`、`database_schema`、`implementation_status`、`openai-llm-usage`

### 已知限制（本版本）

- **Z5 未做**：尚无按章 LLM 自动造检索词（**1.2.0 已实现**）
- Writer 正文仍为规则模板；检索 run 存进程内存（**Writer LLM 见 1.2.0**）

## [1.1.1] - 2026-07-26

### 新增 / 变更

- **文献按章向导**：锁定大纲后按章节检索 IEEE（经 AUT Library）、多选确认、写入 Zotero 章节子集合并镜像本地
- **Zotero 真源**：`ensure-structure` / `import` / `sync`；`run-agent` 写作前从项目 Collection（含子集合）拉取；支持桌面端离线增补
- **检索候选「已存在」标注**：相对项目 Collection 任意子集合（优先 DOI，其次标题）；默认不勾选已存在项
- **检索库配置**：全局 `.env` 注册表（IEEE/ACM 入口）+ 项目 `literature_databases` 勾选（ACM 仅注册）
- **前端**：`LiteratureConfirmPanel`（进度条、章节要点、完整 abstract、从 Zotero 同步）

### API

- `GET /api/zotero/ping`、`/collections`；`POST .../ensure-structure`、`.../import`、`.../sync`
- `GET /api/literature-providers`
- `POST /api/projects/{id}/literature-search/ping`、`literature-search`、`.../{run_id}/confirm`
- `GET .../literature-search/{run_id}`
- `run-agent`：无 Zotero 文献则 **400**；不再用 mock 检索覆盖本地库

### 数据库

- `projects.literature_databases`（JSONB）
- `literatures`：`zotero_subcollection_key`、`outline_heading`、`source_query`、`confirmed_at`

### 文档

- 设计归档：`docs/20260726-literature-zotero-search-discussion.md`
- 更新 README、`api_reference`、`database_schema`、`implementation_status`

### 已知限制（本版本）

- **Z5 未做**：尚无按章 LLM 自动造检索词（可手填或用 `LITERATURE_TEST_QUERY`）
- ACM Digital Library 仅注册入口，检索未实现（**1.1.2 已实现**）
- Writer 正文仍为规则模板（非长文 LLM）；检索 run 存进程内存

## [1.1.0] - 2026-07-26

### 新增 / 变更

- **多源输入（A/B/C/D）**：Assessment、背景材料、论文大纲、具体要求；支持粘贴与上传（md/docx/pdf/txt）
- **Sources API**：`/api/projects/{id}/sources`（CRUD / upload / reparse / summarize / notebook-sync）与 `outline/lock`
- **定稿缓存**：`projects.assessment_summary` / `paper_outline` / `outline_locked_at` / `specific_requirements`；A/D 变更自动 refresh，B 不改定稿列
- **Summarizer**：`gpt-4o-mini`；无 `OPENAI_API_KEY` 时直存原文为摘要以便联调
- **前端 Inputs**：四区 UI + 定稿只读预览；运行 Agent 前校验 A 就绪 + C 已锁定
- **Agent**：按锁定 `paper_outline` 层级生成草稿；装配 A/C/D 定稿与 B 背景摘要
- **NotebookLM**：挂到 BACKGROUND source（`notebook-sync`）；旧 `/api/notebook/*` 拆除
- **健壮性**：Word 表格文本提取；PDF 清洗 NUL 字节；超长文本截断入库

### 数据库

- **删除**：`notebooklm_inputs`；`projects.assessment_requirements`
- **新增**：`project_source_documents`
- **projects 新增列**：`assessment_summary`、`paper_outline`、`outline_locked_at`、`specific_requirements`

### 文档

- 更新 README、`api_reference`、`database_schema`、`implementation_status`
- 设计讨论归档：`docs/20260726-agent-input-redesign-discussion.md`

### 已知限制（本版本）

- 文献检索仍为模拟数据；Writer 正文为规则模板（有 Key 时 Summarizer 可用 LLM，写作 LLM 增强待后续）

## [1.0.0] - 2026-07-25

### 新增

- **项目脚手架**：FastAPI 后端 + Next.js 前端 + PostgreSQL（docker-compose）+ 根目录 `npm run dev` 一键启动（前端 `1980` / 后端 `1976`，端口占用时提示 kill）
- **鉴权**：用户注册 / 登录 / 当前用户（JWT + OAuth2 Password）
- **项目**：CRUD 与 LangGraph Agent 触发（`POST /api/projects/{id}/run-agent`）
- **NotebookLM**：手动粘贴 / Markdown 上传；Playwright 自动抓取接口预留（501）
- **文献 / Zotero**：列表与选中状态；Zotero status；Agent 侧 DOI 同步预留
- **草稿**：版本列表、最新稿、DOCX/PDF 导出、Word 导入为 Markdown 版本
- **Agent 管线**：需求分析 → 文献检索（模拟）→ APA 写作 → APA 参考文献块
- **文档与测试**：`docs/` 核心文档；后端 pytest API 套件

### 说明

- 初版 CHANGELOG 条目曾记为 `0.1.1`（输入重构），现归并为 **1.1.0** 叙述；以本文件与 README 版本号为准。
