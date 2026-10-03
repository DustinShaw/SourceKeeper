# -*- coding: utf-8 -*-
"""部署脚本：把 dist/PyInjector.exe 安全替换根目录 PyInjector.exe。
- 旧 exe 先备份为 .bak.<时间戳>
- 若旧 exe 被占用（用户开着窗口），则存为 PyInjector-v7.exe 并提示
- 不改动任何 py.json
"""
import os, shutil, hashlib, subprocess, sys, tempfile, importlib.util, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(HERE, "dist", "PyInjector.exe")
ROOT = os.path.join(HERE, "PyInjector.exe")

print("dist exe exists: %s  size=%d" % (os.path.exists(DIST), os.path.getsize(DIST) if os.path.exists(DIST) else -1))

# 1) 备份旧 exe（若存在且未被占用）
if os.path.exists(ROOT):
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = ROOT + ".bak." + ts
    try:
        shutil.copy2(ROOT, bak)
        print("已备份旧 exe: %s" % os.path.basename(bak))
    except PermissionError:
        print("⚠ 旧 exe 被占用，无法备份/覆盖（用户可能开着窗口）。将另存为 PyInjector-v7.exe")
        v7 = os.path.join(HERE, "PyInjector-v7.exe")
        shutil.copy2(DIST, v7)
        print("已生成: %s  (请关闭旧窗口后手动替换)" % os.path.basename(v7))
        sys.exit(0)
    except Exception as e:
        print("备份旧 exe 失败: %s" % e)
        sys.exit(1)

# 2) 覆盖根目录 exe
try:
    shutil.copy2(DIST, ROOT)
    print("✓ 已替换根目录 PyInjector.exe  size=%d" % os.path.getsize(ROOT))
except PermissionError:
    print("⚠ 根目录 PyInjector.exe 被占用，无法覆盖。另存为 PyInjector-v7.exe")
    v7 = os.path.join(HERE, "PyInjector-v7.exe")
    shutil.copy2(DIST, v7)
    print("已生成: %s" % os.path.basename(v7))
    sys.exit(0)

# 3) 终测：对临时副本跑真实 exe 的 --adult-scan --write，验证冻结二进制可用 + 真实文件不变
REAL_CFG = os.path.join(HERE, "py.json")
real_md5 = hashlib.md5(open(REAL_CFG, "rb").read()).hexdigest()
tmp = tempfile.mkdtemp(prefix="pyinj_deploy_")
try:
    shutil.copy2(REAL_CFG, os.path.join(tmp, "py.json"))
    shutil.copytree(os.path.join(HERE, "py"), os.path.join(tmp, "py"))
    proc = subprocess.run([ROOT, "--repo", tmp, "--adult-scan", "--write"],
                          capture_output=True)
    out = (proc.stdout or b"").decode("utf-8", "replace")
    # 仅打印关键行
    for line in out.splitlines():
        if "成人" in line or "标注" in line or "备份" in line or "仓库" in line or "现有" in line:
            print("   " + line)
    print("exe rc=%d" % proc.returncode)
    # 解析临时副本
    spec = importlib.util.spec_from_file_location("inj", os.path.join(HERE, "injector.py"))
    inj = importlib.util.module_from_spec(spec); spec.loader.exec_module(inj)
    _, sites, _, _ = inj.load_repo(tmp)
    n = sum(1 for s in sites if str(s.get("adult", "0")) == "1")
    print("临时副本 adult=1 数: %d" % n)
    after = hashlib.md5(open(REAL_CFG, "rb").read()).hexdigest()
    if real_md5 == after:
        print("✓ 真实 py.json 未改动 (md5 一致)")
    else:
        print("✗ 真实 py.json 被改动！")
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print("部署完成。")
