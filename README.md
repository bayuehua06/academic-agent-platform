# Academic Agent Platform

**版本：1.3.0**

学术辅助平台：多源输入（Assessment / 背景 / 大纲 / 具体要求）→ Summarizer 定稿 → **按章 IEEE/ACM 检索（可 LLM 造词）并确认入 Zotero** → LangGraph 按锁定大纲生成 APA 7th 草稿（有 Key 时 LLM 分节写作；**文献可选**）；**精修工作区**支持节内多轮、跨节 Facts、确认时落库指令与重建 References；支持版本控制与 Word/PDF 导出导入。

## 技术栈

| 层级 | 技术 |
|------|------|
| Frontend | Next.js (App Router), Tailwind CSS |
| Backend | FastAPI, SQLAlchemy (Async), Pydantic v2 |
| Agent | LangGraph, LangChain, pyzotero |
| 文献检索 | Playwright（AUT Library → IEEE / ACM） |
| Database | PostgreSQL |
| Documents | Pandoc, python-docx, pypandoc, pypdf, python-pptx |
| Auth | JWT / OAuth2 Password (Passlib/Bcrypt) |

## 快速开始

固定端口：**前端 `1980`** / **后端 `1976`**。

### 一键启动（推荐）

```bash
./start.sh
```

停止：`./stop.sh`

- 控制面板：http://localhost:1980
- API 文档：http://localhost:1976/docs

### 环境变量（摘要）

编辑 `backend/.env`（勿提交真实密钥）：

```env
# LLM
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4o-mini
OPENAI_WRITER_MODEL=gpt-4o

# Zotero（写作真源；可为空库写作）
ZOTERO_LIBRARY_ID=
ZOTERO_API_KEY=
ZOTERO_LIBRARY_TYPE=user

# AUT → IEEE / ACM
AUT_USERNAME=
AUT_PASSWORD=
LITERATURE_DB_IEEE_URL=https://library.aut.ac.nz/databases/ieee-xplore
LITERATURE_DB_ACM_URL=https://library.aut.ac.nz/databases/acm-digital-library
LITERATURE_DEFAULT_DATABASES=ieee
LITERATURE_TEST_QUERY=food delivery transformation
CHROME_CDP_URL=http://127.0.0.1:9222
```

- **Summarizer / Z5 / 精修**：`OPENAI_MODEL`（默认 `gpt-4o-mini`）
- **Writer**：`OPENAI_WRITER_MODEL`（默认 `gpt-4o`）；空则回退 `OPENAI_MODEL`
- 无 Key：摘要直存原文；检索词规则回退；写作用模板

**OpenAI 用在哪些地方（主动/被动）**：见 [docs/openai-llm-usage.md](./docs/openai-llm-usage.md)。

### 典型使用路径

1. 创建项目 → Inputs 四区  
2. **A** Assessment → 定稿；**C** 大纲 → **锁定**（Word 含表内文字会进要点；`key_points` 为写作硬输入）  
3. 可选：**B** 背景 / NotebookLM；**D** 具体要求（字数、语言、必含等）  
4. **Literature**（可选）：按章检索或「本章不需文献」→ 确认入库 / Zotero 同步  
5. **运行学术 Agent**（需 A + 锁定 C；文献可选；会注入已落库章节指令与 Facts）→ Draft  
6. 可选：**精修工作区** → 节内多轮预览 / Working Facts / 采纳 → **确认**出 minor（重建 References、落库 directives）  

## 核心功能（1.3）

1. **用户鉴权** — JWT 注册 / 登录  
2. **多源输入 A/B/C/D** — 粘贴、上传（含 pptx / Word 模板）、NotebookLM；定稿与大纲锁定  
3. **Summarizer** — `gpt-4o-mini` 或无 Key 直存；跟原文语言  
4. **文献检索 + Zotero** — AUT→IEEE/ACM、Z5 造词、按章向导（可跳过章）、Collection 真源同步  
5. **APA 草稿（LLM）** — 约束抽取 + 分节写作；大纲 Seed 硬输入；**禁止库外引用** + 成稿清洗；注入 `section_directives` / `confirmed_facts`  
6. **草稿精修（P0–P3 + 多轮/跨节）** — working / 分节 diff / 图·表锁定 / 节内多轮候选 / Working Facts / 下游「建议再精修」/ 确认 minor + References 重建 + directives 落库  
7. **版本与导出** — major/minor；顶栏下载 Word/PDF（APA、真表格、`项目名_v版本`）  

## 目录结构

```
academic-agent-platform/
├── backend/                 # FastAPI + LangGraph
├── frontend/                # Next.js 管理后台
├── docs/                    # 核心与归档文档
│   ├── api_reference.md
│   ├── database_schema.md
│   ├── implementation_status.md
│   ├── openai-llm-usage.md
│   └── 20260726-*.md / 20260727-*.md
├── scripts/
├── start.sh / stop.sh
├── docker-compose.yml
├── README.md
├── CHANGELOG.md
└── .cursorrules
```

## 文档

| 文档 | 说明 |
|------|------|
| [CHANGELOG.md](./CHANGELOG.md) | 版本与功能变更 |
| [docs/api_reference.md](./docs/api_reference.md) | HTTP API |
| [docs/database_schema.md](./docs/database_schema.md) | 数据表结构 |
| [docs/implementation_status.md](./docs/implementation_status.md) | 实现进度 |
| [docs/openai-llm-usage.md](./docs/openai-llm-usage.md) | OpenAI Key 用在何处 |
| [docs/20260726-draft-polish-workflow-discussion.md](./docs/20260726-draft-polish-workflow-discussion.md) | 精修工作流（P0–P3 已入 1.3.0） |
| [docs/20260727-draft-polish-multiturn-cross-section-discussion.md](./docs/20260727-draft-polish-multiturn-cross-section-discussion.md) | 节内多轮 + 跨节依赖（M0–M4 已入 1.3.0） |

## 已知限制

- Writer / Z5 / 精修依赖 OpenAI 额度与网络；失败自动回退  
- 确认时未匹配文内引用仅警告，不阻断（P4 可加严格模式）  
- 文档内嵌图 OCR / 真插图生成未做  
- PDF 导出依赖系统 pandoc；长稿需人工审阅  

详见 [implementation_status.md](./docs/implementation_status.md)。
