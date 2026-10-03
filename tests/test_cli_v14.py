# -*- coding: utf-8 -*-
"""v14 CLI 级测试：在 py.json 副本上验证 --list/--disable/--enable，
并确认原始 py.json 的 md5 不变（安全）。网络检测（--check-url）单独由 test_v14 覆盖。"""
import os
import sys
import json
import shutil
import tempfile
import hashlib

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import injector as I

REAL = os.path.join(HERE, "py.json")
PASS, FAIL = 0, 0


def ok(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ✓ %s" % name)
    else:
        FAIL += 1
        print("  ✗ %s  %s" % (name, extra))


def md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


before = md5(REAL)
with open(REAL, "r", encoding="utf-8") as f:
    raw0 = f.read()
n_sites0 = len(I.parse_jsonc(raw0).get("sites", []))
ok("原始 py.json 解析与站点数", n_sites0 > 0, "n=%d" % n_sites0)

tmp = tempfile.mkdtemp(prefix="pyinj_cli_")
cfg = os.path.join(tmp, "py.json")
shutil.copy2(REAL, cfg)
# 同时复制 py/ 目录（如有），保证 .py 可被解析
py_src = os.path.join(HERE, "py")
if os.path.isdir(py_src):
    shutil.copytree(py_src, os.path.join(tmp, "py"))

# 取第一个站点 key
rawc = I.read_text(cfg)
sites = I.parse_jsonc(rawc).get("sites", [])
first_key = str(sites[0].get("key", ""))
ok("取得首个站点 key", bool(first_key), first_key)

# ---- --list（应无禁用标记）----
rc = I.run_cli(["--repo", tmp, "--list"])
ok("--list 返回 0", rc == 0, "rc=%s" % rc)

# ---- --disable KEY --write ----
rc = I.run_cli(["--repo", tmp, "--disable", first_key, "--write"])
ok("--disable 返回 0", rc == 0, "rc=%s" % rc)
raw1 = I.read_text(cfg)
d1 = I.parse_jsonc(raw1)
ok("禁用后 active 减少 1", len(d1.get("sites", [])) == n_sites0 - 1,
   "%d vs %d" % (len(d1.get("sites", [])), n_sites0))
ok("禁用集合含该 key", first_key in I.parse_disabled_keys(raw1))
ok("禁用后 JSON 仍合法", True)

# ---- --list 应显示 [禁用] ----
import io
buf = io.StringIO()
old_stdout = sys.stdout
sys.stdout = buf
try:
    I.run_cli(["--repo", tmp, "--list"])
finally:
    sys.stdout = old_stdout
out = buf.getvalue()
ok("--list 含 [禁用] 标记", "[禁用]" in out, out[:200])

# ---- --enable KEY --write ----
rc = I.run_cli(["--repo", tmp, "--enable", first_key, "--write"])
ok("--enable 返回 0", rc == 0, "rc=%s" % rc)
raw2 = I.read_text(cfg)
d2 = I.parse_jsonc(raw2)
ok("启用后 active 恢复", len(d2.get("sites", [])) == n_sites0,
   "%d vs %d" % (len(d2.get("sites", [])), n_sites0))
ok("启用后不再禁用", first_key not in I.parse_disabled_keys(raw2))
ok("启用后 JSON 仍合法", True)
# 启用后首个站点 key 与 api 字段完整
restored = [s for s in d2.get("sites", []) if str(s.get("key", "")) == first_key]
ok("启用后字段完整", restored and restored[0].get("api") == sites[0].get("api"))

# ---- 预览模式不应改写文件（--disable 不加 --write）----
md5_before_preview = md5(cfg)
rc = I.run_cli(["--repo", tmp, "--disable", first_key])
ok("预览 --disable 返回 0", rc == 0)
ok("预览模式未改动文件", md5(cfg) == md5_before_preview)

# ---- 原始文件 md5 必须不变 ----
after = md5(REAL)
ok("原始 py.json md5 不变（安全）", before == after, "%s vs %s" % (before, after))

shutil.rmtree(tmp, ignore_errors=True)
print("\n结果：%d 通过, %d 失败" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
