# API Reference

**版本：1.3.0**（2026-07-27）

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
| GET | `/api/projects/{project_id}` | 是 | 项目详情（含定稿字段 + `confirmed_facts`） |
| PATCH | `/api/projects/{project_id}` | 是 | 更新标题 / zotero / 定稿字段等 |
| DELETE | `/api/projects/{project_id}` | 是 | 删除项目（级联本地 sources / literatures / drafts / directives；不删 Zotero 远端） |
| POST | `/api/projects/{project_id}/run-agent` | 是 | 运行 LangGraph。需 **A 定稿 + 已锁定 C**；**文献可选**。注入 active `section_directives` + `confirmed_facts`。有 Collection 时先 Zotero sync；空库也可写作。→ `DraftVersion`（major+1）。Body: `{ max_papers?, skip_search? }` |
| GET | `/api/projects/{project_id}/section-directives` | 是 | 已落库章节指令；Query `active_only?`（默认 true） |
| PATCH | `/api/projects/{project_id}/section-directives/{id}` | 是 | 编辑 `directive_text` / `instruction` / `active` |
| DELETE | `/api/projects/{project_id}/section-directives/{id}` | 是 | 软删（`active=false`） |

## Sources — `/api/projects/{project_id}/sources`

多源输入 A/B/C/D。`role`: `ASSESSMENT` \| `BACKGROUND` \| `OUTLINE` \| `SPECIFIC`；`source_type`: `PASTE` \| `UPLOAD` \| `NOTEBOOKLM`。

| Method | Path | Auth | 说明 |
|--------|------|------|------|
| GET | `/api/projects/{id}/sources` | 是 | 列表；Query `role?` 过滤 |
| POST | `/api/projects/{id}/sources` | 是 | 粘贴创建。Body: `{ role, source_type?: "PASTE", title?, raw_text, notebook_url? }` |
| POST | `/api/projects/{id}/sources/upload` | 是 | multipart：`file` + `role` + `title?`（md/docx/dotx/pdf/txt/pptx） |
| POST | `/api/projects/{id}/sources/notebook-sync` | 是 | 抓取 NotebookLM → `BACKGROUND`+`NOTEBOOKLM`。Body: `{ notebook_url, use_browser? }`；失败 **502/503** |
| DELETE | `/api/projects/{id}/sources/{source_id}` | 是 | 删除；A/D 刷新定稿；**删光 OUTLINE 时清空已锁大纲** |
| POST | `/api/projects/{id}/sources/{source_id}/reparse` | 是 | 重新解析 raw / 落盘文件，并重新摘要 |
| POST | `/api/projects/{id}/sources/{source_id}/summarize` | 是 | 重新摘要：有 Key 调默认模型；无 Key 直存原文 |
| POST | `/api/projects/{id}/outline/lock` | 是 | 锁定大纲。Body: `{ source_id? }`（默认最新 OUTLINE）→ 写 `paper_outline` + `outline_locked_at`（含表内要点；写作硬输入） |

**定稿刷新**：A/D 增删改后自动更新 `assessment_summary` / `specific_requirements`；B 不改 projects；C 仅在 `outline/lock` 时写入。

> 旧 `/api/notebook/*` 已拆除（404）。

## Zotero / Literature — `/api/zotero`

| Method | Path | Auth | 说明 |
|--------|------|------|------|
| GET | `/api/zotero/ping` | 是 | 真实连通检测 |
| GET | `/api/zotero/collections` | 是 | 列出库内集合（调试） |
| GET | `/api/zotero/status` | 是 | 是否已配置（不发请求） |
| POST | `/api/zotero/projects/{project_id}/ensure-structure` | 是 | 创建/对齐项目 Collection + 章节 Subcollections |
| POST | `/api/zotero/projects/{project_id}/sync` | 是 | 从 Zotero 拉取并镜像本地 |
| POST | `/api/zotero/projects/{project_id}/import` | 是 | Body: `{ outline_heading, items[], source_query? }` → 入库 |
| GET | `/api/zotero/projects/{project_id}/literatures` | 是 | 文献列表 |
| PATCH | `/api/zotero/literatures/{literature_id}` | 是 | 更新 `selected_for_draft` / `relevance_score` |

> 写作引用以项目已确认文献为准；空库允许写作但禁止库外文内引用。

## Literature Search — `/api`

| Method | Path | Auth | 说明 |
|--------|------|------|------|
| POST | `/api/projects/{id}/literature-search/suggest-query` | 是 | Z5 按章造词 |
| GET | `/api/literature-providers` | 是 | 检索库注册表；含 `openai_configured` |
| POST | `/api/projects/{id}/literature-search/ping` | 是 | 探测连通 |
| POST | `/api/projects/{id}/literature-search` | 是 | 按章检索；多库各取 `max_results` 后去重 |
| GET | `/api/projects/{id}/literature-search/{run_id}` | 是 | 取回候选（进程内存） |
| POST | `/api/projects/{id}/literature-search/{run_id}/confirm` | 是 | 确认入库 |

## Drafts — `/api/drafts`

| Method | Path | Auth | 说明 |
|--------|------|------|------|
| POST | `/api/drafts/import-docx?project_id=` | 是 | multipart `.docx` + `base_version_id` → **进入 working**（预填 `confirmed_facts`） |
| POST | `/api/drafts/{project_id}/working/start` | 是 | Query `base_version_id`：无上传开启精修工作区 |
| GET | `/api/drafts/{project_id}/working` | 是 | 当前 active working（含分节 meta、`working_facts`、`stale_headings`、`outline_seeds`） |
| DELETE | `/api/drafts/{project_id}/working` | 是 | 丢弃工作区 |
| PATCH | `/api/drafts/{project_id}/working/facts` | 是 | Body: `{ working_facts }` |
| POST | `/api/drafts/{project_id}/working/confirm` | 是 | 确认 → minor + References 重建 + directives/Facts 落库。响应可含 `citation_warnings` / `directives_persisted` / `references_matched` |
| GET | `/api/drafts/{project_id}/working/section-diff` | 是 | Query `heading`：行级 diff + `outline_key_points` |
| POST | `/api/drafts/{project_id}/working/polish-section` | 是 | Body: `{ heading, instruction, literature_ids?, section_markdown?, base_markdown?, prior_instructions? }` → 预览 |
| POST | `/api/drafts/{project_id}/working/accept-section` | 是 | Body: `{ heading, preview_markdown, instruction }` → overrides + 暂存 directive；标记下游 stale |
| GET | `/api/drafts/{project_id}` | 是 | 版本列表（含 `major` / `minor` / `display_label`） |
| GET | `/api/drafts/{project_id}/latest` | 是 | 最新版本 |
| GET | `/api/drafts/{project_id}/export?format=docx\|pdf` | 是 | 导出；Markdown 表→Word 表；`项目名_v版本` |

## 状态码约定

- `401`：未认证或 token 无效
- `404`：资源不存在或不属于当前用户
- `400`：参数错误
- `501`：功能预留未启用
- `502` / `503`：上游服务失败（Notebook 抓取等）
