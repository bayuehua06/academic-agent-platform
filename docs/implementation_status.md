# Implementation Status

最后更新：2026-07-26 · **版本 1.2.0**

## 总览

| 模块 | 状态 | 说明 |
|------|------|------|
| 项目脚手架 / docker-compose | ✅ 完成 | PostgreSQL 16 |
| 根 `npm run dev` / `./start.sh` | ✅ 完成 | 前端 1980 / 后端 1976 |
| JWT 鉴权 | ✅ 完成 | 注册 / 登录 / me |
| Projects CRUD | ✅ 完成 | 定稿字段 + 改名/删除 + `run-agent`（A+C+Zotero 文献） |
| 进度状态推导 | ✅ 完成 | API 展示非「作业完成」语义 |
| 多源输入重构 | ✅ 完成 | `docs/20260726-agent-input-redesign-discussion.md` |
| Sources / Summarizer / Inputs UI | ✅ 完成 | 短预览 + 查看全部；摘要跟原文语言 |
| 文献检索 + Zotero（Z0–Z4、Z6） | ✅ 完成 | 见 `docs/20260726-literature-zotero-search-discussion.md` |
| IEEE + ACM 多库检索 / 去重 / UI 勾选 | ✅ 完成 | 1.1.2 |
| Z5 LLM 造检索词 | ✅ 完成 | 1.2.0：`suggest-query` + 向导按钮 / 可选进章自动 |
| Writer LLM 长文 | ✅ 完成 | 1.2.0：约束抽取 + 分节/扩写/校验；默认英文 |
| Agent 按大纲写作 | ✅ 完成 | LLM 或模板；文献来自 Zotero sync |
| NotebookLM 抓取 | ✅ 完成 | |
| Pandoc 导出 / Word 导入 | ✅ / ⚠️ PDF 依赖系统 pandoc | |
| API 自动化测试 | ✅ 完成 | pytest |
| Alembic 迁移 | ⏳ 占位 | 现用 `create_all` + 硬切加列 |

## 前端组件

| 组件 | 状态 |
|------|------|
| ProjectInputs | ✅ A/B/C/D；预览 / 全文 |
| LiteratureConfirmPanel | ✅ 按章向导 / IEEE·ACM 勾选 / Z5 造词 / 确认 / 同步 |
| ZoteroList | ✅ 已确认库 |
| DraftViewer / VersionHistory | ✅ |
| 登录 / 注册 / Dashboard | ✅ 改名 / 删除 / 进度标签 |

## LangGraph 节点

| 节点 | 状态 |
|------|------|
| Requirement Analyzer | ✅ 优先锁定大纲 |
| Literature Searcher | ✅ `skip_search` + 上游已 sync 的 sources |
| APA Writer | ✅ 有 Key → 约束 + 分节 LLM；否则模板 |
| APA Formatter | ✅ |

## 已知限制

1. Writer / Z5 依赖 OpenAI 额度与网络；失败自动回退。  
2. 检索 run 存进程内存，重启后端后候选会话丢失（已确认文献在 Zotero/DB）。  
3. 超长 PDF 入库截断；CSL 为 stub；长稿需人工审阅。

## 下一步建议

1. 候选相关性 LLM 打分（可选，未立项）。  
2. Alembic。  
3. Writer 分章流式输出 / 前端进度展示。
