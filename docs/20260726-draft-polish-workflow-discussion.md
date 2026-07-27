# 草稿上传精修工作流 — 设计讨论

> **状态：P0–P3 已实现并入 1.3.0 · P4 未开始**  
> （P3：confirm 时 References 重建 + directives/Facts 落库 + run-agent 注入；与 `20260727` M4 一并完成）  
> **扩展规划**：节内多轮 + 跨节依赖 → `docs/20260727-draft-polish-multiturn-cross-section-discussion.md`（M0–M4 已入 **1.3.0**）  
> 日期：2026-07-26（本文）；扩展 2026-07-27  
> 版本对齐：P0–P2 ∈ **1.2.2**；P3 + 多轮/跨节 ∈ **1.3.0**  
> 相关：Writer / D 约束（1.2.0）、导出 APA（1.2.1）、引用护栏（1.2.2）、Zotero 真源文献

本文记录「用户下载 Word → 手工改 → 上传 → 分节 AI 精修 → 确认小版本」的产品与技术规格。实现前以本文为准；落地后按 `.cursorrules` 归档并更新核心文档。

---

## 1. 目标与原则

**目标**：在保留用户手工修改的前提下，按章节用 LLM（默认 mini）精修，并把章节级要求记下来，供日后整篇重生使用。

**原则**：

1. **上传稿为工作区真源**；AI 不得在未确认时覆盖已发布版本。  
2. **引用只许来自项目 Zotero / 本地已确认库**；模型不可发明文献。  
3. **图/表块不参与改写**（锁定）。  
4. **小版本只在「确认工作区」时产生**；精修过程在工作区内迭代。  
5. **章节指令独立存储**（`section_directives`），不塞进现有 D 定稿文本。

---

## 2. 已锁定决策

| # | 问题 | 决定 |
|---|------|------|
| 1 | 版本何时 +minor | **仅「确认工作区」** 时生成下一小版本（如 9.1、9.2）。上传进入工作区；节精修在工作区内预览/采纳，**不**每采纳一节就 +0.1。 |
| 2 | 指令存哪 | **独立 `section_directives`**（按 heading + 条目）；不写入 `specific_requirements` 正文。整篇 `run-agent` 时按节注入对应 directive。 |
| 3 | References / 引用 | 文内引用与列表均以 **Zotero 已入库文献** 为准。提示词可写「请引用 XXX（须在库中）」；不在库则先走 Literature 入库。确认小版本时 **按文内实际引用重建 References**。 |
| 4 | 图/表 | **含图/表的块锁定不改**；精修跳过或整段保留原文。 |
| 5 | 模型 | 节精修默认 `OPENAI_MODEL`（mini）；可后续加 `OPENAI_POLISH_MODEL`。 |
| 6 | Diff | 展示工作区全文，**按节高亮相对 base（及可选相对上一确认小版本）** 的增删。 |
| 7 | Major 版本 | 本阶段以 **minor 链**为主（9.1、9.2…）。若未来需要「里程碑 major=10」，可作为显式「晋升 major」动作；**MVP 不强制**每次确认都跳 major。 |

### 版本语义（拍板后的理解）

```
v9          ← 已确认版本（Agent 或既往确认）
  └─ 下载 Word → 手工改 → 上传（指定 base=v9）
        → 进入 working（未编号或标记 working）
        → 分节精修（工作区内多次预览/采纳）
        →【确认】→ v9.1（写入 draft_versions）
  └─ 打开 v9.1 → 再改 / 再上传或基于 9.1 开工作区
        → 精修…
        →【确认】→ v9.2
```

说明：用户原述「确认之后是 9.1」——即 **一次完整工作区周期确认 = 一个 minor**，不是「每改一节一个 minor」。

---

## 3. 核心概念

| 概念 | 说明 |
|------|------|
| **Base version** | 上传或「基于此版开启精修」时选定的已确认版本（如 v9）。 |
| **Working copy** | 未确认的编辑态：正文 Markdown、分节覆盖、待写入指令。每项目至多一个 active working（MVP）。 |
| **Section polish** | 对单节：用户指令 + 可选勾选文献 → LLM 改写 → 预览 → 采纳/丢弃。 |
| **Section directive** | 持久化的章节备忘；确认工作区时落库；整篇重生时注入该节 Writer 提示。 |
| **Confirm** | 工作区拼装 → 校验警告 → 新 minor 版本 + 重建 References + 落盘 directives。 |

---

## 4. 数据模型（规划）

> 实现时可微调列名；以落地时 `database_schema.md` 为准。

### 4.1 `draft_versions` 扩展

| 列 | 说明 |
|----|------|
| `version_number` | 保持 INT 排序键（全局递增），或改为 major 用 INT、另存 display |
| `major` | INT，如 9 |
| `minor` | INT，如 0=「纯 major 展示为 9」；1→展示 `9.1` |
| `display_label` | 缓存 `"9.1"`（可选） |
| `parent_version_id` | FK，血缘 |
| `base_version_id` | 本次工作区所基于的版本 |
| `source_type` | 增：`MANUAL_IMPORT` \| `POLISH_CONFIRM` \| `AGENT_GEN` |

展示规则：`minor==0` → `v{major}`；否则 `v{major}.{minor}`。

### 4.2 `draft_workings`（或项目上 JSON 工作区）

| 列 | 说明 |
|----|------|
| `project_id` | |
| `base_version_id` | |
| `content_markdown` | 当前工作区全文 |
| `section_overrides` | JSONB：`{ heading: markdown }` 已采纳精修 |
| `status` | `ACTIVE` \| `CONFIRMED` \| `DISCARDED` |
| `updated_at` | |

MVP 也可用「单行 working + 确认后清掉」简化。

### 4.3 `section_directives`（新表或 projects JSONB）

推荐 **表**（便于审计与按节查询）：

| 列 | 说明 |
|----|------|
| `id` | UUID |
| `project_id` | |
| `outline_heading` | 与锁定大纲 heading 对齐 |
| `directive_text` | 短指令（英文/原文，模板化） |
| `source_working_id` / `confirmed_version_id` | 来源 |
| `created_at` | |
| `active` | bool，可软删 |

模板示例：

```text
[Section: Literature Review] When regenerating this section, emphasize platformization debates; cite only library sources tagged for this chapter unless user lists otherwise.
```

整篇 `run-agent`：Writer 分节时附加该 heading 下所有 `active` directives。

### 4.4 图/表锁定标记

解析工作区 MD 时识别：

- Markdown 表（`| ... |`）
- 占位：`[Figure N: ...]` / `![...](...)` / Word 转入的图注行

精修输入：将该节拆成「可改段落」与「锁定块」；模型只收可改部分，输出后按锚点拼回。

---

## 5. 用户流程（UI）

1. **Draft 顶栏**：下载 / **精修（无上传，基于选中版本）** / 上传 Word；上传或精修均指定 base。  
2. 进入 **精修工作区**（非立刻 9.1）。  
3. **Diff 视图**：左/上节列表；主区显示工作区正文，高亮相对 base 的变化；节状态：未改 / 已精修 / 含锁定块。  
4. **选节 → 精修面板**：  
   - 指令输入（多次可追加）  
   - 可选：从 Zotero 镜像勾选「本次必须考虑的文献」  
   - 「生成预览」→ 并排原文/新稿 → 采纳 / 重试 / 放弃  
   - 采纳时：**追加一条 section_directive（工作区暂存）**；确认时才持久化（或采纳即持久化，确认时绑定 version——实现二选一，推荐 **确认时持久化**，避免弃稿脏数据）  
5. **确认工作区** → 新 minor（9.1）+ References 重建 + directives 落库。  
6. 基于 9.1 再開工作区 → 确认 → 9.2。

---

## 6. API 草案（实现期细化）

| Method | Path | 说明 |
|--------|------|------|
| POST | `/drafts/import-docx` | 扩展：`base_version_id` 必填（或 query）；进入 working，不直接当最终 minor |
| GET | `/projects/{id}/draft-working` | 当前工作区 + diff meta |
| DELETE | `/projects/{id}/draft-working` | 丢弃工作区 |
| POST | `/projects/{id}/draft-working/polish-section` | Body: heading, instruction, literature_ids? → preview markdown |
| POST | `/projects/{id}/draft-working/accept-section` | 采纳预览写入 overrides + 暂存 directive |
| POST | `/projects/{id}/draft-working/confirm` | 拼装 → minor 版本 + References + 持久化 directives |
| GET | `/projects/{id}/section-directives` | 列表 |
| PATCH/DELETE | `.../section-directives/{id}` | 编辑/停用 |

现有 `import-docx` 行为需 **迁移**：默认改为「开工作区」；若需兼容「直接当新版本」，用 flag `confirm_immediately`（默认 false）。

---

## 7. 引用与 References

**改写时**：

- Context 只注入：本项目已确认文献（可过滤本章 + 用户勾选）。  
- System：`Cite ONLY from the provided source list using APA in-text. Do not invent sources.`  
- 用户说「引用一下 Kim et al.」→ 若库中能解析到则放入 must-use；否则返回 400/提示先入库。

**确认时**：

1. 扫描终稿文内 `(Author, year)` / Author (year)。  
2. 匹配 Zotero 镜像 → 生成 `apa_references_block`。  
3. 未匹配引用 → **警告列表**（MVP 可仍允许确认，但 UI 红标；或设置 `strict_citations`）。  
4. 覆盖工作区/正文末尾旧 References 段（与 1.2.1 导出逻辑一致）。

---

## 8. 图/表策略

- 检测锁定块 → 精修 API 不把其送入「待改正文」，或标注 `<<LOCKED_FIGURE_1>>` 要求原样返回。  
- UI 显示锁图标；用户无法对该块单独「改写」。  
- **不生成**新图文件；不自动绘表（除非未来单独立项 Markdown 表生成）。

---

## 9. 与现有模块关系

| 模块 | 关系 |
|------|------|
| Writer / run-agent | 读取 `section_directives` 按节注入；D 仍管全局约束 |
| Zotero sync | 精修前建议可点 sync；引用列表来自镜像 |
| 导出 APA docx | 确认后的 minor 与现网一致 |
| Inputs D | **不**因精修改写 `specific_requirements` |

---

## 10. 实现分期（建议）

| Phase | 内容 | 出口 |
|-------|------|------|
| **P0** | 版本 major/minor 字段 + 展示；import 绑定 `base_version_id`；工作区 CRUD；确认 → 9.1 | 上传→确认出小版本，无 AI |
| **P1** | 按节 diff UI；节拆分与图/表锁定检测 | 能看清相对 base 的变化 |
| **P2** | polish-section + accept（mini）+ 暂存 directives | 单节精修闭环 |
| **P3** | confirm 时 References 重建 + directives 持久化；run-agent 读 directives | ✅ 已实现（含 M4 Facts） |
| **P4** | 指令/文献勾选 UX、严格引用警告、弃稿清理 | 未开始 |

测试：P0/P2/P3 须补 `backend/tests`（API 契约变更强制）。

---

## 11. 开放项（实现前可再定，不阻塞 P0）

1. 每项目是否允许并行多个 working（MVP：**仅一个**）。  
2. 确认失败（引用全不匹配）是阻断还是警告。  
3. `version_number` INT 与 major/minor 双轨如何排序列表。  
4. 大纲 heading 与 Word 标题漂移时的手动映射 UI（P1 可先「最长匹配 + 未匹配节整节锁定」）。

---

## 12. 非目标（本设计不做）

- 精修流程里自动上网搜新文献  
- LLM 生成图片 / 复杂出版级三线表  
- 每次采纳一节就自动 +0.1  
- 把章节指令合并进 D 定稿大文本  

---

## 13. 下一步

- **P0 已完成**：工作区 + major/minor + 确认小版本（**1.2.2**）。  
- **P1 已完成**：分节 diff、图/表锁定检测、行级高亮（**1.2.2**）。  
- **P2 已完成**：`polish-section` / `accept-section`、暂存 `pending_directives`（**1.2.2**）。  
- **P3 已完成**：confirm References 重建 + `section_directives` / `confirmed_facts` 落库 + Writer 注入（与 **M4** 合并，**1.3.0**）。  
- 下一阶段可选：**P4** UX 打磨。
