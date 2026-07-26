# NotebookLM 同步 — 简化 MVP 设计

状态：已定稿（按产品确认简化）  
日期：2026-07-25

## 产品目标（只做这些）

1. 用户填写一个 **NotebookLM URL**
2. 点击 **「更新」**：用本机已登录的浏览器会话打开该 URL，把 notebook 里 **从头到尾的对话全文** 拉下来
3. 保存到 `notebooklm_inputs`，界面显示 **最近同步时间戳**；可再次点「更新」覆盖式追加一条新记录（保留历史）

不做：定时 cron、多 Worker、浏览器扩展、SaaS 云端无头爬 Google。

## 原理

前端页面无法跨域直接读 `notebooklm.google.com` 的 DOM。  
因此「当前 browser 能访问」= **本机 Chrome 已登录 Google**，后端用 **Playwright 复用同一 User Data Dir（专用 Profile）** 打开 URL 并抽取文本。

```
[用户 Chrome 已登录 NotebookLM]
        │ 配置 CHROME_USER_DATA_DIR + Profile
        ▼
[点「更新」] → API POST /notebook/{id}/sync
        ▼
[Playwright persistent context] → 打开 URL → 滚到底 → 抽取对话全文
        ▼
[notebooklm_inputs] raw_transcript + synced_at
```

## 使用前提

1. 创建/使用 **专用调试 Chrome 目录**（`~/.academic-agent-platform/chrome-debug-profile`），由 `./scripts/start-chrome-debug.sh` 启动并开启 CDP `9222`  
   - 新版 Chrome 会对**系统默认用户目录**静默忽略 `--remote-debugging-port`（命令行有参数但端口不监听）  
2. 在该专用窗口登录 Google / NotebookLM（首次一次即可）  
3. `.env` 配置：`CHROME_CDP_URL=http://127.0.0.1:9222`  
4. 同步时保持该调试 Chrome 开着即可；日常浏览可用普通 Chrome（另一套目录）

## UI（项目详情 → Inputs）

| 元素 | 说明 |
|------|------|
| Notebook URL | 文本框，可编辑 |
| 最近同步 | `synced_at` 时间戳；从未同步显示「尚未同步」 |
| 更新 | 触发 browser 抓取 |
| 对话预览 | 展示最近一次 `raw_transcript` / summary |
| （保留）手动粘贴 | 抓取失败时的兜底 |

## API

`POST /api/notebook/{project_id}/sync`

```json
{ "notebook_url": "https://notebooklm.google.com/...", "use_browser": true }
```

成功 → `NotebookLMOut`（含 `synced_at`、`raw_transcript`）。

## 抓取策略（实现）

1. `launch_persistent_context(user_data_dir, channel="chrome", headless=False)`  
2. `goto(notebook_url)`，等待网络大致空闲  
3. 在聊天区域多次向上滚动，尽量加载历史  
4. 抽取对话节点文本；若 selector 失效则回退 `main`/`body` 可见文本  
5. 规范化后入库，并生成 `extracted_summary`

Selector 集中在服务内常量，Google 改版时只改一处。

## 风险（可接受）

- DOM 改版可能导致抽取变差 → 用户改用手动粘贴  
- Profile 锁定 / 未登录 → API 返回明确错误文案  
- 仅适合本机单用户开发/实验室，不是多租户云爬虫  

## 与旧方案关系

原「定期调度 / 扩展 / 云 Worker」方案搁置；本文替代为唯一目标范围。
