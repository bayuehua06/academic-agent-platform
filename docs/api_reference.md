# API Reference

Base URL（开发）：`http://localhost:1976`  
API 前缀：`/api`  
鉴权：除注册/登录外，需 `Authorization: Bearer <access_token>`  
交互文档：`http://localhost:1976/docs`

## Health

| Method | Path | Auth | 说明 |
|--------|------|------|------|
| GET | `/health` | 否 | 健康检查 |

## Auth — `/api/auth`

| Method | Path | Auth | 说明 |
|--------|------|------|------|
| POST | `/api/auth/register` | 否 | 注册。Body: `{ username, email, password }` → `UserOut` |
| POST | `/api/auth/login` | 否 | OAuth2 Password 表单（`username` 可为用户名或邮箱 / `password`）→ `{ access_token, token_type }` |
| GET | `/api/auth/me` | 是 | 当前用户 |

## Projects — `/api/projects`

| Method | Path | Auth | 说明 |
|--------|------|------|------|
| GET | `/api/projects` | 是 | 当前用户项目列表（含文献数、源文档数、大纲/评估就绪标记） |
| POST | `/api/projects` | 是 | 创建项目。Body: `{ title, zotero_collection_id? }` |
| GET | `/api/projects/{project_id}` | 是 | 项目详情（含 `assessment_summary` / `paper_outline` / `specific_requirements`） |
| PATCH | `/api/projects/{project_id}` | 是 | 更新标题 / status / zotero / 定稿字段（`assessment_summary` / `paper_outline` / `specific_requirements`） |
| DELETE | `/api/projects/{project_id}` | 是 | 删除项目（级联子表） |
| POST | `/api/projects/{project_id}/run-agent` | 是 | 运行 LangGraph。需 **A 定稿 + 已锁定 C**，否则 **400**。装配 A/C/D 定稿 + B summaries；Writer 按 `paper_outline` 逐节输出。Body: `{ max_papers?, skip_search? }` → `DraftVersion` |

## Sources — `/api/projects/{project_id}/sources`

多源输入 A/B/C/D。`role`: `ASSESSMENT` \| `BACKGROUND` \| `OUTLINE` \| `SPECIFIC`；`source_type`: `PASTE` \| `UPLOAD` \| `NOTEBOOKLM`。

| Method | Path | Auth | 说明 |
|--------|------|------|------|
| GET | `/api/projects/{id}/sources` | 是 | 列表；Query `role?` 过滤 |
| POST | `/api/projects/{id}/sources` | 是 | 粘贴创建。Body: `{ role, source_type?: "PASTE", title?, raw_text, notebook_url? }` |
| POST | `/api/projects/{id}/sources/upload` | 是 | multipart：`file` + `role` + `title?`（md/docx/pdf/txt） |
| POST | `/api/projects/{id}/sources/notebook-sync` | 是 | 抓取 NotebookLM → `BACKGROUND`+`NOTEBOOKLM`。Body: `{ notebook_url, use_browser? }`；失败 **502/503** |
| DELETE | `/api/projects/{id}/sources/{source_id}` | 是 | 删除；A/D 会刷新 projects 定稿列 |
| POST | `/api/projects/{id}/sources/{source_id}/reparse` | 是 | 重新解析 raw / 落盘文件，并重新摘要 |
| POST | `/api/projects/{id}/sources/{source_id}/summarize` | 是 | 重新摘要：有 `OPENAI_API_KEY` 调 `gpt-4o-mini`；**无 Key 时直存原文**为 `summary_text`（`status=SUMMARIZED`） |
| POST | `/api/projects/{id}/outline/lock` | 是 | 锁定大纲。Body: `{ source_id? }`（默认最新 OUTLINE）→ 写 `paper_outline` + `outline_locked_at` |

**定稿刷新**：A/D 增删改后自动更新 `assessment_summary` / `specific_requirements`（多条 A 有 Key 时可 LLM 合并，否则 `---` 拼接）；B 不改 projects；C 仅在 `outline/lock` 时写入。

> 旧 `/api/notebook/*` 已拆除（404）。

## Zotero / Literature — `/api/zotero`

| Method | Path | Auth | 说明 |
|--------|------|------|------|
| GET | `/api/zotero/status` | 是 | 是否已配置 Zotero API |
| GET | `/api/zotero/projects/{project_id}/literatures` | 是 | 文献列表 |
| PATCH | `/api/zotero/literatures/{literature_id}` | 是 | 更新 `selected_for_draft` / `relevance_score` |

## Drafts — `/api/drafts`

| Method | Path | Auth | 说明 |
|--------|------|------|------|
| POST | `/api/drafts/import-docx?project_id=` | 是 | multipart 上传 `.docx` → 新版本（`MANUAL_IMPORT`） |
| GET | `/api/drafts/{project_id}` | 是 | 版本列表（新→旧） |
| GET | `/api/drafts/{project_id}/latest` | 是 | 最新版本 |
| GET | `/api/drafts/{project_id}/export?format=docx\|pdf` | 是 | 导出文件流；可选 `version_id` |

## 状态码约定

- `401`：未认证或 token 无效
- `404`：资源不存在或不属于当前用户
- `400`：参数错误
- `501`：功能预留未启用
- `502` / `503`：上游服务失败（Phase 2+ Notebook 抓取等）
