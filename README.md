# Academic Agent Platform

学术辅助平台：读取 Google NotebookLM 输入，自动检索学术文献并同步至 Zotero，使用 LangGraph 生成符合 APA 7th 规范的论文草稿，支持版本控制、Word/PDF 导档与逆向 Word 导入。

## 技术栈

| 层级 | 技术 |
|------|------|
| Frontend | Next.js (App Router), Tailwind CSS, Shadcn UI |
| Backend | FastAPI, SQLAlchemy (Async), Pydantic v2 |
| Agent | LangGraph, LangChain, browser-use, pyzotero |
| Database | PostgreSQL |
| Documents | Pandoc, python-docx, pypandoc |
| Auth | JWT / OAuth2 Password (Passlib/Bcrypt) |

## 快速开始

固定端口：**前端 `1980`** / **后端 `1976`**。

### 一键启动（推荐）

```bash
./start.sh
```

会自动：停止旧进程 → 检查/释放端口 → 安装依赖 → 初始化 PostgreSQL（Docker 或本机）→ 启动前后端。

停止：

```bash
./stop.sh
```

- 控制面板：http://localhost:1980
- API 文档：http://localhost:1976/docs

### 仅用 npm（需已装好依赖与数据库）

```bash
npm run dev
```

端口已被占用时会提示先 kill；也可用 `./stop.sh` 释放。

### 手动准备（可选）

数据库二选一：

```bash
# A. Docker
docker compose up -d

# B. 本机 PostgreSQL（无 Docker 时 ./start.sh 会自动创建 academic 角色与库）
./scripts/ensure-db.sh
```

首次依赖：

```bash
cd backend && python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
cd .. && npm run install:all
cp frontend/.env.example frontend/.env.local
```

## 目录结构

```
academic-agent-platform/
├── backend/                 # FastAPI + LangGraph
├── frontend/                # Next.js 管理后台
├── docs/                    # 核心与规划文档
│   ├── api_reference.md
│   ├── database_schema.md
│   ├── implementation_status.md
│   └── 20260725-*.md        # 已完成的规划/实现文档
├── scripts/                 # ensure-db / npm run dev 辅助脚本
├── start.sh                 # 一键初始化并启动
├── stop.sh                  # 停止服务并释放端口
├── docker-compose.yml
├── README.md
├── CHANGELOG.md
└── .cursorrules
```

## 核心功能

1. **用户鉴权** — JWT 注册 / 登录
2. **NotebookLM 同步** — MVP 粘贴/上传；预留 Playwright 抓取
3. **文献检索** — IEEE Xplore / Google Scholar（browser-use）+ Zotero 同步
4. **APA 7th 草稿** — LangGraph 工作流：需求分析 → 检索 → 撰写 → 参考文献格式化
5. **版本控制** — Draft 版本历史、Word/PDF 导出、Word 逆向导入 Markdown

## 文档

| 文档 | 说明 |
|------|------|
| [CHANGELOG.md](./CHANGELOG.md) | 版本与功能变更 |
| [docs/api_reference.md](./docs/api_reference.md) | HTTP API |
| [docs/database_schema.md](./docs/database_schema.md) | 数据表结构 |
| [docs/implementation_status.md](./docs/implementation_status.md) | 实现进度 |

## 环境变量

见 `backend/.env.example` 与 `frontend/.env.example`。

## 开发状态

见 [docs/implementation_status.md](./docs/implementation_status.md)。当前为可运行基础框架；完整文献检索依赖 Chrome Profile / API Key 配置后启用。
