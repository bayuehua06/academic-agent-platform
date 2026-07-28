# Writer 引用证据：可核对内容 / 链接取文 — 设计讨论

> **状态：CE1–CE4 已实现**  
> 日期：2026-07-27  
> 前提版本：1.3.x Writer + citation_guard；Attach 章节分配（ZA）已落地  
> 相关：`citation_guard.py`、`writer.py`、`literature_assignments.py`、`docs/openai-llm-usage.md`  
> 目标版本：**1.4.x**

---

## 0. 待拍板结论（草案，请确认）

| # | 问题 | 建议结论 |
|---|------|----------|
| 1 | 要不要做 | **要**。仅「库内署名合法」不够；主张须能被可核对证据支撑 |
| 2 | 模型能否自己上网 | **不能裸做**；须后端提供取文/证据卡，再喂 Writer（可选用 tool-calling，但取文实现在我们侧） |
| 3 | MVP 证据源 | **优先 abstract**（本地 literatures + 必要时 Crossref/OpenAlex 补全） |
| 4 | 无证据时怎么办 | **禁止捏造发现/结果**；可仅作「该工作存在」级提及，或该条本轮不引实质主张 |
| 5 | 与 citation_guard 关系 | **并存**：guard = 署名/年份必须在 ALLOWED；证据卡 = 内容主张的依据 |
| 6 | 全文 PDF | **非 MVP**（Zotero 附件 / Unpaywall 后续） |
| 7 | 精修（polish） | 与 Writer **同规则**：本章证据卡进 polish prompt |

---

## 1. 背景与动机

### 1.1 现状

| 层 | 行为 |
|----|------|
| ALLOWED SOURCES | 基本只有题名 / 作者 / 年 / DOI（`format_allowed_sources_block` **未注入 abstract**） |
| citation_guard | 剔除「不在库」的 (Author, Year)；**不验证**句子是否真属于该文 |
| literatures | 常有 `abstract`（Zotero sync / 检索入库），但 Writer 基本没用上 |
| 模型 | 用合法署名 + 训练知识写「看起来像引用」的句子 → **虚假但越库检测过不了关** |

### 1.2 目标（一句话）

**引用 = 库内合法署名 + 可核对证据（至少摘要级）；无证据则不得编造该文的具体发现。**

### 1.3 非目标（本设计）

- 保证每篇都能拿到出版社全文（付费墙无法普遍打破）
- 自动法律合规爬虫绕过登录墙
- 用 browsing 替代本地证据管线（可选增强，不依赖）
- 把「页码级精确定位」做成硬验收（MVP 不做）

---

## 2. 能力现实（为何不「让模型自己查」）

| 路径 | 结论 |
|------|------|
| 裸 Chat Completions | **不会**自动打开 DOI/落地页 |
| Tool / function calling | **可以**：模型请求 `fetch_evidence(doi)`，由**我们的服务**取文再回填 |
| 官方 browsing 产品能力 | 与当前自建 Writer 图不是一键开关；单独接、成本/可控性另议 |

**拍板建议**：证据获取是 **平台服务**（确定性、可缓存、可测）；Writer 只消费「证据卡」，不假装自己会上网。

---

## 3. 产品概念

| 概念 | 含义 |
|------|------|
| **Evidence card（证据卡）** | 单篇文献的可核对文本包：元数据 + abstract/摘录 + 来源标记 + 新鲜度 |
| **Evidence tier** | `full` / `abstract` / `metadata_only` — 决定允许写到什么粒度 |
| **Grounded citation** | 文内引用所支撑的主张，须能被该文证据卡内容合理支撑 |
| **Enrichment** | 本地缺 abstract 时，用 DOI 调开放 API / 落地页补全并写回缓存 |

### 3.1 Evidence tier → 写作许可（草案）

| Tier | 有什么 | 允许 | 禁止 |
|------|--------|------|------|
| `abstract` 或更高 | 可用摘要/摘录 | 综述该文目标、方法要点、摘要中明确的结论 | 编造摘要未提及的数据/实验细节 |
| `metadata_only` | 仅题名作者年 DOI | 「X (year) 讨论了主题 Y」级定位；或本轮**不引**该条做实质主张 | 具体发现、统计结果、方法步骤 |
| 无 DOI 且无 abstract | 最弱 | 同 metadata_only；UI/日志标黄 | 同上 |

---

## 4. 端到端流程

```text
run-agent / polish
  → 解析本章 sources（attach=分配；create=selected_for_draft）
  → build_evidence_cards(sources)
       ├─ 本地 abstract？ → tier=abstract
       ├─ 否则有 DOI？ → enrich(doi) → 写回 literatures.abstract（可选）→ tier=abstract|metadata_only
       └─ 否则 → tier=metadata_only
  → format_allowed_sources_block + format_evidence_block → Writer / Polish
  → 成稿后：既有 citation_guard（署名）
  → （CE3 可选）轻量「主张-证据」抽检 / 警告，不做硬删句除非明确误引署名
```

---

## 4.1 关键证据块选择（确定性 / 低成本优先）

> 目标：在不让模型“自己猜内容”的前提下，从可用证据文本里稳定挑出最能支撑本节主张的片段。

### 4.1.1 证据文本来源优先级

对同一条 literature source，按以下顺序准备 evidence 文本（用于后续 chunk 筛选）：

1. **URL / landing page（不是 PDF）**：抽取落地页主栏文本（main content），视为“全文资源”，用于 chunk 筛选。
2. **Zotero PDF / 可解析附件（后续 CE4）**：PDF 转文本后视为“全文资源”，用于 chunk 筛选。
3. **本地 abstract**：作为摘要证据（abstract evidence）。
4. **仅 metadata（title/author/year/doi）**：作为最低证据层（metadata_only）。

### 4.1.2 chunking

- 将全文资源（URL 抽取文本 / PDF 文本）按段落或固定长度切成 chunks（带少量重叠）。
- 设定每篇 literature 最多可注入的 chunks 数：`max_chunks_per_source`（例如 3~6）。

### 4.1.3 section query（用于“挑证据”）

每个写作 section 构造 query，来源包括：
- section `heading`
- section `key_points` 中的关键词（表格框架只用于保结构，表内“中文草稿”不得原样当成证据关键词；仍会被模型翻译/改写成英文）
- must-include / checklist 中的硬关键词（可选）

### 4.1.4 chunk 打分与选择（关键词检索）

对每个 chunk 计算确定性分数（不依赖向量检索，低成本）：
- 关键词命中数量（含标题词/方法词/指标词/术语词）
- 简单模糊匹配（大小写/空格差异；可选规则同义词）

选择分数 Top-K chunks 注入证据卡，且总字符数/总 token 受控：
- `max_chars_per_section_evidence`（例如几千到一两万字符，按 token 风险微调）

> 可配置性（建议 CE1 就支持）：所有阈值与预算都通过配置读取，而不是写死在代码里。
> 例如：`max_chunks_per_source`、`max_chars_per_section_evidence`、`keyword_top_n`、`topk`、`best_score_min`、`fallback_mode`（见 §13）。

### 4.1.5 必须的回退链（避免“关键词筛选找不到”）

当关键词检索无法选出足够的证据 chunks（例如 Top-K 为空、或最高分低于阈值）时，按以下回退：

1. **如果本地 abstract 存在**：退回 `tier=abstract`，用 abstract 作为 evidence 注入。
2. **否则如果 DOI enrich 可用（CE2）**：先 enrich abstract，失败则继续降级。
3. **仍失败**：退回 `tier=metadata_only`，只允许“主题定位句”，禁止方法/结果/具体数字等实质发现主张。

同时对 URL：
- 若 URL 落地页抽取/抓取失败或抽取文本为空：同样回退到 abstract（若有），否则 metadata_only。

---

## 5. 数据与缓存

### 5.1 复用现有

- `literatures.abstract`：主缓存字段（已有）
- `literatures.doi`：enrich 主键

### 5.2 建议新增（可 CE2 再加）

| 字段 | 说明 |
|------|------|
| `evidence_tier` | 可选缓存，避免每次推断 |
| `evidence_fetched_at` | 上次 enrich 时间 |
| `evidence_source` | `zotero` \| `crossref` \| `openalex` \| `landing` \| `none` |
| `url` / `landing_url` | 若 Zotero/检索有链接可存（现网可能没有，CE2 再补） |

当前实现：已新增 `evidence_tier` / `evidence_source` / `evidence_fetched_at` / `landing_url`，并在运行时组装证据卡；补全成功会写回 `abstract` 与 evidence 元数据。

### 5.3 证据卡结构（内存 / 提示）

```json
{
  "title": "...",
  "authors": ["..."],
  "year": "2020",
  "doi": "10....",
  "tier": "abstract",
  "evidence_source": "zotero",
  "abstract": "……（截断至 N 字符）",
  "assigned_headings": ["Introduction"]
}
```

---

## 6. Writer / 提示词

### 6.1 ALLOWED SOURCES（加强）

在现有署名行之外，每条增加：

- `tier=…`
- `Abstract/evidence: …`（无则 `NONE — metadata only; do not invent findings`）

### 6.2 HARD 规则（新增文案）

- Cite ONLY ALLOWED SOURCES（不变）。
- **GROUNDING**：实质主张（发现、结果、方法细节）必须能被该条 evidence 文本支持。
- `tier=metadata_only`：不得捏造该文具体结论；宁可少引或只写主题定位句。
- 禁止用训练记忆「补全」库内论文未提供的内容。

### 6.3 按章注入

与 Attach 分配一致：本章只带本章 sources 的证据卡（create 暂仍全局池，ZA5 后对齐）。

### 6.4 精修

`draft_polish` 使用同一 `build_evidence_cards` + 同一 grounding 规则。

---

## 7. Enrichment 服务（CE2）

### 7.1 提供方优先级（建议）

1. 本地 `literatures.abstract`（Zotero）
2. **Crossref** / **OpenAlex**（DOI → abstract，开放、稳）
3. 可选：DOI 内容协商 / 落地页 HTML 主文本抽取（失败率高，限时、限长）
4. 后续：Unpaywall + PDF 文本（CE4）

### 7.2 策略

- 超时短（如 3–5s/篇）、并发有上限（如本章最多 8 篇 enrich）
- 失败 → `metadata_only`，**不阻断**写作
- 成功写回 `abstract`，下次免打
- 记录 `evidence_source`（若有列）或仅日志

### 7.3 安全与礼貌

- 只请求 DOI / 已知学术 API；User-Agent 标明学术工具
- 不存 cookie、不破解登录墙
- 对 HTML 只抽主栏文本并硬截断（如 4k–8k 字符）

---

## 8. 与 citation_guard 的分工

| 检查 | 负责 | 时机 |
|------|------|------|
| (Author, Year) 是否在库 | citation_guard | 写后 sanitize / verify |
| 主张是否有摘要依据 | 提示约束为主；CE3 可选抽检 | 写时 + 可选写后警告 |
| 无证据仍写了具体数字 | CE3 启发式警告（非 MVP 硬拦） | 写后 |

**MVP 不**做「逐句 NLI 对齐摘要」硬校验（贵、脆）；先靠提示 + tier 规则把胡编空间压下去。

---

## 9. API / 模块（实现落点）

| 模块 | 职责 |
|------|------|
| `services/evidence_cards.py`（新） | `build_evidence_cards`、`format_evidence_block`、tier 推断 |
| `services/evidence_enrichment.py`（CE2） | DOI → Crossref/OpenAlex/landing |
| `citation_guard.format_allowed_sources_block` | 扩展为含 abstract/tier，或改为调用 evidence formatter |
| `projects.run-agent` / `draft_polish` | 写作前 build cards |
| 可选 `POST .../literatures/{id}/enrich-evidence` | 手动补摘要（调试/UI） |

---

## 10. 实现分期

| Phase | 内容 | 状态 |
|-------|------|------|
| CE0 | 本文讨论拍板 | 待确认 |
| **CE1** | 本地 abstract 注入 ALLOWED；grounding 提示；metadata_only 禁捏造发现；单测 formatter | 已完成 |
| **CE2** | DOI enrich（Crossref/OpenAlex）写回 abstract；写作前批量补全；超时降级 | 已完成 |
| CE3 | Literature UI 显示 tier / 缺摘要；写后轻量 warning 仍保持可选未启用 | 部分完成 |
| CE4 | Zotero PDF 附件 / Unpaywall 全文片段 | 已完成 |

---

## 11. 验收清单（CE1）

- [ ] Writer 提示中每条 ALLOWED 含 abstract 或明确 `metadata_only`
- [ ] 无 abstract 时系统提示含「不得编造该文发现」
- [ ] create / attach 组装 sources 仍带 `abstract` 字段且 formatter 使用之
- [ ] citation_guard 署名规则回归不破
- [ ] pytest：formatter 快照 / tier 推断

## 12. 验收清单（CE2）

- [ ] 缺 abstract + 有 DOI → enrich 后 abstract 非空或明确失败为 metadata_only
- [ ] enrich 失败不导致 run-agent 500
- [ ] 二次写作命中本地缓存，不再重复打外部 API（同 abstract 已存在）

---

## 13. 开放问题（请你拍板）

1. **CE1 是否立刻做**（只注入本地摘要，不 enrich）？建议：**是**。  
2. **无摘要时**：严格「禁止实质引用该条」还是允许「主题定位句」？建议：**允许主题定位，禁止发现/数据**。  
3. **enrich 写回 DB**：默认写回 `literatures.abstract`？建议：**写回**（对用户也有价值）。  
4. **CE2 提供方**：先 Crossref + OpenAlex 是否足够？建议：**够 MVP**。  
5. **是否上 tool-calling 让模型按需取文**，还是写作前批量 enrich？建议：MVP **批量前置**；按需 tool 作 CE3+ 优化（省 token）。
6. **chunk 选择阈值**：你希望“关键词筛选找不到”触发回退的判据是：
   - A. Top-K 为空 / 总分为 0
   - B. Top-1 低于阈值（例如命中数 < 2 或分数 < X）
   - C. 两者都要（更严格，默认）

---

## 14. 下一步

- CE1–CE4 已落地；README/CHANGELOG 仍等你确认实现后再改。  
- 可选后续：写后 grounding 抽检（CE3 剩余）、PDF 文本本地缓存列、按需 tool-calling。
