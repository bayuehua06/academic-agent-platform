# 草稿精修：节内多轮对话 + 跨节依赖 — 设计讨论

> **状态：M0–M4 已实现并入 1.3.0**  
> 日期：2026-07-27  
> 前提版本：**1.2.2**（已落地 P0–P2 单轮精修 / working / 确认 minor）  
> 相关：`docs/20260726-draft-polish-workflow-discussion.md`  
> 发布版本：**1.3.0**

本文记录产品能力的讨论结论与规格；实现以本文为准。

---

## 1. 背景与问题

### 1.1 节内多轮（问题 1）

现状（1.2.2）：单节 `polish-section` → 预览 → **Accept 或丢弃**。无法在 AI 候选上继续追问。

期望：在 **同一工作区、同一节** 内多轮讨论，满意后再 Accept；不提前产生 minor。

### 1.2 跨节依赖（问题 2）

现状：每节精修 predominantly 只看「本节正文 + 用户指令 + 文献列表」，**不读**已 Accept 的上游改写。

痛点：第 1 章把 case study 改成全新案例后，后续章节仍按旧稿改写。

| 路径 | 含义 |
|------|------|
| A. 精修时做 | 下游节精修时注入上游新内容 |
| B. 改 D + 整篇重生 | 更新全局约束后 `run-agent` |

结论：分层使用 + **Working Facts**（见 §3.3）。

### 1.3 大纲要点为硬输入（问题 3）

锁定大纲 `paper_outline[].key_points` 常已包含用户写好的内容，例如：

- case study 基本信息（公司/场景/约束）
- 四个 proposal 的名称与要点
- 必答问题编号与范围

这些是 **Authoritative Seed（权威种子）**，与 A/D 定稿同级：

| 规则 | 说明 |
|------|------|
| Writer | 必须落实 key_points 中的专有名、提案名、给定事实；**禁止另起炉灶编造冲突 case / 改名提案** |
| 精修 | 每轮提示词注入本节（及可选全文）大纲要点；改写不得抹掉或替换这些种子，除非用户指令明确要求修改 |
| 与 Facts 关系 | 大纲种子是初始真源；精修中谈定的新 case 写入 Working Facts，二者一并注入下游 |

---

## 2. 已对齐的大方向

1. **继续落在 working 内**；确认工作区才 +minor。
2. **节内多轮** = 候选线程迭代，Accept 才写 `section_overrides`。
3. **跨节**默认精修级联 + Working Facts；框架作废才回 D 重生。
4. **大纲 key_points = 硬输入**（§1.3）。
5. 引用规则服从 1.2.2 `citation_guard`；图/表锁定不变。

---

## 3. 方案规格

### 3.1 节内多轮精修

| 概念 | 说明 |
|------|------|
| **Candidate** | 当前节的 AI 候选稿（未 Accept） |
| **Turn** | 一轮用户指令 → 新 Candidate |
| **Thread** | 同一 heading 下有序 Turns（前端栈，MVP 最近 N=5） |

```
工作区当前节（或编辑区）
  → Turn1：instruction₁ + base → Candidate₁
  → Turn2：instruction₂ + Candidate₁ → Candidate₂
  → Accept(Candidateₖ) → section_overrides
```

**API**

- `POST .../polish-section` Body 增：
  - `base_markdown?`：多轮时以上一预览为底
  - `prior_instructions?`：近几轮指令（可选）
- `accept-section` 不变

**UI**：有预览时「基于预览继续精修」；采纳 / 丢弃预览 / 回退上一候选。

### 3.2 大纲 Seed 注入

- 取 `projects.paper_outline` 中与本节 heading 匹配的 `key_points`（大小写不敏感）。
- Writer 分节 user 提示：标注 `OUTLINE SEED (authoritative)`。
- 精修 system/user：同样注入；冲突时以用户本轮 instruction 为准，但仍禁止无指令时擅自改名/换 case。

### 3.3 Working Facts + 上游摘要

| 字段 | 说明 |
|------|------|
| `draft_workings.working_facts` | 自由文本：已定 case、主张、不可违背事实 |
| `draft_workings.stale_headings` | JSON 列表：上游变更后建议再精修的下游节 |

精修输入默认附带：Working Facts + **本节之前**已出现在工作区正文中的上游节摘要（截断）。

级联 UX：Accept 上游后，将后续节 heading 加入 `stale_headings`；侧栏标记「建议再精修」。

### 3.4 与整篇重生

- 局部 case/定义 → 精修级联
- 全局 D/评分框架 → 更新 D 后可 `run-agent`（警告会冲掉未固化精修）
- 大纲结构推倒 → 重锁 C + 重生

---

## 4. 与现有文档关系

| 文档 | 关系 |
|------|------|
| `20260726-draft-polish-workflow-discussion.md` | 父设计；P0–P2 ∈ 1.2.2 |
| P3 directives 落库 | Facts / 节指令确认时持久化 |
| 1.2.2 citation_guard | 每轮仍清洗 |

---

## 5. 实现顺序

| 步 | 内容 | 状态 |
|----|------|------|
| M0 | 大纲 key_points 硬输入（Writer + 精修） | ✅ 已实现 |
| M1 | 节内多轮：`base_markdown` + 前端候选栈 | ✅ 已实现 |
| M2 | `working_facts` + PATCH + 精修注入 | ✅ 已实现 |
| M3 | 上游摘要 + `stale_headings` | ✅ 已实现 |
| M4 | 确认时 Facts/directives 持久化（并入 P3） | ✅ 已实现 |

---

## 6. 开放项

1. Facts 是否改为结构化 `{key,value}[]`（MVP 自由文本）。
2. 下游 stale 是警告还是阻断 Accept（MVP：仅标记）。
3. M4 与 P3 合并排期。

---

## 7. 非目标

- 精修自动搜新文献；出版级插图；用多轮替代大纲锁定

---

## 8. 下一步

- M0–M4 与 P3 已随 **1.3.0** 发布。
- P4（严格引用阻断、指令编辑 UX 等）可另排。
