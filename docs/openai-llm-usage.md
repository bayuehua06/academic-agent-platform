# OpenAI / LLM 使用说明（统一）

> 版本对齐：**v1.2.0**（Z5 / Writer LLM / 默认英文）· 更新日期：2026-07-26  
> 配置：`backend/.env` → `OPENAI_API_KEY`、`OPENAI_MODEL`（默认 `gpt-4o-mini`）、`OPENAI_WRITER_MODEL`（默认 `gpt-4o`）  
> Key **本身免费**；调用按量从 Platform 余额扣费。与 ChatGPT Plus **不是同一套计费**。

本文汇总：**哪些功能会用到 Key、何时触发（主动/被动）、无 Key 时行为**。实现以代码为准。

---

## 1. 总览

| 能力 | 现状 | 触发方式 | 无 Key 时 |
|------|------|----------|-----------|
| 源文档摘要（A/B/D/C 要点） | ✅ 已用 | 见下表「被动 + 主动」 | 直存原文 / 大纲结构不丢 |
| 多份 Assessment 合并定稿 | ✅ 已用 | 被动（A 变更刷新） | `---` 拼接各份摘要 |
| 按章 LLM 造检索词（Z5） | ✅ 已用 | 主动：「生成本章检索词」；可选进章自动填入 | 规则回退词（标题/要点） |
| Agent 长文写作（Writer） | ✅ 已用 | 被动：`run-agent` | 继续规则模板 |
| IEEE / ACM / Zotero / Pandoc | ❌ 不用 Key | — | — |

调用入口：`summarizer.py`、`literature_query.py`（Z5）、`agents/nodes/writer.py`（共用 `llm_client.py`）。

---

## 2. 已实现：Summarizer

### 2.1 模型与回退

- 模型：`OPENAI_MODEL`（默认 `gpt-4o-mini`）
- 有 Key：按 `role` 不同 system prompt 压缩文本（**跟原文语言，不默认译成中文**）  
- 无 Key / 调用失败 / 空返回：**passthrough**，把可用原文写入 `summary_text`，流程不中断  
- 送入 LLM 的原文有长度上限（约 1.2 万字符量级），超长会截断再摘要  

### 2.2 按角色做什么

| `role` | LLM 任务（有 Key） |
|--------|-------------------|
| `ASSESSMENT` | 压缩 rubric / 作业说明，保留评分与硬性约束 |
| `BACKGROUND` | 背景笔记 / Notebook 对话等 → 要点摘要 |
| `SPECIFIC` | 字数、引用格式等具体要求 → 短条目 |
| `OUTLINE` | 在已有标题结构下压缩各节 `key_points`（不新造章节） |

### 2.3 触发方式（主动 vs 被动）

**被动（用户没点「摘要」，系统顺带跑）**

| 用户动作 | API / 路径 | 是否可能调 LLM |
|----------|------------|----------------|
| Inputs 粘贴创建源文档 | `POST .../sources` | ✅ 创建后 `_apply_parse_and_summarize` |
| Inputs 上传文件 | `POST .../sources/upload` | ✅ 同上 |
| NotebookLM 同步 | `POST .../sources/notebook-sync` | ✅ 抓取成功后摘要 BACKGROUND |
| 重新解析 | `POST .../sources/{id}/reparse` | ✅ 再解析后再摘要 |
| 锁定大纲 | `POST .../outline/lock` | ✅ 若大纲尚未 `SUMMARIZED`，会 `apply_to_document` |
| A/D 增删改后刷新定稿 | `project_assembly.refresh_project_drafts` | ✅ 多份 A 时 `merge_assessment_parts`（≥2 份且有 Key 才 LLM 合并） |

**主动（用户明确点按钮）**

| 用户动作 | API | 说明 |
|----------|-----|------|
| 前端「重新摘要 / Summarize」 | `POST .../sources/{id}/summarize` | 强制再跑一遍 Summarizer |

> **不是**每次打开页面都会调 OpenAI；只有上述写入/刷新/点击时才会。

### 2.4 费用直觉（粗算）

- 摘要类调用：单次通常几千～一万 token 量级，`gpt-4o-mini` 很便宜  
- 联调期：粘贴/上传几次 A/B/C/D ≈ 几次调用；设好 Platform **月度限额**更安心  

---

## 3. 已实现：Z5 按章检索词

| 项 | 说明 |
|----|------|
| API | `POST /api/projects/{id}/literature-search/suggest-query` Body: `{ outline_heading }` |
| 返回 | `{ query, mode: llm\|fallback, openai_configured }` |
| 前端 | 「生成本章检索词」；可选「进章时自动生成」 |
| 输入 | 章节 heading + key_points + assessment / specific 定稿摘要 |
| 无 Key | `mode=fallback`，由标题/要点拼英文倾向检索词 |

---

## 4. 已实现：Writer 长文

| 项 | 说明 |
|----|------|
| 触发 | `POST /api/projects/{id}/run-agent`（有 Key 时） |
| 模型 | `OPENAI_WRITER_MODEL`（默认 `gpt-4o`）；空则回退 `OPENAI_MODEL`。Summarizer/Z5 仍用 mini |
| 约束 | 先从 D+A **抽取通用 checklist**（字数/引用/必含/禁止等），失败则规则回退；**原文 D 始终附带** |
| 语言 | **默认学术英文**；仅当约束明确要求中文（或其他语言）时才切换 |
| 分节 | 每节 + 扩写均带完整 HARD CONSTRAINTS；并附上一节末尾以保持连贯 |
| 校验 | 成稿后检查字数与 must_include；不达标再补写一轮 |
| 回退 | 无 Key / 全节失败 → 模板；changelog 含 model / words / target / verify_ok |

> 字数只是 checklist 的一项，不是唯一目标。

---

## 5. 明确不用 OpenAI 的部分

| 模块 | 说明 |
|------|------|
| AUT → IEEE / ACM 检索 | Playwright + AUT 账号 |
| 项目勾选 `literature_databases` | UI + create/patch；双库各 `max_results` 后 DOI/标题去重 |
| Zotero ping / 结构 / import / sync | pyzotero + `ZOTERO_*` |
| 文献「已存在」标注 | DOI/标题比对，无 LLM |
| Pandoc / Word / PDF | 本地工具链 |
| JWT / 项目 CRUD | 无 LLM |

---

## 6. 配置与安全

```env
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
OPENAI_WRITER_MODEL=gpt-4o
```

- 只放本机 `backend/.env`，已在 `.gitignore`  
- 泄露后到 [platform.openai.com/api-keys](https://platform.openai.com/api-keys) **Revoke** 并换新  
- 开通后 **重启后端**  

自检：上传短 Assessment 看摘要是否压缩；Literature 点「生成本章检索词」；有文献后 `run-agent` 看草稿是否明显长于模板句。

---

## 7. 相关代码入口

| 文件 | 职责 |
|------|------|
| `backend/app/services/summarizer.py` | 源文档摘要 / A 合并 |
| `backend/app/services/literature_query.py` | Z5 检索词 |
| `backend/app/services/writing_constraints.py` | D/A 约束抽取与成稿校验 |
| `backend/app/services/llm_client.py` | 共用 Chat；`purpose=writer` 走 Writer 模型 |
| `backend/app/agents/nodes/writer.py` | 分节写作 / 扩写 / 补写 |
| `backend/app/api/literature_search.py` | `suggest-query` |
| `backend/app/api/sources.py` | 创建/上传/reparse/summarize |
| `backend/app/core/config.py` | `openai_api_key` / `openai_model` / `openai_writer_model` |

---

## 附：检索库配置

| 层 | 实现情况 |
|----|----------|
| 全局 `.env` IEEE/ACM URL、默认库 | ✅ |
| 项目 `literature_databases` + 向导勾选 | ✅ |
| 多库各 N 条 + DOI/标题去重 | ✅ |
