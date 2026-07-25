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

固定端口：**前端 `1980`** / **后端 `1976`**。若端口已被占用，`npm run dev` 会提示先 kill。

### 1. 启动数据库

```bash
docker compose up -d
```

### 2. 首次安装依赖

```bash
# 后端
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

# 前端 + 根脚本
cd ..
npm run install:all
cp frontend/.env.example frontend/.env.local
```

### 3. 一键启动前后端

```bash
npm run dev
```

- 控制面板：http://localhost:1980
- API 文档：http://localhost:1976/docs

## 目录结构

```
academic-agent-platform/
├── backend/          # FastAPI + LangGraph
├── frontend/         # Next.js 管理后台
├── docker-compose.yml
└── README.md
```

## 核心功能

1. **用户鉴权** — JWT 注册 / 登录
2. **NotebookLM 同步** — MVP 粘贴/上传；预留 Playwright 抓取
3. **文献检索** — IEEE Xplore / Google Scholar（browser-use）+ Zotero 同步
4. **APA 7th 草稿** — LangGraph 工作流：需求分析 → 检索 → 撰写 → 参考文献格式化
5. **版本控制** — Draft 版本历史、Word/PDF 导出、Word 逆向导入 Markdown

## 环境变量

见 `backend/.env.example` 与 `frontend/.env.example`。

## 开发状态

当前为可运行的基础框架（脚手架 + 数据模型 + 鉴权 + 服务桩 + Agent 图 + 前端看板）。完整文献检索依赖本地 Chrome Profile / API Key 配置后启用。
