"""dontmissddl — 交互式部署引导脚本。

自动化的部分：建多维表格字段、写 .env、可选写 GitHub Secrets。
最后打印一份必须手动完成的操作清单（开机器人、拉群、配飞书自动化等）。

用法：
    python setup.py
"""

import os
import re
import shutil
import subprocess
import sys

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from pathlib import Path

import requests

BASE = "https://open.feishu.cn"
ROOT = Path(__file__).parent
ENV_FILE = ROOT / ".env"

# 字段定义：名称/类型必须和 server/sources/feishu_bitable.py 写入的字段一致
# 类型：1=多行文本  3=单选  5=日期
FIELDS = [
    {"name": "标题", "type": 1},
    {"name": "状态", "type": 3, "options": ["待办", "已完成", "已忽略"]},
    {"name": "截止日期", "type": 5, "property": {"date_formatter": "yyyy-MM-dd HH:mm"}},
    {"name": "描述", "type": 1},
    {"name": "来源", "type": 1},
    {"name": "原始文本", "type": 1},
    {"name": "提醒状态", "type": 1},
    {"name": "添加日期", "type": 5, "property": {"date_formatter": "yyyy-MM-dd"}},
]


def ask(prompt, default=""):
    hint = f" [{default}]" if default else ""
    val = input(f"{prompt}{hint}: ").strip()
    return val if val else default


# ── 飞书 API ─────────────────────────────────────────────

def get_tenant_token(app_id, app_secret):
    r = requests.post(
        f"{BASE}/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": app_id, "app_secret": app_secret},
        timeout=10,
    )
    d = r.json()
    if d.get("code") != 0:
        raise RuntimeError(f"获取飞书 token 失败: code={d.get('code')} msg={d.get('msg')}")
    return d["tenant_access_token"]


def resolve_wiki_node(token, wiki_token):
    r = requests.get(
        f"{BASE}/open-apis/wiki/v2/spaces/get_node",
        headers={"Authorization": f"Bearer {token}"},
        params={"token": wiki_token},
        timeout=10,
    )
    d = r.json()
    if d.get("code") != 0:
        return ""
    return d.get("data", {}).get("node", {}).get("obj_token", "")


def list_field_names(token, app_token, table_id):
    r = requests.get(
        f"{BASE}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/fields",
        headers={"Authorization": f"Bearer {token}"},
        params={"page_size": 100},
        timeout=15,
    )
    d = r.json()
    if d.get("code") != 0:
        print(f"  ⚠ 读取已有字段失败: {d.get('msg')}")
        return []
    return [it["field_name"] for it in d.get("data", {}).get("items", [])]


def create_field(token, app_token, table_id, field):
    body = {"field_name": field["name"], "type": field["type"]}
    if field.get("property"):
        body["property"] = field["property"]
    r = requests.post(
        f"{BASE}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/fields",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=body,
        timeout=15,
    )
    return r.json()


def parse_bitable_url(url):
    """从多维表格链接里解析 app_token 和 table_id。"""
    app_token = ""
    table_id = ""
    m = re.search(r"/base/([A-Za-z0-9]+)", url)
    if m:
        app_token = m.group(1)
    m = re.search(r"[?&]table=([A-Za-z0-9]+)", url)
    if m:
        table_id = m.group(1)
    return app_token, table_id


# ── GitHub Secrets ──────────────────────────────────────

def detect_repo():
    try:
        out = subprocess.run(
            ["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
            capture_output=True, text=True, timeout=20,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return ""


def set_secret(name, value, repo):
    r = subprocess.run(
        ["gh", "secret", "set", name, "--repo", repo],
        input=value, text=True, capture_output=True, timeout=30,
    )
    return r.returncode == 0


# ── 主流程 ──────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  dontmissddl 部署引导")
    print("  能自动化的自动化，不能的会告诉你下一步手动做什么")
    print("=" * 60)
    print()

    cfg = {}

    print("【1/4】LLM（DeepSeek）")
    cfg["LLM_API_KEY"] = ask("  DeepSeek / OpenAI 兼容 API Key")
    cfg["LLM_BASE_URL"] = ask("  API 地址", "https://api.deepseek.com/v1")
    cfg["LLM_MODEL"] = ask("  模型名", "deepseek-chat")
    print()

    print("【2/4】飞书自建应用（读群消息 + 写多维表格）")
    cfg["FEISHU_APP_ID"] = ask("  App ID（cli_ 开头）")
    cfg["FEISHU_APP_SECRET"] = ask("  App Secret")
    print()

    print("【3/4】多维表格（存储）")
    print("  先去飞书新建一个空的多维表格（不用建字段，脚本帮你建），")
    print("  然后复制它的链接。链接长这样：")
    print("  https://xxx.feishu.cn/base/bascnXXXX?table=tblXXXX&view=vewXXXX")
    url = ask("  多维表格链接")
    app_token, table_id = parse_bitable_url(url)
    if not app_token:
        m = re.search(r"/wiki/([A-Za-z0-9]+)", url)
        if m and cfg["FEISHU_APP_ID"] and cfg["FEISHU_APP_SECRET"]:
            try:
                token = get_tenant_token(cfg["FEISHU_APP_ID"], cfg["FEISHU_APP_SECRET"])
                app_token = resolve_wiki_node(token, m.group(1))
            except RuntimeError as e:
                print(f"  ⚠ {e}")
    if not app_token:
        app_token = ask("  手动填 app_token（bascn 开头）")
    if not table_id:
        table_id = ask("  手动填 table_id（tbl 开头）")
    cfg["FEISHU_APP_TOKEN"] = app_token
    cfg["FEISHU_TABLE_ID"] = table_id
    print()

    if cfg["FEISHU_APP_ID"] and cfg["FEISHU_APP_SECRET"] and app_token and table_id:
        print("  正在自动创建字段...")
        try:
            token = get_tenant_token(cfg["FEISHU_APP_ID"], cfg["FEISHU_APP_SECRET"])
            existing = list_field_names(token, app_token, table_id)
            for f in FIELDS:
                if f["name"] in existing:
                    print(f"    · {f['name']}（已存在，跳过）")
                    continue
                res = create_field(token, app_token, table_id, f)
                if res.get("code") == 0:
                    print(f"    ✓ {f['name']}")
                else:
                    print(f"    ✗ {f['name']} 创建失败: {res.get('msg')}")
        except RuntimeError as e:
            print(f"  ⚠ {e}")
    print()

    print("【4/4】信息源（至少配一个，都可以以后再补）")
    cfg["FEISHU_GROUP_IDS"] = ask("  飞书群 chat_id（多个用逗号分隔）")
    email = ask("  邮箱账号（可选，如 xxx@qq.com）")
    if email:
        cfg["EMAIL_USER"] = email
        cfg["EMAIL_HOST"] = ask("    IMAP 服务器", "imap.qq.com")
        cfg["EMAIL_PORT"] = ask("    IMAP 端口", "993")
        cfg["EMAIL_PASSWORD"] = ask("    邮箱授权码/密码")
    cfg["WECHAT_SOGOU_NAMES"] = ask("  公众号名称（可选，多个用逗号分隔，如 字节跳动招聘,腾讯招聘）")
    print()

    lines = [
        "# dontmissddl 配置（由 setup.py 生成）",
        "# 生产环境请把这些填到 GitHub Secrets，.env 只用于本地调试",
    ]
    for k, v in cfg.items():
        if v:
            lines.append(f"{k}={v}")
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"✓ 已写入 {ENV_FILE.name}")

    if shutil.which("gh"):
        repo = detect_repo()
        if repo:
            do_secrets = ask("  检测到 gh CLI，要把这些配置写到 GitHub Secrets 吗？(y/N)", "n").lower()
            if do_secrets in ("y", "yes"):
                ok = total = 0
                for k, v in cfg.items():
                    if not v:
                        continue
                    total += 1
                    if set_secret(k, v, repo):
                        ok += 1
                        print(f"    ✓ {k}")
                    else:
                        print(f"    ✗ {k} 失败")
                print(f"  已写入 {ok}/{total} 个 Secret")
    else:
        print("  未检测到 gh CLI，稍后请到仓库 Settings → Secrets 手动填。")

    print()
    print("=" * 60)
    print("  接下来还需要你手动完成（脚本无法自动化）：")
    print("=" * 60)
    print("  1. 飞书开放平台 → 自建应用：打开「机器人」能力，开通权限")
    print("     （读取群消息、多维表格读写、知识库读取），然后发布应用。")
    print("  2. 把机器人拉进要监听的飞书群，确认 FEISHU_GROUP_IDS 填对了。")
    print("  3. 多维表格里加一个公式列「剩余天数」：")
    print('     = DATEDIF(TODAY(), 截止日期, "D")')
    print("  4. 多维表格右上角「自动化」→ 新建两条规则：")
    print("     A. 触发=记录新增 → 发通知")
    print("     B. 触发=每天 09:30，条件=剩余天数∈{7,3,1} → 发带「完成/忽略」按钮的卡片")
    print("  5. 仓库 Settings → Actions 启用，然后到 Actions 页手动触发一次测试。")
    print()


if __name__ == "__main__":
    main()
