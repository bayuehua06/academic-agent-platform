# Implementation Status

最后更新：2026-07-26

## 总览

| 模块 | 状态 | 说明 |
|------|------|------|
| 项目脚手架 / docker-compose | ✅ 完成 | PostgreSQL 16；本机需安装 Docker |
| 根 `npm run dev` | ✅ 完成 | 前端 1980 / 后端 1976；占用则提示 kill |
| `./start.sh` / `./stop.sh` | ✅ 完成 | 参考 chronicleweb；含依赖安装与 DB 初始化（Docker 或本机 PG） |
| JWT 鉴权 | ✅ 完成 | 注册 / 登录 / me |
| Projects CRUD | ✅ 完成 | 定稿字段：`assessment_summary` / `paper_outline` / `specific_requirements`；含 Agent 触发 |
| Agent 输入重构 Phase 1 | ✅ 完成 | 删 `notebooklm_inputs`；增 `project_source_documents`；旧 `/api/notebook` 拆除；见 `docs/agent-input-redesign-discussion.md` |
| Sources API / 定稿刷新 | ✅ Phase 2 | ingest / outline 解析 / refresh；粘贴·上传·Notebook sync；`outline/lock`；run-agent 校验 A+C |
| Summarizer | ✅ Phase 3 | `gpt-4o-mini`；**无 `OPENAI_API_KEY` 时直存原文为摘要**以便跑通；`POST .../summarize` |
| 前端 Inputs（A/B/C/D） | ✅ Phase 4 | `ProjectInputs`：粘贴/上传/Notebook/锁定大纲/定稿只读；Agent 按钮校验 A+C |
| Agent 按大纲写作 | ✅ Phase 5 | state 用定稿字段；Writer 严格按 `paper_outline` 层级输出 |
| NotebookLM 抓取 | ✅ 挂到 Sources | `POST .../sources/notebook-sync` → BACKGROUND |
| 文献检索 | ⚠️ 部分 | 未配 Chrome/API 时使用模拟数据 |
| Zotero 同步 | ⚠️ 部分 | 需 `ZOTERO_LIBRARY_ID` + `ZOTERO_API_KEY`；未配置则跳过写入 |
| APA Writer / Formatter | ✅ 完成 | 规则型生成；LLM 增强可选（需 OpenAI Key） |
| Pandoc 导出 DOCX | ✅ 完成 | 无 pandoc 时回退 python-docx |
| Pandoc 导出 PDF | ⚠️ 依赖 | 需系统 pandoc（及引擎） |
| Word 导入 Markdown | ✅ 完成 | `POST /api/drafts/import-docx` |
| 前端 Dashboard / 项目详情 | ✅ 完成 | 三 Tab + A/B/C/D Inputs + 版本/导出/导入 |
| API 自动化测试 | ✅ 完成 | pytest + httpx + SQLite；sources / summarizer / agent outline（56 cases） |
| Alembic 迁移 | ⏳ 占位 | 现用 `create_all`；`alembic.ini` 已放 |

## 前端组件

| 组件 | 状态 |
|------|------|
| DraftViewer | ✅ |
| VersionHistory | ✅ |
| ZoteroList | ✅ |
| 登录 / 注册页 | ✅ |
| Dashboard | ✅ |
| Project Detail Tabs | ✅ |

## LangGraph 节点

| 节点 | 文件 | 状态 |
|------|------|------|
| Requirement Analyzer | `agents/nodes/requirement_analyzer.py` | ✅ |
| Literature Searcher | `agents/nodes/researcher.py` | ⚠️ 模拟/预留 browser-use |
| APA Writer | `agents/nodes/writer.py` | ✅ |
| APA Formatter | `agents/nodes/apa_formatter.py` | ✅ |
| Graph 组装 | `agents/graph.py` | ✅ |

## 已知限制

1. 数据库角色/库需 `docker compose up -d` 初始化；无 Docker 时后端启动会失败。
2. 完整 Scholar/IEEE 检索与 NotebookLM DOM 抓取尚未接入真实 browser-use。
3. CSL 为 stub（`backend/resources/apa.csl`），生产可替换官方 APA 7th CSL。

## 下一步建议

1. 补全 `.cursorrules` 中「API 与自动化测试（强制）」章节条文（测试套件已落地，规则正文仍可补齐）。
2. 接入真实文献检索与 Zotero 联调。
3. 用 Alembic 管理 schema 变更。
