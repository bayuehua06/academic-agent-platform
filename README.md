# Academic Agent Platform

**版本：1.2.0**

学术辅助平台：多源输入（Assessment / 背景 / 大纲 / 具体要求）→ Summarizer 定稿 → **按章 IEEE/ACM 检索（可 LLM 造词）并确认入 Zotero** → LangGraph 按锁定大纲生成 APA 7th 草稿（有 Key 时 LLM 分节写作）；可选 NotebookLM 抓取；支持版本控制与 Word/PDF 导出导入。

## 技术栈

| 层级 | 技术 |
|------|------|
| Frontend | Next.js (App Router), Tailwind CSS |
| Backend | FastAPI, SQLAlchemy (Async), Pydantic v2 |
| Agent | LangGraph, LangChain, pyzotero |
| 文献检索 | Playwright（AUT Library → IEEE / ACM） |
| Database | PostgreSQL |
| Documents | Pandoc, python-docx, pypandoc, pypdf |
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

# Zotero（写作真源）
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

- **Summarizer / Z5**：`OPENAI_MODEL`（默认 `gpt-4o-mini`）
- **Writer**：`OPENAI_WRITER_MODEL`（默认 `gpt-4o`）；空则回退 `OPENAI_MODEL`
- 无 Key：摘要直存原文；检索词规则回退；写作用模板

**OpenAI 用在哪些地方（主动/被动）**：见 [docs/openai-llm-usage.md](./docs/openai-llm-usage.md)。

### 典型使用路径

1. 创建项目 → Inputs 四区  
2. **A** Assessment → 定稿；**C** 大纲 → **锁定**  
3. 可选：**B** 背景 / NotebookLM；**D** 具体要求（字数、语言、必含等）  
4. **Literature**：勾选 IEEE/ACM → 按章检索（可「生成本章检索词」）→ 确认 → 入 Zotero（可桌面离线再补，点「从 Zotero 同步」）  
5. **运行学术 Agent**（需 A + 锁定 C + Zotero 集合中有文献）→ Draft  

## 核心功能（1.2）

1. **用户鉴权** — JWT 注册 / 登录  
2. **多源输入 A/B/C/D** — 粘贴、上传、NotebookLM sync；定稿与大纲锁定；短预览 + 全文查看  
3. **Summarizer** — `gpt-4o-mini` 或无 Key 直存；跟原文语言，不默认译中  
4. **文献检索 + Zotero** — AUT→IEEE/ACM、多库去重、Z5 造词、按章向导、确认入库、Collection 真源同步  
5. **APA 草稿（LLM）** — 约束抽取 + 分节写作 / 扩写 / 校验；默认学术英文；无 Key 回退模板  
6. **项目管理 UX** — 改名 / 删除；进度按就绪度推导（非「作业完成」）  
7. **版本控制** — Draft 历史、Word/PDF 导出、Word 逆向导入  

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
│   ├── 20260726-agent-input-redesign-discussion.md
│   └── 20260726-literature-zotero-search-discussion.md
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
| [docs/openai-llm-usage.md](./docs/openai-llm-usage.md) | OpenAI Key 用在何处（主动/被动）与规划 |
| [docs/20260726-agent-input-redesign-discussion.md](./docs/20260726-agent-input-redesign-discussion.md) | 1.1 输入重构设计归档 |
| [docs/20260726-literature-zotero-search-discussion.md](./docs/20260726-literature-zotero-search-discussion.md) | 1.1.1 文献/Zotero 设计归档 |

## 已知限制

- Writer / Z5 依赖 OpenAI 额度与网络；失败自动回退  
- 检索 run 存进程内存，重启后端后候选会话丢失（已确认文献在 Zotero/DB）  
- NotebookLM / IEEE·ACM 自动化需本机浏览器（CDP 或独立 Chrome）  
- PDF 导出依赖系统 pandoc；长稿需人工审阅  

详见 [implementation_status.md](./docs/implementation_status.md)。
