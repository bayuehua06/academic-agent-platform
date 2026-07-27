# Implementation Status

最后更新：2026-07-27 · **版本 1.3.0**

## 总览

| 模块 | 状态 | 说明 |
|------|------|------|
| 项目脚手架 / docker-compose | ✅ 完成 | PostgreSQL 16 |
| 根 `npm run dev` / `./start.sh` | ✅ 完成 | 前端 1980 / 后端 1976 |
| JWT 鉴权 | ✅ 完成 | 注册 / 登录 / me |
| Projects CRUD | ✅ 完成 | 定稿字段 + 改名/删除 + `run-agent`（A+C；文献可选） |
| 进度状态推导 | ✅ 完成 | API 展示非「作业完成」语义 |
| 多源输入重构 | ✅ 完成 | 含 pptx；大纲 Word 读表；模板包规范化 |
| Sources / Summarizer / Inputs UI | ✅ 完成 | 短预览 + 查看全部；删光 C 清锁定 |
| 文献检索 + Zotero（Z0–Z5） | ✅ 完成 | 向导可跳过章；空库可写作 |
| Writer LLM + **引用护栏** | ✅ 完成 | 禁止库外引用 + 成稿清洗；大纲 Seed；directives/Facts 注入 |
| 草稿精修 P0–P2 | ✅ 完成 | working / diff / polish·accept / 确认 minor（**1.2.2**） |
| 精修多轮 + 跨节（M0–M3） | ✅ 完成 | 候选栈 / Facts / stale / 大纲 Seed（**1.3.0**） |
| 确认落库 P3 / M4 | ✅ 完成 | References 重建 + `section_directives` + `confirmed_facts` |
| Pandoc 导出 / Word 导入 | ✅ / ⚠️ PDF 依赖 pandoc | APA；Markdown 表→Word 表；文件名 |
| API 自动化测试 | ✅ 完成 | pytest（含 polish / M4 confirm / citation） |
| Alembic 迁移 | ⏳ 占位 | 现用 `create_all` + 硬切加列 |
| 精修 P4 UX | 📋 未开始 | 严格引用阻断、指令编辑打磨等 |

## 前端组件

| 组件 | 状态 |
|------|------|
| ProjectInputs | ✅ A/B/C/D；大纲 .docx/.dotx |
| LiteratureConfirmPanel | ✅ 按章向导 / 本章不需文献 / Z5 |
| DraftPolishPanel | ✅ 多轮候选 / Facts / Seed / stale |
| SectionDirectivesPanel | ✅ 落库指令列表 / 停用 |
| DraftViewer / VersionHistory | ✅ major/minor；顶栏导出 |
| 登录 / 注册 / Dashboard | ✅ |

## LangGraph 节点

| 节点 | 状态 |
|------|------|
| Requirement Analyzer | ✅ |
| Literature Searcher | ✅ `skip_search` 时空库不 mock |
| APA Writer | ✅ 约束 + 分节 LLM + Seed + directives/Facts + citation_guard |
| APA Formatter | ✅ 仅按真 sources 建 References |

## 已知限制

1. 确认时未匹配文内引用仅警告，不阻断（P4 可加严格模式）。  
2. 文档内嵌图 OCR、真插图生成未做。  
3. 检索 run 存进程内存；PDF 导出依赖系统 pandoc。

## 下一步建议

1. P4：严格引用选项、指令编辑 UX、弃稿清理。  
2. Alembic；候选相关性打分（可选）。
