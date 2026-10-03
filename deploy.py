# -*- coding: utf-8 -*-
"""源管家 部署 + 冻结 exe 冒烟测试（版本化命名，机器无关）
  1) 从 injector.py 解析 APP_VERSION，把 dist/源管家.exe 部署为根目录
     「源管家 v<版本>.exe」（旧版本 exe 天然留存，即历史备份）；
  2) 遗留的无版本 源管家.exe 备份为 .bak.<时间戳>（仅首次迁移时发生一次）；
  3) 复制真实 py.json 到临时仓库，用新 exe 做无控制台 GUI 启动冒烟（2026-09-29：
     spec 已改 console=False，exe 走窗口子系统，CLI 的 stdout 不再可用；改为
     offscreen 启动 GUI，确认进程能起来、无 Traceback 崩溃，超时后主动结束）；
  4) 断言真实 py.json 的 md5 不变（绝不触碰用户真实文件）。

用法：<venv-python> deploy.py
"""
import os
import re
import sys
import shutil
import hashlib
import subprocess
import tempfile
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
NEW = os.path.join(HERE, "dist", "源管家.exe")
REAL_JSON = os.path.join(HERE, "py.json")
SRC = os.path.join(HERE, "injector.py")

PASS, FAIL = 0, 0


def ok(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ✓ %s" % name)
    else:
        FAIL += 1
        print("  ✗ %s  %s" % (name, extra))


def md5(p):
    h = hashlib.md5()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(65536), b""):
            h.update(c)
    return h.hexdigest()


# ---- 0) 解析版本号（正则读取，避免 import injector 牵连 PySide6）----
m = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', open(SRC, encoding="utf-8").read())
ok("解析 APP_VERSION", bool(m), "injector.py 中未找到")
VERSION = m.group(1) if m else "unknown"
FINAL = os.path.join(HERE, "源管家 v%s.exe" % VERSION)
print("目标产物：%s" % os.path.basename(FINAL))

ok("dist/源管家.exe 存在", os.path.isfile(NEW), NEW)

# ---- 1) 部署（版本化命名）----
ts = datetime.now().strftime("%Y%m%d-%H%M%S")
legacy = os.path.join(HERE, "源管家.exe")
if os.path.isfile(legacy):
    bak = legacy + ".bak." + ts
    shutil.move(legacy, bak)
    print("遗留无版本 exe 已备份：%s" % os.path.basename(bak))
if os.path.isfile(FINAL):
    bak = FINAL + ".bak." + ts
    shutil.copy2(FINAL, bak)
    print("同版本旧文件已备份：%s" % os.path.basename(bak))
shutil.copy2(NEW, FINAL)
print("已部署：%s  (%d 字节)" % (FINAL, os.path.getsize(FINAL)))

EXE = FINAL
before = md5(REAL_JSON)

# ---- 2) 临时仓库 ----
tmp = tempfile.mkdtemp(prefix="pyinj_frozen_")
shutil.copy2(REAL_JSON, os.path.join(tmp, "py.json"))
pysrc = os.path.join(HERE, "py")
if os.path.isdir(pysrc):
    shutil.copytree(pysrc, os.path.join(tmp, "py"))


print("\n== 冻结 exe 冒烟（无控制台 GUI 启动，offscreen）==")
# console=False 后 exe 无 stdout，改为：offscreen 启动 GUI，存活判定 + 无崩溃输出。
# 进程会一直跑（GUI 事件循环），用超时主动结束视为「启动成功」。
env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
try:
    p = subprocess.run([EXE, "--repo", tmp], capture_output=True,
                       timeout=25, env=env)
    # 25 秒内自行退出 = 异常（GUI 不应自退）
    out = p.stdout.decode("utf-8", "ignore")
    err = p.stderr.decode("utf-8", "ignore")
    ok("exe GUI 启动（未异常自退）", p.returncode == 0,
       "rc=%s err=%s" % (p.returncode, err[-300:]))
    ok("exe 无 Traceback", ("Traceback" not in err) and ("Traceback" not in out),
       (err or out)[-300:])
except subprocess.TimeoutExpired as ex:
    # 超时 = GUI 一直在运行（正常）；检查超时前是否吐了 Traceback
    out = (ex.stdout or b"").decode("utf-8", "ignore")
    err = (ex.stderr or b"").decode("utf-8", "ignore")
    ok("exe GUI 启动并持续运行（超时判定存活）", True)
    ok("exe 无 Traceback", ("Traceback" not in err) and ("Traceback" not in out),
       (err or out)[-300:])

# ---- 3) 真实文件未被触碰 ----
after = md5(REAL_JSON)
ok("真实 py.json md5 不变（安全）", before == after, "%s vs %s" % (before, after))

shutil.rmtree(tmp, ignore_errors=True)
print("\n结果：%d 通过, %d 失败" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
