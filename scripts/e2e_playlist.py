"""端到端验收：搜索 → 对比 → 插入（需求 D 主路径）。

在**夹具副本**上跑，不碰真实数据。演示：
  1. 新建歌单
  2. dry-run 报告（不写库）
  3. --apply 写入
  4. 核对结果
  5. 幂等性（再跑一次不应重复插入）
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent      # scripts/ -> 项目根
FIXTURE = ROOT / "tests" / "fixtures" / "lx.data.db"
ENV = {**os.environ, "PYTHONPATH": str(ROOT / "src"),
       "PYTHONIOENCODING": "utf-8"}

# 用多平台：单靠 kg 会因连续请求被限流，导致误判为"无结果"
SRC_ARGS = ["--sources", "kw,wy", "--limit", "5"]


def lx(*args: str) -> tuple[int, str, str]:
    p = subprocess.run([sys.executable, "-m", "lx_cli", *args],
                       capture_output=True, text=True, encoding="utf-8",
                       env=ENV, cwd=str(ROOT))
    return p.returncode, p.stdout, p.stderr


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="lxe2e_"))
    db = tmp / "lx.data.db"
    shutil.copy2(FIXTURE, db)
    print(f"夹具副本: {db}\n")

    # ---- 1. 新建歌单 ----
    code, out, err = lx("--db", str(db), "playlist", "create", "验收歌单", "--force")
    print(f"[1] 新建歌单  exit={code}")
    print("   ", out.strip() or err.strip())

    code, out, _ = lx("--db", str(db), "playlist", "list", "--json")
    lists = json.loads(out)["lists"]
    target = next((x for x in lists if x["name"] == "验收歌单"), None)
    assert target, "新歌单未找到"
    lid = target["id"]
    print(f"    id={lid}  歌曲数={target['songCount']}\n")

    # ---- 2. dry-run ----
    code, out, err = lx("--db", str(db), "playlist", "add", lid,
                        "--from-search", "yorushika", *SRC_ARGS, "--force")
    print(f"[2] dry-run  exit={code}")
    print("   ", out.strip().replace("\n", "\n    ")[:700], "\n")

    code, out, _ = lx("--db", str(db), "playlist", "list", "--json")
    after_dry = next(x for x in json.loads(out)["lists"] if x["id"] == lid)
    print(f"    dry-run 后歌曲数 = {after_dry['songCount']}（应仍为 0）\n")

    # ---- 3. apply ----
    time.sleep(2)
    code, out, err = lx("--db", str(db), "playlist", "add", lid,
                        "--from-search", "yorushika", *SRC_ARGS,
                        "--apply", "--force")
    print(f"[3] apply  exit={code}")
    print("   ", out.strip().replace("\n", "\n    ")[:700], "\n")

    code, out, _ = lx("--db", str(db), "playlist", "list", "--json")
    after_apply = next(x for x in json.loads(out)["lists"] if x["id"] == lid)
    print(f"    写入后歌曲数 = {after_apply['songCount']}\n")

    # ---- 4. 核对内容 ----
    code, out, _ = lx("--db", str(db), "playlist", "show", lid, "--json")
    shown = json.loads(out)
    print(f"[4] show  exit={code}  共 {shown['count']} 首")
    for s in shown["songs"][:4]:
        meta = json.loads(s.get("meta") or "{}")
        print(f"    {s['name']} - {s['singer']}  [{s['source']}]"
              f"  album={meta.get('albumName')!r}")
        print(f"      id={s['id']}")
    print()

    # ---- 5. 幂等性 ----
    time.sleep(2)
    code, out, err = lx("--db", str(db), "playlist", "add", lid,
                        "--from-search", "yorushika", *SRC_ARGS,
                        "--apply", "--force")
    print(f"[5] 再 apply 一次（幂等性）exit={code}")
    code, out2, _ = lx("--db", str(db), "playlist", "list", "--json")
    after_again = next(x for x in json.loads(out2)["lists"] if x["id"] == lid)
    print(f"    歌曲数 = {after_again['songCount']}（应与上面相同）")

    before = after_apply["songCount"]
    idem_ok = after_again["songCount"] == before and before > 0
    print(f"    幂等性: {'通过' if idem_ok else '失败（重复插入或未写入）'}")

    shutil.rmtree(tmp, ignore_errors=True)
    print("\n完成。")
    return 0 if idem_ok else 1


if __name__ == "__main__":
    sys.exit(main())
