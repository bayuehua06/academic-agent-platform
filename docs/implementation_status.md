# Implementation Status

最后更新：2026-07-27 · **版本 1.3.1**

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
| Writer LLM + **引用护栏** | ✅ 完成 | 禁止库外引用 + 成稿清洗；directives/Facts |
| Writer 输入优先级 W1–W4 | ✅ 完成 | 表/结构保真；A=D 硬；字数压缩；must_apply（**1.3.1**） |
| 草稿精修 P0–P2 | ✅ 完成 | working / diff / polish·accept / 确认 minor（**1.2.2**） |
| 精修多轮 + 跨节（M0–M3） | ✅ 完成 | 候选栈 / Facts / stale / 大纲 Seed（**1.3.0**） |
| 确认落库 P3 / M4 | ✅ 完成 | References 重建 + `section_directives` + `confirmed_facts` |
| Pandoc 导出 / Word 导入 | ✅ / ⚠️ PDF 依赖 pandoc | APA；Markdown 表→Word 表；文件名 |
| API 自动化测试 | ✅ 完成 | pytest（含 structure / polish / M4 / citation） |
| Alembic 迁移 | ⏳ 占位 | 现用 `create_all` + 硬切加列 |
| 精修 P4 / Writer W5 | 📋 未开始 | 严格阻断模式、指令 UX 等 |

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
| APA Writer | ✅ A/D 硬约束 + 结构/表 + 压缩 + must_apply + citation_guard |
| APA Formatter | ✅ 仅按真 sources 建 References |

## 已知限制

1. 页数不硬校验；must_apply / 未匹配引用目前仅警告。  
2. 文档内嵌图 OCR、真插图生成未做。  
3. 检索 run 存进程内存；PDF 导出依赖系统 pandoc。

## 下一步建议

1. W5 / P4：严格模式（缺表或套用失败可阻断）、指令编辑 UX。  
2. Alembic；候选相关性打分（可选）。
