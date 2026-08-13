# dontmissddl — 别再错过任何一个 DDL

> A zero-server, zero-cost deadline reminder. It watches your Feishu groups, email, and WeChat public accounts, extracts deadlines with an LLM, stores them in a Feishu Bitable, and reminds you via Feishu automation.

一个**零服务器、零成本**的 DDL（截止日期）提醒工具。它会盯着你的**飞书群聊、邮箱、微信公众号**，用 LLM 自动提取截止时间，存进**飞书多维表格**，再由**飞书自动化**在到期前提醒你。全程跑在 GitHub Actions 上，不需要买服务器。

---

## 架构

```
每天 09:00（GitHub Actions 定时任务）
        │
        ├─ 拉取 4 个信息源的最新内容
        │     ├─ 💬 飞书群聊消息
        │     ├─ 📧 邮箱（IMAP）
        │     ├─ 📰 公众号（搜狗搜索）
        │     └─ 📰 公众号（RSS 源）
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

## 功能

- 🔍 自动识别 4 个信息源里的截止时间
- 🧠 LLM 理解中文时间表达（「下周五前」「月底前」「8 月 20 日前」）
- 📊 自动去重，同一件事不会存两遍；已过期的 DDL 不会写入
- ⏰ 到期前 7 / 3 / 1 天提醒 + 新增通知（由飞书自动化实现）
- 🆓 零成本：GitHub Actions 免费额度 + DeepSeek（每次提取约 $0.001）
- 📦 零服务器：没有 Docker、没有 VPS、没有常驻进程

---

## 快速开始

```bash
# 1. Fork 本仓库，clone 到本地，运行引导脚本：
#    python setup.py
#    它会带你填配置、自动建多维表格字段、写 .env，并可选帮你写 GitHub Secrets

# 2. 手动完成剩下的飞书配置（见下一节「连接飞书」）：
#    开机器人 + 把机器人拉进群 + 配自动化

# 3. 完成。GitHub Actions 每天 09:00（北京时间）自动跑一次。
#    也可以到 Actions 页手动 workflow_dispatch 触发测试。
```

---

## 连接飞书（重点）

飞书侧有三块要配置：**自建应用**（读群消息）、**多维表格**（存数据）、**自动化**（发提醒）。三者互相关联，按顺序来。

### 1. 飞书自建应用 —— 负责读群消息 + 写表格

1. 到 [飞书开放平台](https://open.feishu.cn) → 创建「企业自建应用」。
2. 在「凭证与基础信息」拿到 **App ID** 和 **App Secret**（对应 `FEISHU_APP_ID` / `FEISHU_APP_SECRET`）。
3. 打开「机器人」能力。
4. 在「权限管理」里勾选并开通：
   - 读取群消息（`im:message`）
   - 多维表格读写（`bitable:app`）
   - 知识库读取（用于解析表格 token，`wiki:*` 相关）
5. 把机器人拉进你要监听的飞书群，拿到群的 **chat_id**（对应 `FEISHU_GROUP_IDS`，多个用逗号分隔）。

### 2. 多维表格（Bitable）—— 负责存 DDL

1. 新建一个多维表格（建议放进知识库，方便取 token），建好以下字段：

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

2. 拿到 token（`python setup.py` 能自动帮你建字段并解析 token）：
   - `FEISHU_APP_TOKEN`：多维表格的 app_token，就是链接里 `/base/` 后面那一串（`bascn...`）。**首选，直接填这个。**
   - `FEISHU_TABLE_ID`：数据表的 table_id，就是链接里 `table=tbl...` 那一段。
   - `FEISHU_WIKI_TOKEN`：备选。如果你只拿得到知识库节点 token（`/wiki/` 后面那串），填它也能跑，代码会自动解析出 app_token。

   > 字段（标题/状态/截止日期…）用 `python setup.py` 自动建，避免手建 8 个字段拼错名；「剩余天数」公式列留到第 3 步手动加。

3. 代码写入时，**状态固定填「待办」**，已过期的 DDL 会自动跳过。

### 3. 飞书自动化 —— 负责提醒

提醒完全由多维表格自带的「自动化」实现，代码不参与。打开多维表格 → 右上角「自动化」→ 新建两条规则：

**规则 A · 新增 DDL 通知**

- 触发器：记录被新增时
- 动作：发送消息/卡片到群（或私聊自己），内容带上「标题」和「截止日期」

**规则 B · 到期提醒（7 / 3 / 1 天）**

- 前提：先加好上面的「剩余天数」公式列
- 触发器：每天定时（例如 09:30）
- 条件：`剩余天数 ∈ {7, 3, 1}`
- 动作：发送卡片，卡片里放两个按钮：
  - 「完成」→ 把「状态」改为「已完成」
  - 「忽略」→ 把「状态」改为「已忽略」

这样每条 DDL 会在到期前 7 天、3 天、1 天各提醒一次，点按钮即可标记处理。

---

## 信息源

| 信息源 | 需要的配置 | 原理 |
|--------|-----------|------|
| 🟢 飞书群聊 | `FEISHU_APP_ID` / `FEISHU_APP_SECRET` / `FEISHU_GROUP_IDS` | 机器人定时拉群消息 |
| 📧 邮箱 | `EMAIL_HOST` / `EMAIL_USER` / `EMAIL_PASSWORD` 等 | IMAP 增量拉取未读邮件 |
| 📰 公众号（搜狗） | `WECHAT_SOGOU_NAMES` | 按公众号名称搜最新文章 |
| 📰 公众号（RSS） | `WECHAT_RSS_URLS` | 解析 RSS 源（Feeddd / WeRSS） |

> 至少配一个源就能跑，飞书群聊是主源。

---

## 配置（GitHub Secrets）

| Secret | 必填 | 说明 |
|--------|------|------|
| `LLM_API_KEY` | ✅ 是 | DeepSeek / OpenAI 兼容 API Key |
| `LLM_BASE_URL` | 否 | API 地址（默认 DeepSeek） |
| `LLM_MODEL` | 否 | 模型名（默认 `deepseek-chat`） |
| `FEISHU_APP_ID` | ✅* | 飞书自建应用 App ID |
| `FEISHU_APP_SECRET` | ✅* | 飞书自建应用密钥 |
| `FEISHU_GROUP_IDS` | 否 | 监听群 chat_id，逗号分隔 |
| `FEISHU_APP_TOKEN` | ✅* | 多维表格 app_token（链接 `/base/` 后那串，首选） |
| `FEISHU_WIKI_TOKEN` | 备选 | 知识库节点 token（没 app_token 时用） |
| `FEISHU_TABLE_ID` | ✅* | 数据表 table_id |
| `EMAIL_HOST` | 否 | IMAP 服务器（如 `imap.qq.com`） |
| `EMAIL_PORT` | 否 | IMAP 端口（默认 993） |
| `EMAIL_USER` | 否 | 邮箱账号 |
| `EMAIL_PASSWORD` | 否 | 邮箱密码或授权码 |
| `WECHAT_SOGOU_NAMES` | 否 | 公众号名称，逗号分隔 |
| `WECHAT_RSS_URLS` | 否 | RSS 源地址，逗号分隔 |

> `*` 表示写多维表格这一环节必须配置；信息源本身按需选一个即可。

---

## 目录结构

```
dontmissddl/
├── setup.py                    ← 部署引导脚本（python setup.py）
├── server/
│   ├── main.py                  ← 入口：poll 拉取并写入多维表格
│   ├── extract.py               ← LLM 提取 DDL
│   └── sources/
│       ├── feishu_bot.py        ← 飞书群消息读取
│       ├── feishu_bitable.py    ← 多维表格写入
│       ├── email_source.py      ← 邮箱 IMAP
│       ├── wechat_sogou.py      ← 公众号（搜狗搜索）
│       └── wechat_rss.py        ← 公众号（RSS）
├── prompts/
│   └── extract-ddl.md           ← 提取提示词
├── data/
│   └── state.json               ← 去重锚点（增量拉取的游标）
├── .github/workflows/
│   └── cron.yml                 ← 每天定时跑 poll
└── .env.example                 ← 环境变量样例
```

---

## English

**dontmissddl** is a zero-server, zero-cost DDL reminder. It monitors Feishu groups, email inbox, and WeChat public accounts, extracts deadlines with an LLM (DeepSeek), stores them in a Feishu Bitable, and sends reminders via Feishu automation. Everything runs on GitHub Actions' free tier — no server, no database, no running process to maintain.

**Pipeline:** GitHub Actions (daily 09:00 Beijing) → poll 4 sources → LLM extraction → write Feishu Bitable → Feishu automation sends reminders (new-DDL notice + 7/3/1-day alerts with "ignore/done" buttons).

**Feishu side (three pieces):**
1. **Custom app** — reads group messages and writes the Bitable (`FEISHU_APP_ID`/`SECRET`, bot capability, `im:message` + `bitable:app` + wiki permissions).
2. **Bitable** — the database. Fields: 标题 / 状态 / 截止日期 / 描述 / 来源 / 原始文本 / 提醒状态 / 添加日期 / 剩余天数(formula). Provide its wiki node token (`FEISHU_WIKI_TOKEN`) and table id (`FEISHU_TABLE_ID`); the code resolves the app_token automatically.
3. **Automation** — the reminder scheduler. Rule A notifies on new records; Rule B runs daily and fires when 剩余天数 ∈ {7,3,1}, sending a card with "完成/忽略" buttons that update 状态.

**Getting started:** fork this repo → run `python setup.py` (interactive guide that creates Bitable fields, writes `.env`, and can set GitHub Secrets) → finish the few manual Feishu steps → done.

---

MIT License
