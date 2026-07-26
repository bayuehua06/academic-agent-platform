# Changelog

本文件记录 Academic Agent Platform 的版本与功能变更摘要（功能 / API / 组件 / 数据库）。详细实现见 `docs/`。

## [0.1.0] - 2026-07-25

### 新增

- **项目脚手架**：FastAPI 后端 + Next.js 前端 + PostgreSQL（docker-compose）+ 根目录 `npm run dev` 一键启动（前端 `1980` / 后端 `1976`，端口占用时提示 kill）
- **鉴权**：用户注册 / 登录 / 当前用户（JWT + OAuth2 Password）
- **项目**：CRUD 与 LangGraph Agent 触发（`POST /api/projects/{id}/run-agent`）
- **NotebookLM**：手动粘贴 / Markdown 上传；Playwright 自动抓取接口预留（501）
- **文献 / Zotero**：项目文献列表、选中状态更新、Zotero 配置状态查询
- **草稿**：版本列表、最新版、DOCX/PDF 导出、Word 逆向导入新版本
- **Agent**：需求分析 → 文献检索（可回退模拟数据）→ APA 正文 → APA References
- **前端**：登录/注册、Dashboard 项目卡片、项目详情三 Tab（Inputs / Literature / Draft）
- **文档规范**：引入 `.cursorrules`；补充 `CHANGELOG.md` 与核心文档 `docs/api_reference.md`、`docs/database_schema.md`、`docs/implementation_status.md`

### 数据库

- 新建表：`users`、`projects`、`notebooklm_inputs`、`literatures`、`draft_versions`
