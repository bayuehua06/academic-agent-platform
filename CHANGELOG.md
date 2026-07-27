# Changelog

本文件记录 Academic Agent Platform 的版本与功能变更摘要（功能 / API / 组件 / 数据库）。详细实现见 `docs/`。

## [1.3.1] - 2026-07-27

### 新增 / 变更

- **Writer 输入优先级（W1–W4）**：大纲结构/表格保真；A（评分）与 D 同为硬约束；字数超长压缩 + 更紧容差；D/A「必须套用文档」绑定注入
- **结构护栏**：Seed 含 Markdown 表时，成稿校验缺表/缺标题并专项 repair；精修提示同步强调保表
- **页数**：明确为弱信号，不做硬校验（长度请用词数写在 D）

### API

- `POST .../run-agent`：行为增强（无新路径）— 注入项目源文档目录供 must_apply 匹配；Writer 校验含结构 / 字数 / must_include；未匹配套用文档写入 verification 警告（不阻断）

### 组件 / 服务

- 新增 `structure_guard.py`
- `writing_constraints.py`：A/D 同级抽取、`must_apply_documents`、字数 `hi×1.1` 报警
- `writer.py`：表硬提示、节内压缩、结构 repair、MUST APPLY 块
- `draft_polish.py`：表保真提示

### 数据库

- 无 schema 变更（服务层能力）

### 文档

- 更新 README、`api_reference`、`database_schema`、`implementation_status`
- `docs/20260727-writer-input-priority-discussion.md` 标记已入 **1.3.1**

### 已知限制（本版本）

- 页数仍不硬校验；must_apply 匹配失败仅警告
- 表「同构」以列数近似为主，非出版级版式
- PDF 导出仍依赖系统 pandoc；内嵌图 OCR 未做

## [1.3.0] - 2026-07-27

### 新增 / 变更

- **节内多轮精修**：预览上可继续追问（`base_markdown` / 候选栈）；满意后再 Accept；不提前 +minor
- **跨节连续性**：Working Facts、上游节摘要注入；Accept 上游后下游标「建议再精修」
- **大纲 Seed 硬输入**：锁定大纲 `key_points` 对 Writer / 精修均为权威种子（禁止擅自换 case / 改名提案）
- **确认落库（P3）**：confirm 时按文内引用重建 References；`pending_directives` → `section_directives`；Facts → `projects.confirmed_facts`
- **整篇重生注入**：`run-agent` / Writer 按节读取 active directives + confirmed facts；新开工作区预填 Facts

### API

- `POST .../working/polish-section`：增 `base_markdown?`、`prior_instructions?`
- `PATCH .../working/facts`：更新 Working Facts
- `POST .../working/confirm`：响应增 `citation_warnings` / `directives_persisted` / `references_matched`
- `GET|PATCH|DELETE .../projects/{id}/section-directives`：章节指令列表 / 编辑 / 软删
- `GET .../projects/{id}`：增 `confirmed_facts`

### 组件 / 服务

- `draft_polish.py`（多轮 + Seed / Facts / 上游 / directives 注入）
- `references_rebuild.py`（确认时 References）
- `DraftPolishPanel`（候选栈、Facts、stale 标记）；`SectionDirectivesPanel`
- Writer：`OUTLINE SEED` + SECTION DIRECTIVES + CONFIRMED FACTS

### 数据库

- `projects.confirmed_facts`
- `draft_workings.working_facts` / `stale_headings`
- 新表 `section_directives`

### 文档

- 更新 README、`api_reference`、`database_schema`、`implementation_status`
- 设计文档 `20260726` / `20260727` 标记 P3 / M0–M4 已入本版本

### 已知限制（本版本）

- 未匹配引用仅警告不阻断；指令编辑 UX 仍简（P4）
- 文档内嵌图片 OCR / 真插图生成未做
- PDF 导出仍依赖系统 pandoc

## [1.2.2] - 2026-07-27

### 新增 / 变更

- **草稿精修工作区（P0–P2）**：基于已确认版本开启 working；分节 diff / 图·表锁定；`polish-section` / `accept-section`；确认工作区出 minor（如 9.1）
- **大纲 Word**：按文档顺序解析段落 + **表格文字** 进入章节 `key_points`；支持 Word 模板包（`template.main`→`document.main`）上传
- **按章文献向导**：「本章不需文献」可标记跳过；末章可结束；进度区分有文献 / 已跳过
- **零文献可写作**：`run-agent` 仅需 A 定稿 + 锁定 C；文献可选
- **引用完整性（硬约束）**：Writer / 扩写 / 补写 / 精修共用禁止库外引用规则；成稿后清洗非法文内引用；剥除模型自写 References
- **Researcher 空库修复**：`skip_search=True` 时即使 `sources=[]` 也不再注入 mock 假文献（修复 Smith/Wang 等幻觉来源）
- **APA 导出**：Markdown 管道表格转为 Word 真表格；草稿正文不再写入 Writer 模型调试行
- **Inputs**：大纲区接受 `.docx` / `.dotx`；删光 OUTLINE 时清空已锁 `paper_outline`

### API

- `POST .../run-agent`：无文献时 **不再 400**；有 Collection 仍同步 Zotero，无则空 sources 写作
- `POST .../drafts/{id}/working/*`：start / discard / confirm / polish-section / accept-section / section-diff（P0–P2）
- `DELETE .../sources/{id}`：删光 OUTLINE 时清空锁定大纲与相关进度状态

### 组件 / 服务

- `citation_guard.py`、`word_package.py`、`outline_parser`（含表）、`apa_docx`（含表）、`researcher`（skip 空库）
- `draft_sections.py` / `draft_polish.py` / `DraftPolishPanel`
- `LiteratureConfirmPanel`：本章不需文献 / 结束向导

### 文档

- 更新 README、`api_reference`、`implementation_status`
- 新增 `docs/20260727-draft-polish-multiturn-cross-section-discussion.md`（节内多轮精修 + 跨节依赖，规划中）

### 已知限制（本版本）

- 精修仍为单轮预览→采纳；节内多轮对话与跨节 Working Facts 见新设计文档（未实现）
- 文档内嵌图片 OCR / 真插图生成未做
- PDF 导出仍依赖系统 pandoc

## [1.2.1] - 2026-07-26

### 新增 / 变更

- **导出文件名**：Word/PDF 下载名为 `{项目名}_v{版本}`；CORS 暴露 `Content-Disposition`；前端以项目标题兜底
- **APA Word 版式**：默认 python-docx 导出（TNR 12、双倍行距、1″ 边距、标题层级、正文首行缩进、References 悬挂缩进）；备 `apa_reference.docx` 供 pandoc
- **References 截断修复**：有 `apa_references_block` 时去掉正文半截 References，再整段替换权威列表
- **Draft 工具栏**：下载 Word / PDF / 导入 Word 移至页顶同一行（图标按钮）

### API

- `GET .../drafts/{id}/export`：`Content-Disposition` 使用项目名+版本；可选 `version_id`；CORS `expose_headers` 含该头

### 组件 / 服务

- `apa_docx.py`、`pandoc_service.merge_content_with_apa_references`
- 项目页 Draft 顶栏操作区

### 文档

- 更新 README、`api_reference`、`database_schema`、`implementation_status`

### 已知限制（本版本）

- PDF 导出仍依赖系统 pandoc
- 用户上传版本后的润色流程尚未立项（校验 / 按节润色待讨论）

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
