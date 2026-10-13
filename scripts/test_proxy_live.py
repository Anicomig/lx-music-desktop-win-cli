"""代理三向验证：确认"本机绕过代理 + 外网走代理"分工正确。

前置：系统代理开启（127.0.0.1:7890）、LX 运行、开放 API 启用。
**不设 NO_PROXY** —— 全靠代码里的 _local_session() 生效。
"""
import json
import os
import subprocess
import sys
import urllib.request

CLI = ["python", "run.py"]
CWD = r"C:\Users\EDY\Documents\workspace\LX-CLI-project\lx-cli-v2"
ENV = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
ENV["PYTHONIOENCODING"] = "utf-8"
# 明确清掉任何绕过代理的环境变量，保证测的是代码而非环境
for v in ("NO_PROXY", "no_proxy", "HTTP_PROXY", "HTTPS_PROXY",
          "http_proxy", "https_proxy"):
    ENV.pop(v, None)

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  [{'OK ' if ok else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))


def lx(*args, timeout=60):
    p = subprocess.run(CLI + list(args), cwd=CWD, env=ENV,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout)
    return p.returncode, p.stdout, p.stderr


print("=== 0. 环境确认 ===")
proxies = urllib.request.getproxies()
print(f"  系统代理: {proxies}")
check("系统代理已开启", bool(proxies), str(proxies.get("http", "")))
for v in ("NO_PROXY", "no_proxy", "HTTP_PROXY", "http_proxy"):
    assert v not in ENV, f"{v} 不应存在"
print("  NO_PROXY 未设（好：测的是代码而非环境）")

print("\n=== 1. 本机向：Open API 必须绕过代理 ===")
code, out, err = lx("status", "--json")
if code == 0:
    d = json.loads(out)
    check("lx status 成功（无 502）", True,
          f"status={d.get('status')!r} name={d.get('name', '')[:20]}")
    check("返回真实曲目", bool(d.get("name")), d.get("name", "")[:30])
else:
    check("lx status 成功（无 502）", False, f"exit={code} {err[:120]}")

# 直接验证 _local_session 的 trust_env
code, out, err = lx("-vv", "status", "--json") if False else (0, "", "")
sys.path.insert(0, os.path.join(CWD, "src"))
from lx_cli.core.openapi_client import _local_session  # noqa: E402
s = _local_session()
check("_local_session.trust_env=False", s.trust_env is False, f"trust_env={s.trust_env}")

# 反向证明：全局会话确实会用代理（说明这个修复是必要的）
from lx_cli.core.http import get_session  # noqa: E402
gs = get_session()
check("全局会话仍走代理（搜索需要）", gs.trust_env is True,
      f"trust_env={gs.trust_env}")

print("\n=== 2. 外网向：搜索必须走代理 ===")
code, out, err = lx("search", "yorushika", "--limit", "2", "--json")
if code == 0:
    d = json.loads(out)
    plats = d.get("platforms", [])
    total = d.get("count", 0)
    check("lx search 成功（走代理）", total > 0,
          f"{total} 首，平台={len(plats)}")
    check("多平台可用", len(plats) >= 3, f"platforms={plats}")
else:
    check("lx search 成功（走代理）", False, f"exit={code} {err[:120]}")

print("\n=== 3. 反证：什么情况下本机请求会失败 ===")
# 实测事实：requests 对 127.0.0.1 自动豁免代理（proxy_bypass=True），
# 所以"走代理请求 127.0.0.1"不会失败 —— 这正是要澄清的认知点。
import urllib.request
bypass127 = urllib.request.proxy_bypass("127.0.0.1")
bypass0000 = urllib.request.proxy_bypass("0.0.0.0")
check("requests 对 127.0.0.1 豁免代理", bypass127 is True,
      f"proxy_bypass('127.0.0.1')={bypass127}")
check("requests 对 0.0.0.0 不豁免（会走代理）", bypass0000 is False,
      f"proxy_bypass('0.0.0.0')={bypass0000}")

# 真正会 502 的是 0.0.0.0 —— 证明旧代码的 host 才是真凶
try:
    r = urllib.request.urlopen("http://0.0.0.0:23330/status", timeout=8)
    code0000 = r.status
except urllib.error.HTTPError as e:
    code0000 = e.code
except Exception as e:
    code0000 = f"{type(e).__name__}"
check("★ 连 0.0.0.0 会失败（证实旧代码 502 根因）", code0000 == 502,
      f"http://0.0.0.0:23330 -> {code0000}")

# 而 127.0.0.1 正常
try:
    r = urllib.request.urlopen("http://127.0.0.1:23330/status", timeout=8)
    code127 = r.status
except Exception as e:
    code127 = f"{type(e).__name__}"
check("★ 连 127.0.0.1 正常", code127 == 200,
      f"http://127.0.0.1:23330 -> {code127}")

print("\n=== 4. lx doctor 全项 ===")
code, out, err = lx("doctor", "--json", timeout=120)
if code in (0, 1, 2):
    d = json.loads(out)
    for c in d["checks"]:
        mark = {"ok": "OK ", "warn": "WARN", "fail": "FAIL", "skip": "SKIP"}[c["status"]]
        print(f"    [{mark}] {c['name']}")
        if c["status"] == "fail":
            print(f"           → {c.get('fix_hint', '')}")
    n_fail = sum(1 for c in d["checks"] if c["status"] == "fail")
    check("doctor 无 fail", n_fail == 0, f"{n_fail} 个 fail")
    # 关键：验证本机(api.reach) 与 外网(net.search) 同时 ok
    by_id = {c["id"]: c for c in d["checks"]}
    check("★ 本机 API 连通 = ok", by_id.get("api.reach", {}).get("status") == "ok",
          by_id.get("api.reach", {}).get("name", ""))
    check("★ 外网搜索 = ok", by_id.get("net.search", {}).get("status") == "ok",
          by_id.get("net.search", {}).get("name", ""))
else:
    check("doctor 可运行", False, f"exit={code}")

print("\n=== 5. 其它本机命令 ===")
code, out, err = lx("lyric", "--json")
check("lx lyric（本机，无 502）", code == 0,
      (json.loads(out).get("lyric", "")[:20] if code == 0 else err[:60]))

code, out, err = lx("db", "stats", "--json")
check("lx db stats（只读）", code == 0,
      (f"{json.loads(out).get('lists')} 歌单" if code == 0 else err[:60]))

passed = sum(1 for _, ok, _ in results if ok)
total = len(results)
print(f"\n{'='*60}")
print(f"=== {passed}/{total} 通过 ===")
if passed != total:
    print("失败项：")
    for n, ok, d in results:
        if not ok:
            print(f"  - {n}  {d}")
sys.exit(0 if passed == total else 1)
