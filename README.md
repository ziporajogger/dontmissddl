# dontmissddl — 别再错过任何一个 DDL

> A zero-server, zero-cost deadline reminder. It watches Feishu groups, email, or WeChat public accounts, extracts deadlines with an LLM, stores them in a Feishu Bitable, and reminds you via Feishu automation.

一个**零服务器、零成本**的 DDL（截止日期）提醒工具。它盯着你选的**信息源**（飞书群聊 / 邮箱 / 公众号，任选一个或多个），用 LLM 自动提取截止时间，存进**飞书多维表格**，再由**飞书自动化**在到期前提醒你。全程跑在 GitHub Actions 上，不需要买服务器。

---

## 架构

```
每天 09:00（GitHub Actions 定时任务）
        │
        ├─ 拉取信息源的最新内容（任选一个或多个）
        │     ├─ 💬 飞书群聊消息
        │     ├─ 📧 邮箱（IMAP）
        │     └─ 📰 公众号（搜狗搜索）
        │
        ├─ 逐条交给 DeepSeek 判断「有没有 DDL」
        │     有 → 提取标题 + 截止日期
        │
        ├─ 写入飞书多维表格（Bitable）
        │     字段：标题 / 截止日期 / 描述 / 来源 / 原始文本 …
        │
        └─ 飞书自动化负责提醒（代码不管这一步）
               ├─ 新增 DDL → 发通知
               └─ 到期 7 / 3 / 1 天 → 发带「忽略/完成」按钮的卡片
```

**关键设计**：收集和提取是代码（GitHub Actions），**存储和提醒都在飞书上**——多维表格当数据库，自动化当定时提醒。代码库里不存任何个人数据，也没有后台服务要维护。

---

## 信息源（任选一个或多个）

你只需要配一个信息源就能跑，想盯几类就配几类。

| 信息源 | 需要的配置 | 原理 |
|--------|-----------|------|
| 🟢 飞书群聊 | `FEISHU_APP_ID` / `FEISHU_APP_SECRET` / `FEISHU_GROUP_IDS` | 机器人定时拉群消息 |
| 📧 邮箱 | `EMAIL_HOST` / `EMAIL_USER` / `EMAIL_PASSWORD` 等 | IMAP 增量拉取未读邮件 |
| 📰 公众号 | `WECHAT_SOGOU_NAMES`（公众号名称） | 搜狗搜索 |

**邮箱支持所有 IMAP 协议的服务**，下面几个开箱即用：

| 邮箱 | IMAP 服务器 | 端口 | 密码填什么 |
|------|------------|------|-----------|
| QQ 邮箱 | `imap.qq.com` | 993 | **授权码**（不是登录密码） |
| 163 邮箱 | `imap.163.com` | 993 | 授权码 |
| 126 邮箱 | `imap.126.com` | 993 | 授权码 |
| Gmail | `imap.gmail.com` | 993 | 应用专用密码（App Password） |
| Outlook | `outlook.office365.com` | 993 | 应用密码 |

> 国内邮箱（QQ/163/126）需要在邮箱设置里开启 IMAP 并生成「授权码」，用授权码当密码。

**公众号的抓取方式**：公众号没有公开 API，这里走「搜狗搜索」——填公众号名称，用 Playwright 模拟浏览器去搜狗微信搜，抓标题和正文。需要装 Playwright，偶尔会遇到验证码/反爬。

---

## 部署流程

> 💡 使用 Claude Code：克隆仓库后在目录中打开，输入 `/dontmissddl-setup` 即可开始安装；否则按下方 `start.bat` 流程操作。

整个部署拆成「**自动**」和「**手动**」两部分。能自动的，**Windows 双击 `start.bat`**（Mac/Linux 跑 `python setup.py`）全帮你做了；必须手动的（飞书没有开放接口），脚本最后会打印清单一步步提醒你。

### ✅ 全自动 —— 双击 start.bat 帮你做

| 步骤 | 做什么 |
|------|--------|
| 生成配置 | 自动生成 `.env` 文件模板 |
| 创建多维表格 | 调用飞书接口自动建一个多维表格，并拿到 token |
| 创建字段 | 自动建好 8 个字段（标题/状态/截止日期/…），字段名精确匹配代码 |
| 写回配置 | 把表格 token 自动写回 `.env` |
| 写 Secrets | （可选）用 `gh` CLI 把你 `.env` 里的配置批量写入 GitHub Secrets |

> ⚠️ 唯一要注意的：**密钥（API Key、App Secret）不要在任何对话框里输入，全部填进 `.env` 文件**，脚本会去读它。

### ✋ 必须手动 —— 飞书/平台没有开放接口，谁都做不了

1. 在[飞书开放平台](https://open.feishu.cn)创建「企业自建应用」，拿 App ID / App Secret
2. 开通「多维表格读写」权限（必须，写表格用）；如果选飞书群，再开通「读取群消息」+ 打开「机器人」
3. 发布应用（可能需要管理员审批）
4. （选了飞书群才需要）把机器人拉进群
5. 多维表格里加「剩余天数」公式列 + 配 2 条自动化提醒 ← **这一步才是真·必做，否则收不到提醒**
6. 启用 GitHub Actions

### 完整流程

```
第 1 步  装 git + Python，Fork 本仓库，clone 到本地
第 2 步  飞书开放平台建自建应用 + 开通「多维表格读写」权限（手动，跑脚本前先做）
第 3 步  双击 start.bat → 生成 .env → 用记事本填好密钥 + 一个信息源 → 按回车
         （脚本自动：建多维表格 + 建字段 + 可选写 GitHub Secrets）
第 4 步  照脚本最后打印的清单手动收尾（发布、加「剩余天数」公式列、配自动化）
第 5 步  Actions 手动触发一次测试 → 收工
```

---

## 连接飞书（三块）

飞书侧有三块配置：**自建应用**（写表格 + 可选读群消息）、**多维表格**（存数据）、**自动化**（发提醒）。多维表格这步 `setup.py` 会自动帮你建好。

### 1. 飞书自建应用 —— 写表格（必须）+ 读群消息（选做）

1. [飞书开放平台](https://open.feishu.cn) → 创建「企业自建应用」。
2. 「凭证与基础信息」拿 **App ID** / **App Secret**（填进 `.env` 的 `FEISHU_APP_ID` / `FEISHU_APP_SECRET`）。
3. 「权限管理」开通：
   - **多维表格读写**（`bitable:app`）—— 必须，写表格用
   - **读取群消息**（`im:message`）+ 打开「机器人」—— 只有你选飞书群作为信息源时才需要
4. 发布应用（可能要管理员审批）。

> 「多维表格读写」权限必须在跑 setup.py **之前**开通，否则脚本自动建表格会失败。

### 2. 多维表格（Bitable）—— 存 DDL

**由 `setup.py` 自动创建**，字段如下（手动建表时的参考）：

| 字段 | 类型 | 说明 |
|------|------|------|
| 标题 | 文本 | DDL 标题（LLM 生成） |
| 状态 | 单选 | 待办 / 已完成 / 已忽略（自动化按钮会改它） |
| 截止日期 | 日期 | 截止时间 |
| 描述 | 文本 | 内容摘要 |
| 来源 | 文本 | 来自哪个群/邮箱/公众号 |
| 原始文本 | 文本 | 原始消息全文（方便回看） |
| 提醒状态 | 文本 | 预留 |
| 添加日期 | 日期 | 入库日期 |
| 剩余天数 | 公式 | `DATEDIF(TODAY(), 截止日期, "D")`，给自动化用 |

> 代码写入时「状态」固定填「待办」，已过期的 DDL 会自动跳过。

### 3. 飞书自动化 —— 提醒（必做）

提醒完全由多维表格自带的「自动化」实现。打开多维表格 → 右上角「自动化」→ 新建两条规则：

**规则 A · 新增 DDL 通知**：触发器=记录新增 → 发消息/卡片到群。

**规则 B · 到期提醒（7/3/1 天）**：触发器=每天 09:30 → 条件=剩余天数∈{7,3,1} → 发带「完成」「忽略」按钮的卡片（点按钮把「状态」改成已完成/已忽略）。

---

## 配置（GitHub Secrets）

这些配置都存在 `.env` 里（本地调试用），生产环境填到 GitHub Secrets（`setup.py` 可帮你批量写入）。

| Secret | 必填 | 说明 |
|--------|------|------|
| `LLM_API_KEY` | ✅ 是 | DeepSeek / OpenAI 兼容 API Key |
| `LLM_BASE_URL` | 否 | API 地址（默认 DeepSeek） |
| `LLM_MODEL` | 否 | 模型名（默认 `deepseek-chat`） |
| `FEISHU_APP_ID` | ✅* | 飞书自建应用 App ID（写表格用） |
| `FEISHU_APP_SECRET` | ✅* | 飞书自建应用密钥 |
| `FEISHU_APP_TOKEN` | ✅* | 多维表格 app_token（setup.py 自动填） |
| `FEISHU_TABLE_ID` | ✅* | 数据表 table_id（setup.py 自动填） |
| `FEISHU_GROUP_IDS` | 选填 | 监听群 chat_id（选了飞书群才填） |
| `EMAIL_HOST` / `EMAIL_PORT` | 选填 | IMAP 服务器 / 端口 |
| `EMAIL_USER` / `EMAIL_PASSWORD` | 选填 | 邮箱账号 / 授权码 |
| `WECHAT_SOGOU_NAMES` | 选填 | 公众号名称，逗号分隔 |

> `*` 表示这套「写表格」链路必须配置；信息源按需任选一个即可。

---

## 目录结构

```
dontmissddl/
├── start.bat                   ← Windows 双击这个开始
├── setup.py                    ← 部署脚本（Mac/Linux 跑 python setup.py）
├── server/
│   ├── main.py                 ← 入口：拉取信息源并写入存储
│   ├── storage.py              ← 存储抽象层（目前仅飞书多维表格）
│   ├── extract.py              ← LLM 提取 DDL
│   └── sources/
│       ├── feishu_bot.py       ← 飞书群消息读取
│       ├── feishu_bitable.py   ← 多维表格读写
│       ├── email_source.py     ← 邮箱 IMAP
│       └── wechat_sogou.py     ← 公众号（搜狗搜索）
├── prompts/
│   └── extract-ddl.md          ← 提取提示词
├── data/
│   └── state.json              ← 去重锚点（增量拉取的游标）
├── .github/workflows/
│   └── cron.yml                ← 每天定时跑 poll
└── .env.example                ← 环境变量样例
```

---

## English

**dontmissddl** is a zero-server, zero-cost DDL reminder. It monitors Feishu groups, email (any IMAP mailbox), or WeChat public accounts — pick one or more — extracts deadlines with an LLM (DeepSeek), stores them in a Feishu Bitable, and sends reminders via Feishu automation. Everything runs on GitHub Actions' free tier.

**Pipeline:** GitHub Actions (daily 09:00 Beijing) → poll sources → LLM extraction → write Feishu Bitable → Feishu automation sends reminders (new-DDL notice + 7/3/1-day alerts with "ignore/done" buttons).

**If you use Claude Code**, open the cloned repo and run `/dontmissddl-setup`; otherwise use `start.bat` below.

**Setup is split into automated vs manual:**
- **Automated** (run `start.bat` (Windows) / `python setup.py`): generates `.env`, creates the Bitable + its 8 fields via Feishu API, writes tokens back to `.env`, and (optionally) bulk-writes GitHub Secrets via `gh`.
- **Manual** (no public API exists): create the Feishu app + grant `bitable:app` (required) and, only if monitoring groups, `im:message` + bot; publish the app; add the 剩余天数 formula column; configure the 2 automation rules; enable Actions.
- **Keys never go in a dialog** — fill them in the `.env` file; the script reads from there.

**Getting started:** install git + Python → fork & clone → create the Feishu app & grant permissions → run `start.bat` (Windows) / `python setup.py` → fill `.env` (LLM key + one source) → press Enter → follow the printed manual checklist → trigger a test run.

---

MIT License
