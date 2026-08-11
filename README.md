# dontmissddl — Never Miss a Deadline Again

[English](#english) | [中文](#中文)

---

## English

**dontmissddl** watches your Feishu groups, email inbox, and WeChat public accounts — automatically extracts deadlines with AI, then reminds you before they're due. No server needed. Everything runs in GitHub Actions.

### How It Works

```
GitHub Actions (daily)
    │
    ├── Poll 3 sources for new content
    │     ├── Feishu group messages
    │     ├── Email inbox (IMAP)
    │     └── WeChat RSS feeds
    │
    ├── LLM reads each item: "Is there a deadline?"
    │       │
    │       ▼
    │   Yes → Extract title + deadline → Save to data/ddls.json
    │
    └── Check upcoming DDLs → Send Feishu reminder
            ⏰ "XX project due in 3 days!"
```

### Quick Start

```bash
# 1. Create a Feishu app at https://open.feishu.cn
#    - Enable Bot capability
#    - Add permission: im:message
#    - Get App ID and App Secret

# 2. Add the bot to your target Feishu groups
#    Get the group chat_id from the URL or API

# 3. (Optional) Configure email IMAP or WeChat RSS
#    See Configuration section below

# 4. Fork this repo & set GitHub Secrets
#    Settings → Secrets and variables → Actions
#    Add at minimum: LLM_API_KEY + your source config

# 5. Done! GitHub Actions runs daily at 9:00 AM Beijing time.
```

### Information Sources

| Source | Required Config | How It Works |
|--------|----------------|--------------|
| 🟢 **Feishu** | `FEISHU_APP_ID`, `FEISHU_APP_SECRET`, `FEISHU_GROUP_IDS` | Bot polls group messages via Open API |
| 📧 **Email** | `EMAIL_HOST`, `EMAIL_USER`, `EMAIL_PASSWORD` | IMAP fetches unread emails, checks for DDLs |
| 📰 **WeChat RSS** | `WECHAT_RSS_URLS` | Parses RSS feeds (Feeddd/WeRSS), optionally fetches article body |

> 💡 You only need ONE source to start. Feishu is the primary source with the best integration (reminders are sent back to groups). Email and RSS are great for monitoring newsletters, course announcements, etc.

### Features

- 🔍 **Auto-detect** deadlines across 3 sources (Feishu, Email, WeChat RSS)
- 🧠 **LLM-powered** — understands Chinese time expressions ("下周五"、"月底前")
- 🔔 **Multi-stage reminders** — notified 7, 3, and 1 day before deadline
- 🆓 **Zero cost** — GitHub Actions free tier + DeepSeek (~$0.001/extraction)
- 📊 **No duplicates** — same title + deadline won't be saved twice
- 📦 **No server** — everything in GitHub Actions, no Docker, no VPS

### Architecture

```
dontmissddl/
├── server/
│   ├── main.py              ← CLI: poll + remind
│   ├── extract.py            ← LLM DDL extraction
│   └── sources/
│       ├── feishu_bot.py     ← Feishu Open API client
│       ├── email_source.py   ← IMAP inbox reader
│       └── wechat_rss.py     ← RSS feed parser
├── prompts/
│   └── extract-ddl.md        ← extraction prompt
├── data/
│   ├── ddls.json             ← stored DDL items
│   └── state.json            ← last processed IDs
├── .github/workflows/
│   └── cron.yml              ← runs daily
└── SKILL.md                  ← Claude Code companion skill
```

### Configuration (GitHub Secrets)

| Secret | Required | Description |
|--------|----------|-------------|
| `LLM_API_KEY` | ✅ Yes | DeepSeek or OpenAI-compatible API key |
| `LLM_BASE_URL` | No | LLM API base URL (default: DeepSeek) |
| `LLM_MODEL` | No | Model name (default: deepseek-chat) |
| `FEISHU_APP_ID` | No | Feishu app ID |
| `FEISHU_APP_SECRET` | No | Feishu app secret |
| `FEISHU_GROUP_IDS` | No | Comma-separated chat_ids |
| `EMAIL_HOST` | No | IMAP host (e.g. imap.qq.com) |
| `EMAIL_PORT` | No | IMAP port (default: 993) |
| `EMAIL_USER` | No | Email account |
| `EMAIL_PASSWORD` | No | Email password or app code |
| `WECHAT_RSS_URLS` | No | Comma-separated RSS feed URLs |

---

## 中文

**dontmissddl** 帮你盯着飞书群、邮箱和公众号，自动用 AI 提取截止时间，到期前主动在群里提醒。零服务器，全靠 GitHub Actions。

### 怎么用

1. 在 [飞书开放平台](https://open.feishu.cn) 创建一个应用 → 开启 Bot → 添加 `im:message` 权限 → 拿到 App ID 和 App Secret
2. 把 Bot 拉进你要监听的飞书群 → 拿到群的 chat_id
3. （可选）配置邮箱 IMAP 或公众号 RSS 源
4. Fork 这个仓库 → 在 Settings → Secrets 里填密钥
5. 完成。GitHub Actions 每天自动跑一次。

### 信息源

| 信息源 | 需要的配置 | 原理 |
|--------|-----------|------|
| 🟢 **飞书群** | `FEISHU_APP_ID` 等 | Bot 定时拉群消息 |
| 📧 **邮箱** | `EMAIL_HOST` 等 | IMAP 拉取未读邮件检测 DDL |
| 📰 **公众号** | `WECHAT_RSS_URLS` | 解析 RSS 源（Feeddd/WeRSS 等）文章内容 |

### 原理

```
每天 GitHub Actions 自动运行
    ├── 拉取 3 个信息源的最新内容
    │     ├── 飞书群消息
    │     ├── 未读邮件
    │     └── 公众号 RSS 文章
    ├── LLM 判断是否包含 DDL
    ├── 提取标题 + 截止时间 → 存 data/ddls.json
    └── 检查到期 DDL → 飞书群发提醒
```

### 配置（GitHub Secrets）

| Secret | 必填 | 说明 |
|--------|------|------|
| `LLM_API_KEY` | ✅ 是 | DeepSeek API Key（10 块钱用几个月） |
| `LLM_BASE_URL` | 否 | LLM API 地址 |
| `LLM_MODEL` | 否 | 模型名（默认 deepseek-chat） |
| `FEISHU_APP_ID` | 否 | 飞书应用 App ID |
| `FEISHU_APP_SECRET` | 否 | 飞书应用 App Secret |
| `FEISHU_GROUP_IDS` | 否 | 监听的群 chat_id，逗号分隔 |
| `EMAIL_HOST` | 否 | IMAP 服务器（如 imap.qq.com） |
| `EMAIL_PORT` | 否 | IMAP 端口（默认 993） |
| `EMAIL_USER` | 否 | 邮箱账号 |
| `EMAIL_PASSWORD` | 否 | 邮箱密码或授权码 |
| `WECHAT_RSS_URLS` | 否 | RSS 源地址，逗号分隔 |

---

MIT License
