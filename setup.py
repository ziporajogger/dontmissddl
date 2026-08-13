"""dontmissddl — 一键部署引导脚本（Windows 下可双击运行）。

职责：能自动化的全部自动化。你只需要在 .env 文件里填好密钥（不要在对话框输入），
剩下的——创建多维表格、创建字段、写 GitHub Secrets——都由本脚本完成。
必须手动的那几步（发布应用、拉群、配自动化等），脚本最后会打印清单提醒你。

用法：
    Windows：双击 setup.py（或 setup.bat）
    其它平台：python setup.py
"""

import shutil
import subprocess
import sys

try:
    import requests
except ImportError:
    print("缺少依赖 requests。请先打开命令行运行：  pip install requests")
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
    print("  前置：请先在飞书开放平台创建好「企业自建应用」，并开通权限：")
    print("        读取群消息、多维表格读写、知识库读取。")
    print("        （否则下面自动建表格会失败。）")
    print()

    ensure_env_template()
    print(f"  请用记事本打开根目录的 {ENV_FILE.name}，填好配置。")
    print("  密钥都在文件里填，不要在对话框输入。")
    print("  必填：LLM_API_KEY、FEISHU_APP_ID、FEISHU_APP_SECRET。")
    input("  填好并保存后，回到这里按回车继续...")
    print()

    cfg = load_env()
    required = ["LLM_API_KEY", "FEISHU_APP_ID", "FEISHU_APP_SECRET"]
    missing = [k for k in required if not cfg.get(k)]
    if missing:
        print(f"  ❌ 还缺必填项：{', '.join(missing)}。请填好再重新运行本脚本。")
        input("  按回车退出...")
        return

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
    print("  1. 飞书开放平台 → 自建应用：打开「机器人」能力，然后发布应用")
    print("     （可能需要管理员审批）。")
    print("  2. 把机器人拉进要监听的飞书群，确认 .env 里 FEISHU_GROUP_IDS 填对。")
    print("  3. 打开刚建的多维表格，加一个公式列「剩余天数」：")
    print('     = DATEDIF(TODAY(), 截止日期, "D")')
    print("  4. 多维表格右上角「自动化」→ 新建两条规则：")
    print("     A. 触发=记录新增 → 发通知")
    print("     B. 触发=每天 09:30，条件=剩余天数∈{7,3,1} → 发带「完成/忽略」按钮的卡片")
    print("  5. 仓库 Settings → Actions 启用；Actions 页手动触发一次 workflow_dispatch 测试。")
    print()
    print("  完成。之后每天 09:00 自动收集写入，09:30 飞书自动化提醒。")
    print("=" * 62)
    input("  按回车键退出...")


if __name__ == "__main__":
    main()
