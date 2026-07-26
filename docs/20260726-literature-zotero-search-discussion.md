# 文献检索 + Zotero — 设计归档

> **状态：主路径已完成（Z0–Z4、Z6）· Z5（LLM 造词）待续**  
> 日期：2026-07-26 · 归档同日  
> 入口：[AUT Library](https://library.aut.ac.nz/) → Databases → IEEE Xplore → AU 登录  
> 版本对齐：**v1.1.1**（ACM/多库见 **v1.1.2**；Z5 / Writer LLM 见 **v1.2.0**）

本文为实现规格归档。大纲在业务上基本不再变更，故不做复杂的大纲–集合迁移。

---

## 1. 目标与原则

**目标**：按论文大纲**逐章**从 IEEE（经 AUT）检索 → **人工确认** → 写入 **Zotero（项目 Collection + 章节 Subcollection）** 并镜像本地 → 再写作。

**原则**：

1. **先跑通**：测试检索词固定为 `food delivery transformation`（不依赖 OpenAI）。  
2. **Zotero 为真源**（含离线增补）；本地 `literatures` 为镜像/缓存；`run-agent` 前从 Collection 拉取。  
3. **AUT→IEEE = Playwright UI 自动化**。  
4. 密码 / API Key 仅本机 `.env`，不进 Git、不进前端。  
5. 检索库：**全局 `.env` 注册表 + 项目 `literature_databases` 勾选**（1.1.1 时 IEEE；**1.1.2 起 ACM + UI 勾选 + 去重**）。

---

## 2. 已锁定决策

| 项 | 决定 |
|----|------|
| 搜索源 | AUT Library → **IEEE Xplore**（AU 账号密码） |
| Zotero 配置 | `backend/.env`：`ZOTERO_*` |
| AUT 登录 | `.env`：`AUT_USERNAME` / `AUT_PASSWORD`（及可选 CDP / 独立 Chrome 回退） |
| 触发方式 | Literature **按章向导**（不绑死 `run-agent`） |
| 入 Z 策略 | 确认页勾选后才入；未勾选不入 |
| 库结构 | **项目 = 顶层 Collection**；**章节 = Subcollection（heading）** |
| 同文多章 | MVP：一篇只进确认时那一章；检索候选若已在任意子集合则标 **已存在** |
| 写作读数 | **先 sync Zotero Collection**，再用本地镜像写作 |
| 测试 query | 固定 `food delivery transformation`；可手填 |
| 正式 query（Z5） | 有 Key 后按章 LLM；**尚未实现**（可手填 / 测试默认词） |

---

## 3. 端到端流程（已实现）

```
[配置] .env: Zotero + AUT + 检索库 URL
    │
    ▼
[Z1] ping / ensure-structure / import
    │
    ▼
[Z2–Z4] 按章向导：检索 → 确认（已存在标注）→ 入 Z + 本地
    │
    ▼
[Z6] run-agent：写作前 Zotero sync → 无文献则 400 → 写草稿
```

---

## 4. 实现 Track 结算

| Phase | 状态 |
|-------|------|
| Z0 定稿落地 | ✅ |
| Z1 Zotero 结构 + 写入 | ✅ |
| Z2 AUT→IEEE 检索 | ✅ |
| Z3 确认页 | ✅ |
| Z4 按章向导 | ✅ |
| Z5 LLM 检索词 | ✅（suggest-query） |
| Z6 写作对齐 + Zotero 拉取 | ✅ |
| ACM + 多库去重 + UI 勾选 | ✅（1.1.2） |
| Writer LLM 长文 | ✅（有 Key；失败回退模板） |

### 相对原稿的实现增量

- `POST .../zotero/sync`、写作前自动拉取  
- 候选 `already_exists` / `existing_outline_heading`  
- ACM 检索已实现（1.1.2）；多库各 `max_results` 后 DOI/标题去重  
- 检索 run 为**进程内存**（非独立表）

---

## 5. 非目标（仍有效）

- 付费墙 PDF 全文抓取  
- 一次接入全部 AUT 数据库  
- 大纲频繁变更下的集合迁移  
- MVP 强制 browser-use LLM  

---

核心契约以 `docs/api_reference.md`、`docs/database_schema.md`、`docs/implementation_status.md` 为准。
