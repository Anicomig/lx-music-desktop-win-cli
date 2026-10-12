"""端到端验收：音源脚本管理（安装 / 更新 / 删除 / 校验）。

在**真实 user_api.json 的副本**上跑，不碰原始文件。
重点验证：
  1. 8 个真实脚本全部能正确解码（gz_ + zlib，不是 gzip）
  2. 安装 → 保留原 id 的更新 → 删除
  3. 手改保护（无 --force 时拒绝覆盖）
  4. 编码往返无损（decode(encode(x)) == x）
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REAL = Path(os.environ["APPDATA"]) / "lx-music-desktop" / "LxDatas" / "user_api.json"
ENV = {**os.environ, "PYTHONPATH": str(ROOT / "src"),
       "PYTHONIOENCODING": "utf-8"}


def lx(*args: str) -> tuple[int, str, str]:
    p = subprocess.run([sys.executable, "-m", "lx_cli", *args],
                       capture_output=True, text=True, encoding="utf-8",
                       env=ENV, cwd=str(ROOT))
    return p.returncode, p.stdout, p.stderr


def main() -> int:
    sys.path.insert(0, str(ROOT / "src"))
    from lx_cli.scripts import store
    from lx_cli.scripts.metadata import parse_script_meta

    ok = True
    tmp = Path(tempfile.mkdtemp(prefix="lxscript_"))
    ua = tmp / "user_api.json"
    meta = tmp / "scripts_meta.json"
    shutil.copy2(REAL, ua)
    print(f"副本: {ua}\n")

    # 记录真实文件基线（全程不得变化）
    import hashlib as _hashlib
    real_sha_before = _hashlib.sha256(REAL.read_bytes()).hexdigest()
    print(f"真实文件基线 sha256 = {real_sha_before[:16]}…（全程应保持不变）\n")

    # ---- 1. 解码全部真实脚本 ----
    print("[1] 解码真实脚本（gz_ + zlib）")
    entries = store.load_entries(path=ua)
    print(f"    共 {len(entries)} 个")
    bad = 0
    for e in entries:
        if not e.script:
            print(f"    ✗ {e.name}: 解码失败")
            bad += 1
            continue
        m = parse_script_meta(e.script)
        has_head = e.script.lstrip().startswith("/*")
        if not has_head:
            print(f"    ✗ {e.name}: 缺少头部注释块")
            bad += 1
        # 往返无损
        if store.decode_script(store.encode_script(e.script)) != e.script:
            print(f"    ✗ {e.name}: 编解码往返不一致")
            bad += 1
    print(f"    解码失败/异常: {bad}")
    ok &= bad == 0

    # ---- 2. 安装一个假脚本 ----
    # ⚠️ 安全：**必须**显式传 path/meta_path，否则 CLI 会读默认的真实
    #    %APPDATA% 路径并写坏真实数据（已踩过这个坑）。
    print("\n[2] 安装一个测试脚本（仅作用于副本）")
    fake = tmp / "fake.js"
    fake.write_text(
        "/*!\n"
        " * @name 测试音源A\n"
        " * @description 用于验收\n"
        " * @version 1.0.0\n"
        " * @author tester\n"
        " */\n"
        "(function(){ /* 假实现 */ })();\n",
        encoding="utf-8")
    from lx_cli.scripts import service
    plan = service.install_from_file(fake, path=ua, meta_path=meta,
                                     force=True, dry_run=False)
    print(f"    plan: action={plan.action} id={plan.entry_id}")
    entries2 = store.load_entries(path=ua)
    print(f"    安装后脚本数 = {len(entries2)}（应为 {len(entries) + 1}）")
    ok &= len(entries2) == len(entries) + 1
    # 确认真实文件没被动
    import hashlib as _h
    real_sha_now = _h.sha256(REAL.read_bytes()).hexdigest()
    ok &= real_sha_now == real_sha_before
    print(f"    真实文件未被改动: {'是' if real_sha_now == real_sha_before else '否 ✗'}")

    # ---- 3. 更新：保留 id ----
    print("\n[3] 更新（内容变化，应保留原 id）")
    fake.write_text(fake.read_text(encoding="utf-8").replace(
        "@version 1.0.0", "@version 2.0.0").replace(
        "假实现", "新实现"), encoding="utf-8")
    plan2 = service.install_from_file(fake, path=ua, meta_path=meta,
                                      force=True, dry_run=False)
    print(f"    action={plan2.action}  id={plan2.entry_id}")
    print(f"    old_sha={plan2.old_sha[:12]}…  new_sha={plan2.new_sha[:12]}…")
    ok &= plan2.action == "update"
    id_kept = plan2.entry_id == plan.entry_id
    ok &= id_kept
    print(f"    id 保持不变: {'是' if id_kept else '否 ✗ ' + plan2.entry_id}")

    # ---- 4. 幂等：内容相同应跳过 ----
    print("\n[4] 再次更新（内容相同 → 应 skip）")
    plan3 = service.install_from_file(fake, path=ua, meta_path=meta,
                                      force=True, dry_run=False)
    print(f"    action={plan3.action}  reason={plan3.reason}")
    ok &= plan3.action == "skip"

    # ---- 5. 手改保护 ----
    print("\n[5] 手改保护（改脚本内容后不带 --force 更新）")
    entries3 = store.load_entries(path=ua)
    target = next(e for e in entries3 if e.name == "测试音源A")
    # 手动改内容但**不更新** CLI 记录的哈希 → 模拟"用户手改"
    target.script = target.script + "\n// 用户手动加的一行\n"
    target.script_encoded = store.encode_script(target.script)
    store.save_entries(entries3, path=ua, check_running=False)

    fake.write_text(fake.read_text(encoding="utf-8").replace(
        "@version 2.0.0", "@version 3.0.0"), encoding="utf-8")
    try:
        service.install_from_file(fake, path=ua, meta_path=meta,
                                  force=False, dry_run=False)
        print("    ✗ 未被拦截（应当报错）")
        ok = False
    except Exception as exc:
        print(f"    已拦截: {type(exc).__name__}")
        print(f"      {str(exc).splitlines()[0]}")

    # ---- 6. 删除 ----
    print("\n[6] 删除测试脚本")
    plan4 = service.remove("测试音源A", path=ua, meta_path=meta, force=True)
    entries4 = store.load_entries(path=ua)
    print(f"    action={plan4.action}  剩余={len(entries4)}（应为 {len(entries)}）")
    ok &= len(entries4) == len(entries)

    # ---- 7. 原始文件未被改 ----
    print("\n[7] 原始 user_api.json 是否被改动")
    real_sha_after = _hashlib.sha256(REAL.read_bytes()).hexdigest()
    unchanged = real_sha_after == real_sha_before
    print(f"    基线 = {real_sha_before[:16]}…")
    print(f"    现在 = {real_sha_after[:16]}…")
    print(f"    未被改动: {'是' if unchanged else '否 ✗'}")
    ok &= unchanged

    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n结论：{'全部通过' if ok else '存在失败项'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
