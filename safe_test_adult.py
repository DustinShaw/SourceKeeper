# -*- coding: utf-8 -*-
"""安全测试：复制真实仓库到临时目录，对临时副本跑 --adult-scan --write，
验证标注结果，并断言真实 py.json 字节未变（md5 不变）。全程不改动真实文件。"""
import os
import sys
import shutil
import hashlib
import subprocess
import tempfile
import importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
INJ = os.path.join(HERE, "injector.py")
REAL_CFG = os.path.join(HERE, "py.json")
REAL_PY = os.path.join(HERE, "py")

# 真实文件快照（写保护：全程只读真实文件）
real_md5_before = hashlib.md5(open(REAL_CFG, "rb").read()).hexdigest()

tmp = tempfile.mkdtemp(prefix="pyinj_test_")
try:
    shutil.copy2(REAL_CFG, os.path.join(tmp, "py.json"))
    shutil.copytree(REAL_PY, os.path.join(tmp, "py"))
    print("临时仓库: %s" % tmp)

    # 跑真实 injector 的 CLI（对临时副本）
    env = dict(os.environ)
    py = sys.executable
    proc = subprocess.run(
        [py, INJ, "--repo", tmp, "--adult-scan", "--write"],
        capture_output=True, env=env,
    )
    out = (proc.stdout or b"").decode("utf-8", "replace")
    err = (proc.stderr or b"").decode("utf-8", "replace")
    print("--- CLI 输出 ---")
    print(out)
    if err.strip():
        print("--- CLI stderr ---")
        print(err)
    print("rc=%d" % proc.returncode)

    # 解析临时副本结果
    spec = importlib.util.spec_from_file_location("inj", INJ)
    inj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(inj)
    raw, sites, _, _ = inj.load_repo(tmp)
    adult_keys = [s.get("key") for s in sites if str(s.get("adult", "0")) == "1"]
    print("\n临时副本中 adult=1 的站点 (%d 个):" % len(adult_keys))
    for k in adult_keys:
        print("  - %s" % k)

    # 断言真实文件未被改动
    real_md5_after = hashlib.md5(open(REAL_CFG, "rb").read()).hexdigest()
    if real_md5_before == real_md5_after:
        print("\n✓ 真实 py.json 字节未变 (md5 一致): %s" % real_md5_before)
    else:
        print("\n✗ 严重：真实 py.json 被改动！before=%s after=%s" % (real_md5_before, real_md5_after))
        raise SystemExit(1)
finally:
    shutil.rmtree(tmp, ignore_errors=True)
    print("已清理临时仓库: %s" % tmp)
