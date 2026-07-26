# Implementation Status

最后更新：2026-07-26 · **版本 1.1.2**

## 总览

| 模块 | 状态 | 说明 |
|------|------|------|
| 项目脚手架 / docker-compose | ✅ 完成 | PostgreSQL 16 |
| 根 `npm run dev` / `./start.sh` | ✅ 完成 | 前端 1980 / 后端 1976 |
| JWT 鉴权 | ✅ 完成 | 注册 / 登录 / me |
| Projects CRUD | ✅ 完成 | 定稿字段 + `run-agent`（A+C+Zotero 文献） |
| 多源输入重构 | ✅ 完成 | `docs/20260726-agent-input-redesign-discussion.md` |
| Sources / Summarizer / Inputs UI | ✅ 完成 | |
| 文献检索 + Zotero（Z0–Z4、Z6） | ✅ 完成 | 见 `docs/20260726-literature-zotero-search-discussion.md` |
| IEEE + ACM 多库检索 / 去重 / UI 勾选 | ✅ 完成 | 1.1.2 |
| Z5 LLM 造检索词 | ⏳ 待续 | 可手填 / `LITERATURE_TEST_QUERY` |
| Agent 按大纲写作 | ✅ 结构完成 | 模板正文；文献来自 Zotero sync |
| NotebookLM 抓取 | ✅ 完成 | |
| Pandoc 导出 / Word 导入 | ✅ / ⚠️ PDF 依赖系统 pandoc | |
| API 自动化测试 | ✅ 完成 | pytest |
| Alembic 迁移 | ⏳ 占位 | 现用 `create_all` + 硬切加列 |

## 前端组件

| 组件 | 状态 |
|------|------|
| ProjectInputs | ✅ A/B/C/D |
| LiteratureConfirmPanel | ✅ 按章向导 / IEEE·ACM 勾选 / 确认 / 同步 |
| ZoteroList | ✅ 已确认库 |
| DraftViewer / VersionHistory | ✅ |
| 登录 / 注册 / Dashboard | ✅ |

## LangGraph 节点

| 节点 | 状态 |
|------|------|
| Requirement Analyzer | ✅ 优先锁定大纲 |
| Literature Searcher | ✅ `skip_search` + 上游已 sync 的 sources |
| APA Writer | ✅ 按大纲层级；模板正文 |
| APA Formatter | ✅ |

## 已知限制

1. Z5 未做：无自动按章 LLM query。  
2. Writer 尚未接长文 LLM。  
3. 检索 run 存进程内存，重启后端后候选会话丢失（已确认文献在 Zotero/DB）。  
4. 超长 PDF 入库截断；CSL 为 stub。

## 下一步建议

1. **Z5**：有 Key 时按章 LLM 造检索词（见 `docs/openai-llm-usage.md`）。  
2. Writer 接入 `gpt-4o-mini`。  
3. Alembic。
