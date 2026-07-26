# Agent 输入重构 — 设计讨论稿

状态：**决策已确认**（待实现）  
日期：2026-07-26（修订）  
背景：NotebookLM 作为唯一上下文过窄；改为「多源输入 → Summarizer → 严格按论文架构写作」。

---

## 0. 已确认决策

| 议题 | 结论 |
|------|------|
| **C 架构录入** | **以上传 Word/Markdown 为主**，用 **Heading 样式/标题层级** 识别章节；导入后可预览校对。最终 APA 导出沿用同一章节结构。 |
| **B 多条** | **允许**：多个 Notebook、多个 PDF/Word 等，全部落在 `project_source_documents`（`role=BACKGROUND`）。 |
| **A 评分结构** | **不固定** criteria schema；1～N 文档，Summarizer 自由归纳。 |
| **Summarizer 模型** | **OpenAI `gpt-4o-mini`**（不启用 Premium 双模型，除非日后不够用再加）。 |
| **优先级** | **A > C > B > D** |
| **库表** | **删除** `notebooklm_inputs` 与 `projects.assessment_requirements`；**新增** `project_source_documents`；`projects` 上保留定稿缓存三列。 |
| **定稿缓存** | `assessment_summary` / `paper_outline` / `specific_requirements` 在 `projects`；**变更后必须重生成**（见 4.7）。 |
| **B 与 Agent** | B **不**单独缓存到 projects；写作/检索时 Agent **自行查询**该项目下所有 `role=BACKGROUND` 且已 SUMMARIZED 的文档摘要。 |

优先级理由（用户确认）：

1. 先有评分要求，才能决定/约束文章结构；  
2. 基础文档齐了之后，再提 specific 要求更合理。

写作含义：

- **不得违反 A**（评分点、硬性要求优先满足）；  
- **章节顺序与标题遵循 C**（Header 识别出的骨架）；若 C 与 A 冲突，在 Summarizer/预检阶段提示用户改 C，而不是 Writer 擅自加章；  
- B 只提供论据与上下文；  
- D 在不违背 A/C 的前提下细化风格/禁区等。

---

## 1. 输入模型

| # | 角色 | 必选？ | 形态 | 进 Agent 前 |
|---|------|--------|------|-------------|
| **A** | Assessment + 评分标准 | **必选** | 粘贴 和/或 **多个** Word/PDF/md | Summarizer → `assessment_summary` |
| **B** | 背景材料 | 可选（可多条） | NotebookLM、PDF、Word、粘贴… | 每条 Summarizer → 多条 background summaries |
| **C** | 论文架构 + 各段要点 | **必选** | **上传 Word/Markdown**（Heading 分层）；预览确认 | Parser → `paper_outline[]`；写作与导出共用 |
| **D** | Specific 要求 | 可选 | 短文本或小文档 | Summarizer 或短原文 → `specific_requirements` |

---

## 2. C：Header 驱动架构（采纳方案）

### 2.1 识别规则

- **Word**：`Heading 1` / `Heading 2` / `Heading 3`（python-docx 样式名）→ 大纲层级。  
- **Markdown**：`#` / `##` / `###`。  
- 每个 heading 后、下一同级/更高级 heading 前的正文 → 该节「主要内容/要点」原文（可再经 Summarizer 压成 `key_points`）。

### 2.2 用户流程

1. 上传大纲 Word（或 md）；  
2. 后端解析出 section 树，UI **只读预览 + 可选微调**（改标题/合并节，避免完全手打）；  
3. 用户确认「锁定大纲」后写入 `paper_outline`；  
4. Writer **按此顺序逐节生成**；Pandoc/docx **导出同一 heading 结构**（与 APA 正文一致）。

### 2.3 与「表单」的关系

- 不以空白表单为录入主路径（同意「上传更方便」）。  
- 预览页允许小改，保证 Header 识别偶发错误时可修，从而仍能「严格按框架」。

---

## 3. Agent 流水线

```
A/B/C/D 原始输入
    → Ingest（docx/pdf/md/Notebook 文本）
    → Summarizer LLM（A/B/D）；C 以 Header Parser 为主，可选 LLM 润色 key_points
    → Assembled Context（按优先级装配）
    → Researcher（query 受 A 主题 + C 各节要点约束）
    → Writer（逐节按 C；满足 A；参考 B；落实 D）
    → APA Formatter + 导出（heading 与 C 对齐）
```

---

## 4. 数据库变更（专题讨论 · 待确认）

### 4.1 总原则

| 动作 | 对象 | 说明 |
|------|------|------|
| **删除** | `notebooklm_inputs` | 按你的建议拿掉；Notebook 变为 B 的一种来源，不再单独建表 |
| **新增** | `project_source_documents` | 统一承载 A/B/C/D 的粘贴、上传、Notebook 抓取 |
| **调整** | `projects` | 去掉「仅靠一列 assessment 文本」的旧习惯；增加写作用的**聚合/锁定**字段 |
| **不动** | `users` / `literatures` / `draft_versions` | 继续服务鉴权、文献、草稿版本 |

> 当前库基本是开发数据，**建议直接 drop 旧表 + create 新表**（不必做复杂数据迁移）。若你之后有要保留的项目，再说迁移脚本。

### 4.2 新 ER

```
users 1──* projects 1──* project_source_documents
                 │
                 ├──* literatures
                 └──* draft_versions
```

（`notebooklm_inputs` 不再存在。）

### 4.3 新表 `project_source_documents`（建议 DDL）

```sql
CREATE TABLE project_source_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,

    -- A / B / C / D
    role VARCHAR(20) NOT NULL,
    -- ASSESSMENT | BACKGROUND | OUTLINE | SPECIFIC

    -- 来源形态
    source_type VARCHAR(20) NOT NULL,
    -- PASTE | UPLOAD | NOTEBOOKLM

    title VARCHAR(255),                  -- 展示名（文件名或用户起的标题）
    notebook_url VARCHAR(500),           -- 仅 NOTEBOOKLM
    original_filename VARCHAR(255),      -- 仅 UPLOAD
    content_type VARCHAR(100),           -- 如 application/vnd... / application/pdf / text/markdown
    storage_path VARCHAR(500),           -- 可选：原始文件落盘路径（uploads/...）

    raw_text TEXT,                       -- 解析/抓取后的全文
    summary_text TEXT,                   -- Summarizer 输出（自由文本，不强制 criteria schema）
    summary_json JSONB,                  -- 可选：模型返回的松散结构；C 也可用 JSON 存 outline 树

    -- C：Header 解析出的大纲（也可只放在 projects.paper_outline；二选一或双写）
    -- 建议：单条 OUTLINE 文档的解析结果放本行 summary_json；
    --       用户「锁定」后的定稿大纲放 projects.paper_outline

    status VARCHAR(30) NOT NULL DEFAULT 'PENDING',
    -- PENDING | PARSED | SUMMARIZED | FAILED
    error_message TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    summarized_at TIMESTAMPTZ
);

CREATE INDEX ix_psd_project_role ON project_source_documents(project_id, role);
```

**字段设计说明（供讨论）：**

1. **`role` + `source_type` 正交**  
   - Notebook = `role=BACKGROUND` + `source_type=NOTEBOOKLM`  
   - 评分 PDF = `role=ASSESSMENT` + `source_type=UPLOAD`  
   - 架构 Word = `role=OUTLINE` + `source_type=UPLOAD`  
   - Specific 粘贴 = `role=SPECIFIC` + `source_type=PASTE`

2. **`raw_text` vs 只存文件**  
   - 建议：**解析后必落 `raw_text`**，写作/摘要不依赖反复读盘；原文件可选 `storage_path` 便于追溯。

3. **一条文档一行**  
   - A/B 都允许多行；C 建议业务上「当前生效大纲」以 `projects.paper_outline` 为准，历史上传仍可留多行 OUTLINE。

### 4.4 `projects` 表怎么改

| 列 | 建议 | 理由 |
|----|------|------|
| `assessment_requirements` | **删除或降级** | 原文改由 `project_source_documents`（ASSESSMENT）承载；避免双源不一致 |
| `assessment_summary` **新增** TEXT | Summarizer 对 **全部 A 文档合并后** 的定稿摘要，供 Writer 直接读 |
| `paper_outline` **新增** JSONB | 用户确认锁定后的 C：`[{level, heading, key_points/body}]` |
| `outline_locked_at` **新增** TIMESTAMPTZ | 可选；锁定时间 |
| `specific_requirements` **新增** TEXT | D 的定稿短文本（可来自 SPECIFIC 文档摘要合并） |
| `zotero_collection_id` / `status` / 时间戳 | **保留** | |

可选简化：不在 `projects` 上存 `assessment_summary`，写作时现查所有 ASSESSMENT 的 `summary_text` 拼接——但 **多文件时「合并摘要」仍建议有一列定稿**，否则每次跑 Agent 都要再调 LLM。

**推荐：`projects` 保留三列定稿缓存**

- `assessment_summary`  
- `paper_outline`  
- `specific_requirements`  

源材料一律在 `project_source_documents`。

### 4.5 删除 `notebooklm_inputs` 的影响（实现时一并改）

| 位置 | 处理 |
|------|------|
| ORM `NotebookLMInput` | 删除 |
| API `/api/notebook/*` | 改为 `/api/sources/*` 或挂在 projects 下；`NOTEBOOKLM` 只是 `source_type` |
| 前端 Inputs Tab | Notebook 区块并入「背景材料 B」 |
| Agent `notebook_context` | 改为 assembled：A summary + C outline + B summaries + D |
| 测试 | 替换 notebook 用例为 sources 用例 |

### 4.6 库表问题 — 已确认

1. **直接删除 `notebooklm_inputs`，不做迁移** — 是  
2. **删除 `projects.assessment_requirements`** — 是  
3. **定稿三列放在 `projects`** — 是（见 4.7 更新机制）  
4. **上传文件落盘 `storage_path`** — 是  

### 4.7 定稿缓存的更新机制（必做）

| 触发 | 动作 |
|------|------|
| 新增/删除/替换 **A** 文档，或对某条 A 重新 Summarize | 合并所有 A 的摘要（或再调一次 LLM 合并）→ 写回 `projects.assessment_summary` |
| 上传/替换 **C** 大纲，或用户在预览里改完并点「锁定」 | Header 解析 → 写回 `projects.paper_outline`，更新 `outline_locked_at` |
| 新增/删除/修改 **D** | 更新 `projects.specific_requirements` |
| 仅变更 **B** | **不改** projects 三列；只更新对应 `project_source_documents` 行。Agent 运行时现查 B |

实现时：每次 A/C/D 的 ingest/summarize/lock API 成功后调用 `refresh_project_assembled_fields(project_id)`，避免漏更新。

### 4.8 B 与 Agent 的取数方式

```
Writer / Researcher 启动时：
  A ← projects.assessment_summary          # 定稿缓存
  C ← projects.paper_outline               # 定稿缓存
  D ← projects.specific_requirements       # 定稿缓存
  B ← SELECT summary_text FROM project_source_documents
        WHERE project_id=? AND role='BACKGROUND' AND status='SUMMARIZED'
        ORDER BY created_at
```

是的：**B 只在 `project_source_documents` 里；Agent 自己去拿**，不必再镜像到 `projects`。

---

## 5. 「严格按框架」如何落实

1. Writer **只遍历已锁定的 `paper_outline`** 生成对应 Heading。  
2. Researcher 按 **每一节** 的 heading + 要点 + A 摘要生成检索词。  
3. 导出 docx：section heading 样式与 C 一致。  
4. 运行前校验：至少 1 条 A、已锁定 C；否则禁止写作。

---

## 6. 实现步骤与顺序（Track 清单）

> 用法：每完成一项把 `[ ]` 改成 `[x]`，并在「完成日期」打钩。  
> 状态约定：`待开始` → `进行中` → `已完成` / `跳过`。  
> 原则：**先库表与 API，再 UI，再 Summarizer，最后改写作 Agent**；每步可独立验证。

**总进度**（2026-07-26）：Phase 0–6 已完成并发布 **v1.1.0**。  
说明：Phase 5 结构对齐已实现；检索仍为模拟、写作仍为模板（LLM 真写为后续增强）。

---

### Phase 0 — 文档与环境锁板

| # | 步骤 | 状态 | 完成日期 | 验证方式 |
|---|------|------|----------|----------|
| 0.1 | 设计决策全部写入本文 §0 / §4 | [x] | 2026-07-26 | 本文已锁定 |
| 0.2 | 正式库表同步到 `docs/database_schema.md` | [x] | 2026-07-26 | 与 §4 一致 |
| 0.3 | `docs/api_reference.md` / `implementation_status.md` 在 Phase 1 结束后更新 | [x] | 2026-07-26 | 与实现一致 |
| 0.4 | `.env`：确认 `OPENAI_API_KEY` + `OPENAI_MODEL=gpt-4o-mini`（Summarizer 用） | [ ] | | 能调通一次 chat |

---

### Phase 1 — 数据库与 ORM 硬切

| # | 步骤 | 状态 | 完成日期 | 验证方式 |
|---|------|------|----------|----------|
| 1.1 | ORM：删除 `NotebookLMInput`；`projects` 去掉 `assessment_requirements`，增加 `assessment_summary` / `paper_outline` / `outline_locked_at` / `specific_requirements` | [x] | 2026-07-26 | models 与 schema 文档一致 |
| 1.2 | ORM：新增 `ProjectSourceDocument`（字段按 `database_schema.md`） | [x] | 2026-07-26 | |
| 1.3 | 本地库硬切：drop `notebooklm_inputs`；alter `projects`；create `project_source_documents`（开发库可重建） | [x] | 2026-07-26 | 表结构已核对 |
| 1.4 | 删除/停用旧 `app/api/notebook.py` 引用；修复 import 与测试中的 notebook 依赖（先改成 skip 或删旧测） | [x] | 2026-07-26 | `pytest` 33 passed |

**Phase 1 出口**：应用能启动，旧 notebook 路由不再注册（或 410），新表可写入一条测试行。 ✅

---

### Phase 2 — Sources API + 定稿刷新服务

| # | 步骤 | 状态 | 完成日期 | 验证方式 |
|---|------|------|----------|----------|
| 2.1 | 新增 `services/document_ingest.py`：粘贴 / docx / md / pdf → `raw_text`；UPLOAD 落盘 `storage_path` | [x] | 2026-07-26 | 单测或手工上传 |
| 2.2 | 新增 `services/outline_parser.py`：Word Heading / Markdown `#` → outline JSON | [x] | 2026-07-26 | 给定样例文件测层级 |
| 2.3 | 新增 `services/project_assembly.py`：`refresh_project_assembled_fields(project_id)`（A 合并摘要、C 锁定大纲、D 更新） | [x] | 2026-07-26 | A/C/D 变更后 projects 列正确 |
| 2.4 | API：`GET/POST/DELETE /api/projects/{id}/sources`（按 role 过滤）；粘贴创建；文件上传 | [x] | 2026-07-26 | OpenAPI 可调 |
| 2.5 | API：`POST .../sources/{id}/reparse`；`POST .../outline/lock`（把解析结果写入 `paper_outline`） | [x] | 2026-07-26 | |
| 2.6 | API：Notebook 抓取改为创建 `BACKGROUND`+`NOTEBOOKLM` 的 source（复用现有 browser 逻辑） | [x] | 2026-07-26 | |
| 2.7 | 写作前校验 API 或 run-agent 内校验：必须有 A 定稿 + 已锁定 C | [x] | 2026-07-26 | 缺省返回 400 |
| 2.8 | 后端测试：sources CRUD、outline 解析、refresh 触发、无 notebook 旧路由 | [x] | 2026-07-26 | `pytest` 49 passed |

**Phase 2 出口**：无 UI 也能用 curl/httpx 完成 A/B/C/D 入库与定稿刷新（摘要可先占位字符串，Phase 3 接 LLM）。 ✅

---

### Phase 3 — Summarizer（gpt-4o-mini）

| # | 步骤 | 状态 | 完成日期 | 验证方式 |
|---|------|------|----------|----------|
| 3.1 | `services/summarizer.py`：LangChain + `gpt-4o-mini`；按 role 不同 prompt（A/B/D） | [x] | 2026-07-26 | |
| 3.2 | 单文档 summarize → 写 `summary_text` / `status=SUMMARIZED` | [x] | 2026-07-26 | |
| 3.3 | A 多文档：全部 SUMMARIZED 后合并进 `projects.assessment_summary`（可再调一次 LLM 合并） | [x] | 2026-07-26 | |
| 3.4 | D summarize 或短文本直写 `specific_requirements` | [x] | 2026-07-26 | |
| 3.5 | C：Header 解析为主；可选 LLM 压缩各节 `key_points` 后 lock | [x] | 2026-07-26 | Header 为主；无 Key 直存大纲文本 |
| 3.6 | 无 `OPENAI_API_KEY` 时：**直存原文为 summary**（跑通优先；不返回 503） | [x] | 2026-07-26 | 有 Key 才调 LLM |
| 3.7 | 测试：mock LLM 的 summarize + refresh；无 Key 直存 | [x] | 2026-07-26 | `pytest` 55 passed |

**Phase 3 出口**：上传真实 Assessment Word，能得到 `assessment_summary`；上传大纲 Word 能 lock `paper_outline`。 ✅（无 Key 时 summary=原文）

---

### Phase 4 — 前端 Inputs 重构

| # | 步骤 | 状态 | 完成日期 | 验证方式 |
|---|------|------|----------|----------|
| 4.1 | 项目详情 Inputs：四区 UI — A / B / C / D | [x] | 2026-07-26 | |
| 4.2 | A：多文件上传 + 粘贴；列表显示 status / 摘要预览；触发重摘要 | [x] | 2026-07-26 | |
| 4.3 | B：多条上传 + Notebook URL「更新」；列表可删 | [x] | 2026-07-26 | |
| 4.4 | C：上传 Word/md → 预览 heading 树 →「锁定大纲」；展示 `outline_locked_at` | [x] | 2026-07-26 | |
| 4.5 | D：粘贴/小文件；展示定稿 `specific_requirements` | [x] | 2026-07-26 | |
| 4.6 | 展示 projects 定稿区（只读）：assessment_summary / outline / specific | [x] | 2026-07-26 | |
| 4.7 | 移除旧「仅 Notebook + assessment 大文本框」主路径 | [x] | 2026-07-26 | |
| 4.8 | 运行 Agent 按钮：前端校验 A+C 已就绪 | [x] | 2026-07-26 | |

**Phase 4 出口**：浏览器走通四类输入与锁定，无需手调 API。 ✅

---

### Phase 5 — Agent 改造（Researcher / Writer）

| # | 步骤 | 状态 | 完成日期 | 验证方式 |
|---|------|------|----------|----------|
| 5.1 | `AcademicAgentState`：改为 A/C/D 定稿 + B summaries 列表；去掉对 notebook 单字段的依赖 | [x] | 2026-07-26 | 旧字段仍兼容 |
| 5.2 | `run-agent`：装配 context（A/C/D 自 projects，B 自 documents） | [x] | 2026-07-26 | |
| 5.3 | Researcher：按 C 各节 + A 主题生成 query（优先级 A>C>B>D） | [x] | 2026-07-26 | |
| 5.4 | Writer：**严格按 `paper_outline` 逐节**输出 Heading + 正文 | [x] | 2026-07-26 | |
| 5.5 | 导出 docx：heading 与 C 一致 | [x] | 2026-07-26 | Writer 输出同级 Markdown heading，Pandoc 导出沿用 |
| 5.6 | 更新 Agent 相关测试 | [x] | 2026-07-26 | `pytest` 56 passed |

**Phase 5 出口**：给定 A+C（+可选 B/D）能生成结构对齐的草稿。 ✅

---

### Phase 6 — 收尾与文档

| # | 步骤 | 状态 | 完成日期 | 验证方式 |
|---|------|------|----------|----------|
| 6.1 | 更新 `api_reference.md`、`implementation_status.md` | [x] | 2026-07-26 | |
| 6.2 | README 补充四类输入与 Summarizer 配置说明（你确认后再改） | [x] | 2026-07-26 | |
| 6.3 | CHANGELOG 条目（你确认后再改） | [x] | 2026-07-26 | v1.1.0 |
| 6.4 | 将本文重命名归档为 `docs/YYYYMMDD-agent-input-redesign-discussion.md`（可选） | [x] | 2026-07-26 | `20260726-agent-input-redesign-discussion.md` |

**Phase 6 出口**：文档与版本号与实现一致。 ✅（Academic Agent Platform **1.1.0**）

---

### 推荐执行顺序（一句话）

```
0 文档锁板 → 1 ORM/硬切库 → 2 Sources API + refresh → 3 Summarizer LLM
  → 4 前端四区 → 5 Agent 按大纲写 → 6 文档收尾
```

每完成一个 Phase，在本表勾选并口头/PR 同步；下 Phase 开始前确认上 Phase 出口条件已满足。

---

## 7. Summarizer LLM 选型（已确认：gpt-4o-mini）

场景：学术英文/中文作业说明、rubric、PDF/Word 摘要；要稳定 JSON/Markdown；成本可控；已在栈内有 `langchain-openai`。

### 推荐默认（性价比）

| 项 | 建议 |
|----|------|
| **主选** | **OpenAI `gpt-4o-mini`** |
| 理由 | 已在 `.env` 预留；摘要/结构化足够强；单价低；延迟可接受；LangChain 一等公民 |
| 大致费用体感 | 单份 5–20 页材料摘要通常 **分到几美分量级**（随篇幅变）；研究生个人/小团队很划算 |
| 配置 | `OPENAI_API_KEY` + `OPENAI_MODEL=gpt-4o-mini` |

### 需要更高质量时（可选升级）

| 项 | 建议 |
|----|------|
| **升级** | **OpenAI `gpt-4o`**（或其后继旗舰） |
| 适用 | Rubric 极绕、多文件矛盾多、要很稳的章节要点抽取 |
| 策略 | 默认 mini；对 `role=ASSESSMENT` 或用户勾选「高精度」再用 4o |

### 备选（按需求）

| 提供商 | 模型方向 | 何时选 |
|--------|----------|--------|
| **Anthropic** | Claude 3.5/4 Sonnet 级 | 更长上下文、对长 PDF 一次吃进更从容；需另加依赖与 Key |
| **Google** | Gemini 1.5/2.x Flash | 超长上下文、Google 生态；API 与现栈略疏 |
| **本地/兼容** | Ollama / vLLM（如 Qwen2.5、Llama） | 数据不能出机房；质量与运维自负 |

### 架构建议（实现时）

```text
SUMMARIZER_PROVIDER=openai   # 预留 anthropic|google
SUMMARIZER_MODEL=gpt-4o-mini
SUMMARIZER_MODEL_PREMIUM=gpt-4o   # 可选
```

统一经 LangChain `ChatOpenAI`（或抽象一层 `LLMFactory`），方便你只改 `.env` 换模型。

### 已确认

> **OpenAI `gpt-4o-mini` 作为唯一 Summarizer 模型。** Premium 暂不启用。

---

## 8. 锁定状态

- [x] 产品输入模型 A/B/C/D  
- [x] 优先级 A > C > B > D  
- [x] 库表：删 notebooklm；增 source_documents；projects 定稿三列 + 刷新机制  
- [x] B 由 Agent 自查 documents  
- [x] 模型 gpt-4o-mini  
- [x] 实现步骤清单（§6）可 track  
