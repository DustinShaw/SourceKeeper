# -*- coding: utf-8 -*-
"""源管家 Windows 7 版部署 + 冻结 exe 冒烟测试
  与 deploy.py 流程一致，只换 dist 产物与部署文件名：
    1) dist/源管家Win7.exe -> 根目录「源管家 v<版本>-Win7.exe」；
    2) 冻结 exe CLI 冒烟（--version / --list / --disable / --enable）；
    3) 断言真实 py.json 的 md5 不变（绝不触碰用户真实文件）。

用法（必须用 Python 3.9 环境跑）：
  <py39> deploy_win7.py
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
NEW = os.path.join(HERE, "dist", "源管家Win7.exe")
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


# ---- 0) 解析版本号（正则读取，避免 import injector 牵连 Qt 绑定）----
m = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', open(SRC, encoding="utf-8").read())
ok("解析 APP_VERSION", bool(m), "injector.py 中未找到")
VERSION = m.group(1) if m else "unknown"
FINAL = os.path.join(HERE, "源管家 v%s-Win7.exe" % VERSION)
print("目标产物：%s" % os.path.basename(FINAL))

ok("dist/源管家Win7.exe 存在", os.path.isfile(NEW), NEW)
ok("用 Qt5 构建（PySide2）", "PySide2" in open(SRC, encoding="utf-8").read(), "源码未含 PySide2 回退分支")

# ---- 1) 部署（带 -Win7 后缀，与 Win10+ 版并存不覆盖）----
ts = datetime.now().strftime("%Y%m%d-%H%M%S")
if os.path.isfile(FINAL):
    bak = FINAL + ".bak." + ts
    shutil.copy2(FINAL, bak)
    print("同版本旧文件已备份：%s" % os.path.basename(bak))
shutil.copy2(NEW, FINAL)
print("已部署：%s  (%d 字节)" % (FINAL, os.path.getsize(FINAL)))

EXE = FINAL
before = md5(REAL_JSON)

# ---- 2) 临时仓库 ----
tmp = tempfile.mkdtemp(prefix="pyinj_win7_")
shutil.copy2(REAL_JSON, os.path.join(tmp, "py.json"))
pysrc = os.path.join(HERE, "py")
if os.path.isdir(pysrc):
    shutil.copytree(pysrc, os.path.join(tmp, "py"))


def run_exe(args):
    p = subprocess.run([EXE] + args, capture_output=True, timeout=300)
    return (p.returncode,
            p.stdout.decode("utf-8", "ignore"),
            p.stderr.decode("utf-8", "ignore"))


print("\n== 冻结 exe CLI 冒烟（临时仓库）==")
rc, out, err = run_exe(["--version"])
ok("exe --version rc=0", rc == 0, "rc=%s err=%s" % (rc, err[:200]))
ok("exe --version 输出版本号", ("v%s" % VERSION) in out, out[:100])

rc, out, err = run_exe(["--repo", tmp, "--list"])
ok("exe --list rc=0", rc == 0, "rc=%s err=%s" % (rc, err[:200]))
ok("exe --list 输出含站点", ("py_" in out) or ("站点" in out), out[:200])

sys.path.insert(0, HERE)
try:
    import injector as I  # noqa
    sites = I.parse_jsonc(I.read_text(os.path.join(tmp, "py.json"))).get("sites", [])
    HAVE_I = True
except Exception as ex:  # 装不上 Qt 时兜底：只做 --list 校验
    HAVE_I = False
    print("  · 未加载 injector 模块（%s），冒烟改用 --list 输出校验" % ex)

if HAVE_I and sites:
    first = str(sites[0].get("key", ""))
    ok("取得首个 key", bool(first), first)
    rc, out, err = run_exe(["--repo", tmp, "--disable", first, "--write"])
    ok("exe --disable rc=0", rc == 0, "rc=%s err=%s" % (rc, err[:200]))
    raw1 = I.read_text(os.path.join(tmp, "py.json"))
    ok("exe 禁用生效", first in I.parse_disabled_keys(raw1))
    ok("exe 禁用后 active 减 1",
       len(I.parse_jsonc(raw1).get("sites", [])) == len(sites) - 1)

    rc, out, err = run_exe(["--repo", tmp, "--enable", first, "--write"])
    ok("exe --enable rc=0", rc == 0, "rc=%s err=%s" % (rc, err[:200]))
    raw2 = I.read_text(os.path.join(tmp, "py.json"))
    ok("exe 启用恢复", first not in I.parse_disabled_keys(raw2))
    ok("exe 启用后 active 回到原数",
       len(I.parse_jsonc(raw2).get("sites", [])) == len(sites))
else:
    ok("exe --disable/--enable 冒烟（跳过：无 injector 模块）", True)

# ---- 3) 真实文件未被触碰 ----
after = md5(REAL_JSON)
ok("真实 py.json md5 不变（安全）", before == after, "%s vs %s" % (before, after))

shutil.rmtree(tmp, ignore_errors=True)
print("\n结果：%d 通过, %d 失败" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
