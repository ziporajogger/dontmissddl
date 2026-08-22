"""dontmissddl — 一键部署引导脚本（Windows 下可双击运行）。

职责：能自动化的全部自动化。你只需要在 .env 文件里填好密钥（不要在对话框输入），
剩下的——创建多维表格、创建字段、写 GitHub Secrets——都由本脚本完成。
必须手动的那几步（发布应用、拉群、配自动化等），脚本最后会打印清单提醒你。

用法：
    Windows：双击 start.bat
    其它平台：python setup.py
"""

import shutil
import subprocess
import sys

if sys.version_info < (3, 9):
    print(f"Python 版本过低：需要 3.9+，当前 {sys.version.split()[0]}。")
    print("请到 https://www.python.org/downloads/ 下载安装，勾选 Add to PATH。")
    input("按回车键退出...")
    sys.exit(1)

try:
    import requests
except ImportError:
    print("缺少依赖 requests，正在自动安装...")
    subprocess.run([sys.executable, "-m", "pip", "install", "requests"], check=False)
    try:
        import requests
    except ImportError:
        print("自动安装失败，请手动运行：  pip install requests")
        input("按回车键退出...")
        sys.exit(1)

from pathlib import Path

BASE = "https://open.feishu.cn"
ROOT = Path(__file__).parent
ENV_FILE = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"

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


def ensure_env_template():
    if not ENV_FILE.exists():
        if ENV_EXAMPLE.exists():
            ENV_FILE.write_text(ENV_EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            ENV_FILE.write_text(
                "LLM_API_KEY=\nFEISHU_APP_ID=\nFEISHU_APP_SECRET=\n", encoding="utf-8"
            )
        print(f"✓ 已生成配置文件：{ENV_FILE.name}")
    else:
        print(f"✓ 检测到已有配置文件：{ENV_FILE.name}")


def load_env():
    cfg = {}
    if not ENV_FILE.exists():
        return cfg
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        cfg[k.strip()] = v.strip().strip('"').strip("'")
    return cfg


def set_env_value(key, value):
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines(keepends=True)
    for i, line in enumerate(lines):
        s = line.strip()
        if s and not s.startswith("#") and "=" in s and s.split("=", 1)[0].strip() == key:
            lines[i] = f"{key}={value}\n"
            break
    else:
        lines.append(f"{key}={value}\n")
    ENV_FILE.write_text("".join(lines), encoding="utf-8")


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


def create_bitable_app(token, name, folder_token=""):
    body = {"name": name, "time_zone": "Asia/Shanghai"}
    if folder_token:
        body["folder_token"] = folder_token
    r = requests.post(
        f"{BASE}/open-apis/bitable/v1/apps",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=body,
        timeout=20,
    )
    return r.json()


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
    print("=" * 62)
    print("  dontmissddl 一键部署")
    print("  能自动化的全部自动化；必须手动的最后打印清单提醒你")
    print("=" * 62)
    print()
    print("  前置：请先在飞书开放平台创建好「企业自建应用」，并开通")
    print("        「多维表格读写」权限（必须，用于写表格）。")
    print("        如果要监听飞书群，再额外开通「读取群消息」权限。")
    print()

    ensure_env_template()
    print(f"  请用记事本打开根目录的 {ENV_FILE.name}，填好配置。")
    print("  密钥都在文件里填，不要在对话框输入。")
    print()
    print("  先告诉我你要监控哪些信息源（可多选，用逗号分隔）：")
    print("    1. 飞书群聊    2. 邮箱    3. 公众号（搜狗搜索）")
    print("    直接按回车 = 跳过，稍后自己在 .env 里填")
    choice = input("  你的选择（如 1,3）: ").strip()
    print()

    print("  【必填】写表格用，跟选哪个信息源无关：")
    print("    · LLM_API_KEY           → 你所用大模型平台的 API Key（OpenAI 兼容即可）")
    print("    · FEISHU_APP_ID/SECRET  → open.feishu.cn 自建应用「凭证与基础信息」")
    print()

    if "1" in choice:
        print("  【飞书群聊】填 FEISHU_GROUP_IDS（群 chat_id）：")
        print("    先给应用开「读取群消息」+ 打开「机器人」，把机器人拉进群，")
        print("    然后命令行跑  python -m server.main find-chat  能列出所有群的 chat_id。")
        print()

    if "2" in choice:
        print("  【邮箱】填 EMAIL_HOST / EMAIL_PORT / EMAIL_USER / EMAIL_PASSWORD：")
        print("    QQ 邮箱   → imap.qq.com:993，密码填「授权码」")
        print("    163 邮箱  → imap.163.com:993，密码填「授权码」")
        print("    126 邮箱  → imap.126.com:993，密码填「授权码」")
        print("    Gmail     → imap.gmail.com:993，密码填「应用专用密码」")
        print("    Outlook   → outlook.office365.com:993，密码填「应用密码」")
        print("    授权码在邮箱「设置 → 账户 → 开启 IMAP」里生成。")
        print()

    if "3" in choice:
        print("  【公众号】填 WECHAT_SOGOU_NAMES：")
        print("    就是公众号昵称，多个用英文逗号分隔，如：字节跳动招聘,腾讯招聘。")
        print()

    input("  填好并保存后，回到这里按回车继续...")
    print()

    cfg = load_env()
    required = ["LLM_API_KEY", "FEISHU_APP_ID", "FEISHU_APP_SECRET"]
    missing = [k for k in required if not cfg.get(k)]
    if missing:
        print(f"  ❌ 还缺必填项：{', '.join(missing)}。请填好再重新运行本脚本。")
        input("  按回车退出...")
        return

    sources = [k for k in ("FEISHU_GROUP_IDS", "EMAIL_USER",
                           "WECHAT_SOGOU_NAMES") if cfg.get(k)]
    if not sources:
        print("  ⚠ 你还没配置任何信息源（飞书群 / 邮箱 / 公众号）。")
        print("    建议去 .env 里填一个（FEISHU_GROUP_IDS / EMAIL_USER / WECHAT_SOGOU_NAMES）。")
        print("    也可以先继续，稍后再补。")
        print()

    try:
        token = get_tenant_token(cfg["FEISHU_APP_ID"], cfg["FEISHU_APP_SECRET"])
    except RuntimeError as e:
        print(f"  ❌ {e}")
        input("  按回车退出...")
        return

    app_token = cfg.get("FEISHU_APP_TOKEN", "")
    table_id = cfg.get("FEISHU_TABLE_ID", "")

    if app_token and table_id:
        print("  ✓ 检测到 .env 已配好多维表格，直接使用。")
    else:
        print("  正在自动创建多维表格...")
        name = cfg.get("FEISHU_BITABLE_NAME", "DDL 提醒表")
        res = create_bitable_app(token, name, cfg.get("FEISHU_FOLDER_TOKEN", ""))
        if res.get("code") != 0:
            print(f"  ✗ 创建多维表格失败: {res.get('msg')}")
            print("    请确认已在开放平台开通「多维表格读写」权限，然后重试。")
            input("  按回车退出...")
            return
        app = res.get("data", {}).get("app", res.get("data", {}))
        app_token = app.get("app_token", "")
        table_id = app.get("default_table_id", "")
        url = app.get("url", "")
        if not app_token or not table_id:
            print("  ✗ 创建成功但没拿到 token。请到飞书云空间手动新建一个多维表格，")
            print("    把链接里的 app_token 填到 .env 的 FEISHU_APP_TOKEN，table_id 填 FEISHU_TABLE_ID。")
            input("  按回车退出...")
            return
        set_env_value("FEISHU_APP_TOKEN", app_token)
        set_env_value("FEISHU_TABLE_ID", table_id)
        print("  ✓ 已创建多维表格，并写回 .env。")
        if url:
            print(f"    打开看看：{url}")
    print()

    print("  正在创建字段...")
    existing = list_field_names(token, app_token, table_id)
    for f in FIELDS:
        if f["name"] in existing:
            print(f"    · {f['name']}（已存在，跳过）")
            continue
        res = create_field(token, app_token, table_id, f)
        if res.get("code") == 0:
            print(f"    ✓ {f['name']}")
        else:
            print(f"    ✗ {f['name']} 失败: {res.get('msg')}（可在表格里手动补）")
    print()

    if shutil.which("gh"):
        repo = detect_repo()
        if repo:
            ans = input("  检测到 gh CLI，要帮你把这些配置批量写入 GitHub Secrets 吗？(y/N): ").strip().lower()
            if ans in ("y", "yes"):
                secrets = {k: v for k, v in cfg.items() if v}
                ok = total = 0
                for k, v in secrets.items():
                    total += 1
                    if set_secret(k, v, repo):
                        ok += 1
                        print(f"    ✓ {k}")
                    else:
                        print(f"    ✗ {k} 失败")
                print(f"  已写入 {ok}/{total} 个 Secret")
        else:
            print("  未检测到当前目录是 GitHub 仓库，跳过写 Secrets。")
    else:
        print("  未检测到 gh CLI。稍后请到仓库 Settings → Secrets 手动填（值就在 .env 里）。")
    print()

    print("=" * 62)
    print("  剩下这些必须手动完成（飞书没有开放接口，脚本无法代劳）：")
    print("=" * 62)
    print("  1. 飞书开放平台 → 自建应用：发布应用（可能要管理员审批）。")
    if cfg.get("FEISHU_GROUP_IDS"):
        print("     · 你选了飞书群：记得打开「机器人」能力，并把机器人拉进群。")
    print("  2. 打开刚建的多维表格，加一个公式列「剩余天数」：")
    print('     = DATEDIF(TODAY(), 截止日期, "D")')
    print("  3. 多维表格右上角「工作流」→ 新建 4 个工作流：")
    print("     A. 触发=记录新增 → 发通知（带「完成/忽略」按钮）")
    print("     B. 触发=每天 09:30，条件=剩余天数=7 → 循环逐条发带按钮的卡片")
    print("     C. 同上，剩余天数=3")
    print("     D. 同上，剩余天数=1")
    print("  4. 仓库 Settings → Actions 启用；Actions 页手动触发一次 workflow_dispatch 测试。")
    print()
    print("  完成。之后每天 09:00 自动收集写入，09:30 飞书工作流提醒。")
    print("=" * 62)
    input("  按回车键退出...")


if __name__ == "__main__":
    main()
