# Zotero：复用已有个人 / Group Collection — 设计讨论

> **状态：ZC1–ZC2 已实现（ZC3 打磨待做）**  
> 日期：2026-07-27  
> 前提版本：**1.3.1**  
> 相关：`docs/20260726-literature-zotero-search-discussion.md`、`zotero_service.py`、`literature_workflow.py`  
> 目标版本建议：**≥1.4.0**（用户确认后再升 README/CHANGELOG）  
> **后续修正**：Attach 下「按章检索 + `target_collection_key` 入库」已废止，改为「只 sync + 按章分配」——见 `docs/20260727-zotero-attach-section-assign-discussion.md`。

---

## 0. 已拍板结论（2026-07-27）

| # | 问题 | 结论 |
|---|------|------|
| 1 | 怎么选库 / 集合 | 进入 Literature 时，**列出当前 Key 能访问的全部 Collection**（个人库 + 我所在 Group）。用户 **二选一**：选一个已有 Collection，或 **完全新建**（新建 = 现网逻辑：项目同名 + 章节子集合）。 |
| 1b | 选已有时文献范围 | **只能选定一个** Collection 作为本项目唯一范围。绑定后：把该集合内**已有文献全部拉入**本地作为已有；之后新入库 / sync / 写作文献范围都限定在这一棵集合内。 |
| 2 | Attach 能否放到根 | **可以**（与 Zotero 一致：条目可直接属于根 Collection）。 |
| 3 | 与「本章」向导 | 使用已有 Collection 时：**章与子集合完全解耦**——章只管检索词/跳过；入库目标子集合（或根）由用户自选，不受大纲 heading 限制。 |
| 4 | Tags / 深层嵌套 / 多集合挂载 | **不做**。 |

---

## 1. 背景与动机

### 1.1 现状（1.3.x）

| 行为 | 说明 |
|------|------|
| 顶层 Collection | 按**项目标题**创建或复用同名顶层集合 |
| 子集合 | 按锁定大纲 **heading** 自动建一层子集合 |
| 入库 | 确认文献时写入「当前章」对应子集合 |
| Sync | `zotero_collection_id`（根）+ **直接子集合** |
| 库类型 | 全局 `.env`：单一 `ZOTERO_LIBRARY_TYPE` + `ZOTERO_LIBRARY_ID` |

### 1.2 痛点

协作 Group / 个人大库里已有大量文献与分类；再为每个作业建「项目同名 + 章节子树」会重复入库、无法复用组内结构，且可能污染对方子树。

### 1.3 目标（一句话）

Literature 入口统一：**选一个已有 Collection，或新建一套**。项目始终只绑定 **一个** Collection 作为文献宇宙；Attach 时复用其中全部已有条目，且不强制章节子集合结构。

---

## 2. 产品概念

| 概念 | 含义 |
|------|------|
| **Binding mode** | `create` \| `attach` |
| **Bound collection** | 本项目唯一文献范围（一个 Zotero Collection key + 其所在 library） |
| **Create** | 新建项目同名根集合 + 按大纲 heading 自动子集合（现网） |
| **Attach** | 挂接已有集合；不自动建章节子树；入库目标 = 用户选的子集合 **或根** |
| **Library** | 个人 user 库，或用户 Key 可访问的某个 group 库 |

---

## 3. 两种模式对比

| | **Create** | **Attach** |
|--|------------|------------|
| 入口选择 | 「完全新建」 | 从可访问列表点选一个已有 Collection |
| 根集合 | 按项目标题 ensure/创建 | 用户指定的已有 Collection |
| 子集合 | 按大纲 heading **自动 ensure** | **不**按大纲自动建/改 |
| 首次绑定后 | 空树或仅结构 | **拉取该集合内已有文献** → 本地镜像 |
| 确认入库目标 | 隐式 = 当前章同名子集合 | **手选**：某子集合 **或根** |
| 章与子集合 | 绑定（heading ≈ 子集合名） | **完全解耦** |
| 项目文献范围 | 始终这一棵 | 始终这一棵（仅一个） |
| Sync | 该集合范围内 | 同左：范围内全量对齐 |

---

## 4. 用户流程（定稿）

### 4.1 进入 Literature：绑定选择

1. 若项目尚未绑定（无 `zotero_collection_id` / 未确认 mode）：展示绑定面板。  
2. 调用 API：**列出可访问 Collections**（个人库顶层 + 各 Group 库顶层；展示库名/类型以免混淆）。  
3. 用户操作：  
   - **选已有** → `mode=attach`，写入 `library_type` + `library_id` + `collection_key`，立即 **sync 拉全量已有文献**；或  
   - **完全新建** → `mode=create`，走现网 `ensure-structure`（项目同名 + 章节子集合）。  
4. 已绑定后：Literature 主流程可用；提供「更换绑定」（强警告：本地镜像将按新集合重 sync）。

### 4.2 Attach：检索与入库

1. 按章检索 / 跳过（章 **只** 影响检索词与向导进度）。  
2. 确认入库时：**必选** `target_collection_key`：  
   - 根 Collection，或  
   - 该根下的某个**直接**子集合（MVP 一层；与「不做深层」一致）。  
3. 写入 Zotero 到所选 key；本地记 `zotero_subcollection_key`（根则空或 = 根 key，实现时统一约定）。  
4. `outline_heading` 可仍记「向导当前章」作审计，**不**用于决定写入哪个子集合。

### 4.3 Create

与现网相同：confirm 用 `outline_heading` → 章子集合；可 `ensure-structure`。

---

## 5. 数据与 API（规格）

### 5.1 项目字段

| 字段 | 说明 |
|------|------|
| `zotero_collection_id` | 绑定的 Collection key（已有） |
| `zotero_binding_mode` | `create` \| `attach` |
| `zotero_library_type` | `user` \| `group`（**项目级**，因列表跨个人+组） |
| `zotero_library_id` | 对应库 id（**项目级**） |

> 拍板含义：列表必须跨个人与 Group → 绑定必须记住「在哪个 library」。全局 `.env` 的 `ZOTERO_API_KEY` 仍共用；`ZOTERO_LIBRARY_*` 可作为默认/回退，但 **Attach/跨库以项目字段为准**。

### 5.2 API

| Method | Path | 说明 |
|--------|------|------|
| GET | `/zotero/accessible-collections` | 聚合：user + 可访问 groups 的顶层 Collections（含 library 元数据） |
| GET | `/zotero/collections/{key}/children?library_type=&library_id=` | 直接子集合（Attach 入库下拉；含「可用根」由前端另选项） |
| POST | `/projects/{id}/zotero-binding` | Body: `{ mode: create\|attach, collection_key?, library_type?, library_id? }`；attach 后触发全量 sync |
| POST | `.../ensure-structure` | **仅 create**；attach → 400 |
| POST | `.../literature-search/{run_id}/confirm` | attach 时 **必填** `target_collection_key`（可为根 key） |
| POST | `.../zotero/.../import` | 同上 |
| POST | `.../zotero/.../sync` | 按项目 library + 绑定集合拉齐本地 |

---

## 6. Sync / 已有文献 / Writer

| 点 | 规格 |
|----|------|
| **范围** | 项目绑定的 **唯一** Collection：根内条目 + **直接子集合**内条目（与现网一层一致；「所有已有」指该一层树内全部条目，不扫更深嵌套） |
| Attach 首次绑定 | 立即 sync → 本地出现已有文献，可供勾选 `selected_for_draft` |
| 判重 `already_exists` | **仅在该绑定集合树内**；不扩展到整个 Group 其它兄弟集合 |
| run-agent | sync 后取选中文献；不依赖子集合名 = 章名 |
| 删项目 | **不删**远端 Collection |

> 若协作库子树很深、文献只在孙集合：MVP 扫不到。接受为非目标；需要时可另开「递归 sync」议题。

---

## 7. 权限与安全

- 列表/绑定时用当前 Key 探测；无读权限不展示或不可选。  
- 无写权限的 Group：可绑只读浏览 + sync，但入库按钮禁用并提示。  
- Attach 确认文案：不会自动改对方子树；但会向所选（子）集合 **写入新条目**，且会把该树内文献镜像到本项目。

---

## 8. 非目标

- Tags / 深层嵌套递归 sync  
- 一篇挂多个子集合  
- 同时绑定多个 Collection  
- Per-user Zotero OAuth（仍共用 `.env` API Key 的可见范围）  
- Attach ↔ Create 自动搬迁复制远端条目  

---

## 9. 仍可后续打磨（非阻塞）

1. 更换绑定时的本地镜像策略文案与二次确认。  
2. Attach 下「上次选用的目标子集合」记忆（localStorage）。  
3. 只读 Group 的只读态 UI。  
4. 列表性能：Group / Collection 很多时的分页或搜索。

---

## 10. 实现分期

| Phase | 内容 | 状态 |
|-------|------|------|
| ZC0 | 讨论拍板（本文 §0） | ✅ |
| ZC1 | `accessible-collections` + 项目级 library 字段 + binding API；create/attach 分流；attach 禁 ensure | ✅ |
| ZC2 | attach 首次全量 sync；confirm 必填 `target_collection_key`（含根）；向导 UI | ✅ |
| ZC3 | 只读提示、换绑警告、默认目标记忆 | 部分（换绑确认 + localStorage 记忆目标；只读 Group UI 仍待） |

---

## 11. 下一步

- 实现已落地；**升 README/CHANGELOG 到 1.4.0 需你确认后再做**。  
- 若你希望「已有文献」包含**任意深度**子集合，再说一声，再把 §6 从「一层」改成「递归」。
