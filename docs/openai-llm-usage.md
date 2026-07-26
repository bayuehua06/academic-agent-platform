# OpenAI / LLM 使用说明（统一）

> 版本对齐：**v1.1.2** · 更新日期：2026-07-26  
> 配置：`backend/.env` → `OPENAI_API_KEY`、`OPENAI_MODEL`（默认 `gpt-4o-mini`）  
> Key **本身免费**；调用按量从 Platform 余额扣费。与 ChatGPT Plus **不是同一套计费**。

本文汇总：**哪些功能会用到 Key、何时触发（主动/被动）、无 Key 时行为、以及规划中的用法**。实现以代码为准。

---

## 1. 总览

| 能力 | 现状 | 触发方式 | 无 Key 时 |
|------|------|----------|-----------|
| 源文档摘要（A/B/D/C 要点） | ✅ 已用 | 见下表「被动 + 主动」 | 直存原文 / 大纲结构不丢 |
| 多份 Assessment 合并定稿 | ✅ 已用 | 被动（A 变更刷新） | `---` 拼接各份摘要 |
| 按章 LLM 造检索词（Z5） | ⏳ 未做 | 计划：主动按钮 / 进章时可选自动 | 仅手填或测试默认词 |
| Agent 长文写作（Writer） | ⏳ 未做 | 计划：`run-agent` | 继续规则模板 |
| IEEE / Zotero / Pandoc | ❌ 不用 Key | — | — |

当前代码里，**唯一真实调用 OpenAI 的模块**是 `backend/app/services/summarizer.py`（LangChain `ChatOpenAI`）。

---

## 2. 已实现：Summarizer

### 2.1 模型与回退

- 模型：`OPENAI_MODEL`（默认 `gpt-4o-mini`）
- 有 Key：按 `role` 不同 system prompt 压缩文本  
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

## 3. 规划中（有 Key 才能做「智能」）

| 能力 | Track | 建议触发 | 说明 |
|------|-------|----------|------|
| 按章生成检索词 | **Z5** | 主动：「生成本章检索词」；可选进章时自动填入输入框 | 无 Key 禁止自动造词，仅手填 / `LITERATURE_TEST_QUERY` |
| 草稿正文 LLM 增强 | Writer 后续 | 被动：点「运行学术 Agent」 | 现为规则模板；接 Key 后按 `paper_outline` + Zotero 文献生成 |
| 其它（可选） | — | — | 如候选相关性打分、多库 query 改写——**未立项** |

Z5 与 Writer 上线后，应回写本节「现状」列，并在 `CHANGELOG` 记一笔。

---

## 4. 明确不用 OpenAI 的部分

| 模块 | 说明 |
|------|------|
| AUT → IEEE / ACM 检索 | Playwright + AUT 账号 |
| 项目勾选 `literature_databases` | UI + create/patch；双库各 `max_results` 后 DOI/标题去重 |
| Zotero ping / 结构 / import / sync | pyzotero + `ZOTERO_*` |
| 文献「已存在」标注 | DOI/标题比对，无 LLM |
| Pandoc / Word / PDF | 本地工具链 |
| JWT / 项目 CRUD | 无 LLM |

---

## 5. 配置与安全

```env
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
```

- 只放本机 `backend/.env`，已在 `.gitignore`  
- 泄露后到 [platform.openai.com/api-keys](https://platform.openai.com/api-keys) **Revoke** 并换新  
- 开通步骤见此前说明：Platform 账号 → Billing 充值 → Create key → 写入 `.env` → **重启后端**  

自检：上传一段短 Assessment，看 `summary_text` 是否明显短于原文；或看 Platform Usage 是否有调用。

---

## 6. 相关代码入口

| 文件 | 职责 |
|------|------|
| `backend/app/services/summarizer.py` | LLM / passthrough |
| `backend/app/api/sources.py` | 创建/上传/reparse/summarize/notebook-sync |
| `backend/app/services/project_assembly.py` | 定稿刷新、大纲锁定时摘要、A 合并 |
| `backend/app/core/config.py` | `openai_api_key` / `openai_model` |

---

## 附：检索库「可配置可选」现状（顺带澄清）

此前约定的模型是：

| 层 | 设计 | 实现情况 |
|----|------|----------|
| 全局 `.env` | IEEE/ACM 入口 URL、`LITERATURE_DEFAULT_DATABASES` | ✅ 已有 |
| 项目字段 `literature_databases` | 如 `["ieee"]` / `["ieee","acm"]` | ✅ 后端 create/patch/API |
| `GET /api/literature-providers` | 列出注册表 | ✅ 已有 |
| 检索时按项目勾选跑库 | IEEE + ACM；多库各取 N 条后 DOI/标题去重 | ✅ |
| **前端勾选 UI** | 文献向导多选芯片（写入项目配置） | ✅ |
