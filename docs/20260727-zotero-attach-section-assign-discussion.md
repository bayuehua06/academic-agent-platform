# Attach 模式：按章分配已有文献 — 设计讨论

> **状态：ZA1–ZA3 已实现（ZA4/ZA5 待做）**  
> 日期：2026-07-27  
> 前提版本：ZC1–ZC2 已落地（`create` / `attach` 绑定）  
> 相关：`docs/20260727-zotero-attach-existing-collection-discussion.md`、`LiteratureConfirmPanel`、`run-agent`、Writer  
> 目标版本建议：**≥1.4.0**（与 Zotero Attach 同一版本发布，或紧随其后）

---

## 0. 已拍板结论（2026-07-27）

| # | 问题 | 结论 |
|---|------|------|
| 1 | Attach 下章向导做什么 | **保留按章向导**，但语义改为「从已 sync 文献中为本章勾选必用文献」，**不再** IEEE/ACM 检索、**不再**向 Zotero 写入新条目 |
| 2 | Create 下检索入库 | **仅 create** 保留检索 / 确认入库 / 写入 Zotero 子集合 |
| 3 | 一篇文献能否多章 | **可以**（一篇可分配给多章） |
| 4 | 未分配文献 | Writer **忽略**；UI **提示**「尚有 X 篇未分配到任何章」 |
| 5 | `selected_for_draft` | Attach 下**不再**作为章级 Writer 输入真源；章级真源 = **章节分配关联**。项目级可保留字段作兼容/弱开关，但不与分配打架 |
| 6 | 直观看到分配 | **要**：向导进度 + 每章已分配数 + 文献侧「已分配到哪些章」 |
| 7 | 分配 UI | **理想**：按 Zotero 树勾选。**MVP**：扁平列表 + **动态搜索/filter** + 显示每篇所在 **collection 路径**（根 / 子集合名） |
| 8 | 存储 | **不**复用单值 `Literature.outline_heading`；新增 **章节↔文献多对多关联** |
| 9 | Create 的 Writer 输入 | **目标**也只吃每章分配（与 Attach 同构）；**本轮 pending（ZA5）**，现网暂保留 `selected_for_draft` |
| 10 | 重新同步 | 已绑定项目可随时「重新同步」；按 `zotero_item_key` 对齐，**保留**仍存在条目上的章节分配 |
| 11 | 更换绑定 | 仅打开「更换」**不**清分配；**确认**挂接另一集合（或改 create）后才清空本地文献/分配 |

> 相对上一篇 Attach 设计（ZC）：「attach 确认入库 + `target_collection_key`」产品路径 **废止**；attach 文献宇宙以 Zotero 为唯一真源，本平台只做 **sync + 分配**。

---

## 1. 背景与动机

### 1.1 现状问题

ZC1–ZC2 已支持绑定 Group/个人已有 Collection，但 Literature 向导仍按 create 思路：

- 按章生成检索词 → IEEE/ACM 搜索 → 确认写入 Zotero
- Attach 用户本已在 Zotero 维护主体文献；再从本平台写入远端，既难与对方工作流对齐，也有脏写风险
- Sync 进来的文献没有可靠的「章归属」；Writer 目前吃的是全局 `selected_for_draft` 池，**章与文献脱节**

### 1.2 目标（一句话）

**Create = 帮你建库并检索入库；Attach = 只用你已有的库，按章勾选必引文献给 Writer。**

---

## 2. 产品概念

| 概念 | 含义 |
|------|------|
| **Binding mode** | `create` \| `attach`（已有） |
| **文献池** | 绑定集合树内 sync 到本地的 `literatures` |
| **章节分配（Section Assignment）** | 用户为某大纲 `outline_heading` 勾选的一组 `literature_id`；一篇可属多章 |
| **必用文献（must-use）** | Attach 下 Writer 写该章时**只**允许/优先使用该章已分配文献（见 §6） |
| **路径展示** | 文献在绑定树上的位置，如 `根名` 或 `根名 / 子集合名`（MVP 一层） |

---

## 3. 两种模式对比（定稿）

| | **Create** | **Attach** |
|--|------------|------------|
| 绑定后 | ensure 项目同名 + 章节子集合 | sync 已有条目，不改远端结构 |
| Literature 主操作 | 按章检索 → 勾选 → **写入 Zotero** | 按章从池中 **勾选分配**；可 sync |
| IEEE / ACM / suggest-query | **有** | **无**（UI 隐藏；API 可 400） |
| 确认入库 / import / target_collection | **有** | **禁用** |
| 章与 Zotero 子集合 | heading ≈ 子集合名 | **无关** |
| Writer 文献输入 | **现网**仍用全局 `selected_for_draft`；**目标态**与 Attach 对齐——只吃每章分配（**pending**，见 §9 / ZA5） | **仅各章分配结果**；未分配忽略 |
| 远端写 | 会 create item | **不写**（只读 sync） |

---

## 4. 用户流程

### 4.1 Attach：进入 Literature

1. 已绑定 `attach` + 有 `zotero_collection_id`。
2. 顶部：绑定摘要 +「从 Zotero 同步」+「更换绑定」。
3. **不展示**：检索库勾选、探测连通、检索本章、确认入库、入库目标下拉。
4. 展示：**按章分配向导** + 未分配提示。

### 4.2 Attach：按章分配向导

1. 章节条（与现网一致）：章名 + **已分配篇数**；可跳过（「本章不指定文献」）。
2. 当前章内容区：
   - 搜索框（标题 / 作者 / DOI / 路径名）
   - Filter：全部 / 仅未分配给任何章 / 仅本章已选 / 仅其它章已选
   - 列表每行：勾选框、标题、作者年份、**路径**、**已分配到的章标签**（若有）
3. 勾选即时或「保存本章分配」写入关联表（推荐：**改勾即保存**，避免丢状态）。
4. 向导走完条件：每章「已分配 ≥1」**或**「已标记跳过」；允许全项目零文献写作（全跳过）。

### 4.3 Attach：树形增强（非 MVP 阻塞）

若 sync 带齐子集合名称映射，前端可按：

```text
▼ 绑定根名称
    ☐ Paper A
  ▼ Subcollection Foo
      ☑ Paper B   [Introduction] [Methods]
      ☐ Paper C
```

MVP 用扁平 + 路径字符串即可；树为 ZC/ZA 后续增强。

### 4.4 Create

本轮保持现网检索入库（检索 → 写入章节子集合 → sync）。

**产品目标（pending，不阻塞 ZA1–ZA3）**：Create 入库后也应落到「章节分配」，Writer **统一**只吃每章分配结果（与 Attach 同构）。实现时可：

- 确认入库时 **自动**写入 `literature_section_assignments`（当前章 = 入库章）；或
- 入库后进入与 Attach 相同的分配向导做微调

在 ZA5 落地前，Create 的 Writer 仍走 `selected_for_draft` 全局池。

---

## 5. 数据模型

### 5.1 新增表：`literature_section_assignments`

| 列 | 类型 | 说明 |
|----|------|------|
| `id` | UUID PK | |
| `project_id` | UUID FK → projects | CASCADE |
| `literature_id` | UUID FK → literatures | CASCADE |
| `outline_heading` | String(500) | 必须与锁定大纲某 heading 一致 |
| `created_at` | timestamptz | |

约束：

- `UNIQUE (project_id, literature_id, outline_heading)` — 同章不重复勾选
- Index：`(project_id, outline_heading)`、`(project_id, literature_id)`

语义：

- **多对多**：同一 `literature_id` 可有多行不同 `outline_heading`
- Sync **删除**远端已无条目时：FK CASCADE 清掉其分配行
- 换绑 / 全量 sync 后若 literature 重建：旧分配随旧 literature 删除；**不**自动按 DOI 迁移（MVP 接受；可后续提示「请重新分配」）

### 5.2 现有字段角色调整

| 字段 | Create | Attach |
|------|--------|--------|
| `literatures.*` | 入库镜像 | sync 镜像（文献池） |
| `outline_heading`（literature 上） | 入库来源章（审计） | **可空**；不以它为 Writer 真源 |
| `selected_for_draft` | Writer 过滤真源（现网） | **弱化**：UI 可不强调；Writer **以分配表为准** |
| `zotero_subcollection_key` | 子集合 key | 用于拼路径 / 树 |

### 5.3 路径展示所需元数据

MVP 不新增表：sync / list 时用绑定根 + `list_child_collections` 得到 `key → name`，拼：

- 条目在根：`{root_name}` 或 `（根）`
- 条目在子集合：`{root_name} / {child_name}`

可选后续：`literatures.zotero_collection_path` 缓存字符串，减少每次拼装。

---

## 6. Writer / run-agent

### 6.1 Attach

1. 写作前仍可 sync（远端增删对齐）。
2. 组装 `existing_sources`（或按章分桶）时：
   - **只包含**出现在 `literature_section_assignments` 中的文献
   - 若 Writer 按章生成：该章 prompt **只注入该章分配文献**（推荐）
   - 若现网仍是「整篇一次喂全局源」：则注入 **所有曾被分配到任意章** 的文献并带 `assigned_headings: string[]`，提示模型按章使用；**更优仍是按章注入**
3. 某章零分配且未跳过：可写，但 checklist 提示「本章无指定文献」；citation_guard：该章无 ALLOWED 源则禁止编造引用（与现网零文献一致）。
4. **未分配文献不进入 ALLOWED SOURCES**。

### 6.2 Create（现网 + 目标态）

- **本轮（ZA1–ZA3）**：**不变**，继续 `selected_for_draft` 全局池。
- **目标态（ZA5，pending）**：与 Attach 对齐——Writer **只吃每章分配结果**；未分配忽略。Create 检索入库应同时（或紧随）写入分配关联，避免用户重复勾选。

### 6.3 与 citation_guard

- Attach：ALLOWED = 本章分配 ∪（若全局喂源则全体已分配）
- 禁止引用未分配条目

---

## 7. API（规格）

| Method | Path | 说明 |
|--------|------|------|
| GET | `/zotero/projects/{id}/literatures` | 扩展返回：`collection_path`、`assigned_headings[]`（可同接口或并列） |
| GET | `/projects/{id}/literature-assignments` | 可选：按章聚合 `{ heading, literature_ids[] }` |
| PUT | `/projects/{id}/literature-assignments/{heading}` | Body: `{ literature_ids: UUID[] }` **整章覆盖**该章分配（幂等） |
| POST | `/projects/{id}/literature-assignments/toggle` | 可选：单篇加减章 |
| POST | `.../literature-search*` / `.../import` / confirm 入库 | Attach 项目 → **400**（文案：请改用章节分配） |
| POST | `.../sync` | Attach / Create 均可用 |

响应示例（文献列表项增量）：

```json
{
  "id": "...",
  "title": "...",
  "collection_path": "Group Papers / Methods",
  "assigned_headings": ["Introduction", "Literature Review"],
  "selected_for_draft": true
}
```

---

## 8. 前端（Literature）

### 8.1 分流

```text
if binding_mode === "attach":
  → AssignmentWizard（同步 + 按章勾选）
else:
  → SearchConfirmWizard（现网检索入库）
```

### 8.2 分配态可视化（拍板：要直观）

| 位置 | 内容 |
|------|------|
| 章进度条 | `Introduction · 3` / `Methods · 0` / `Discussion · 跳过` |
| 当前章标题旁 | 「已选 N 篇」 |
| 文献行 | 标签：`Introduction` `Methods` |
| 页脚/旁白 | 「已同步 M 篇；未分配到任何章 K 篇（Writer 将忽略）」 |
| 可选总览 | 「按文献看分配」：每篇下列出所属章（只读或可点章跳转） |

### 8.3 MVP 交互细节

- 默认列表：全部已 sync 文献，按路径或标题排序
- 搜索 debounce 200–300ms，本地 filter 即可（池通常不大）
- 勾选 → `PUT` 本章完整 id 列表（或 toggle API）
- 「本章不指定文献」→ 清空该章分配 + 记 skipped（localStorage 可保留）

---

## 9. 非目标

- Attach 下从平台向 Zotero **新增**条目
- Attach 下 IEEE/ACM 检索
- 深层孙集合递归 sync（仍沿用一层 MVP；路径也仅一层）
- Create 模式**本轮**强制改为分配向导（目标态见 ZA5，不阻塞 Attach）
- 换绑后按 DOI **自动**恢复章节分配
- 一篇挂多个 Zotero 子集合的复杂模型

---

## 10. 实现分期

| Phase | 内容 | 状态 |
|-------|------|------|
| ZA0 | 本文拍板 | ✅ |
| ZA1 | 表 `literature_section_assignments` + PUT/GET API + literatures 带 `assigned_headings` / `collection_path` | ✅ |
| ZA2 | Attach UI：隐藏检索入库；按章分配 + 搜索/filter + 路径 + 未分配提示 | ✅ |
| ZA3 | run-agent / Writer：**attach** 按章注入；未分配不进 ALLOWED | ✅ |
| ZA4 | 树形勾选 UI；换绑后分配引导 | 待做 |
| ZA5 | **pending**：Create 也统一「Writer 只吃每章分配」；入库自动/半自动写入分配表 | 待做 |

---

## 11. 验收清单（实现后）

- [x] Attach 项目看不到检索/入库按钮；调用检索 API 返回 400
- [x] Sync 后可按章多选文献；同一篇可出现在两章的 `assigned_headings`
- [x] 未分配文献不进入 Writer ALLOWED；UI 显示未分配数量
- [x] 章进度能看出每章分配数；文献行能看出分到哪些章
- [x] Create 项目现网检索入库回归通过
- [x] 相关 pytest（assignment CRUD、attach 禁检索、writer 源过滤）

---

## 12. 下一步

- ZA1–ZA3 已落地；**升 README/CHANGELOG 到 1.4.0 需你确认后再做**。
- ZA4（树形 UI）/ ZA5（Create 也吃分配）按需排期。
