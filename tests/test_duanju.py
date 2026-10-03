# -*- coding: utf-8 -*-
"""v15 短剧检测专项测试（纯函数 + CLI，不依赖 Qt）：
- detect_duanju：中文/英文关键词、站点名、误报排除
- CLI --duanju-scan：预览列出；--write 批量注释禁用（可再 --enable 恢复）
"""
import io
import json
import os
import shutil
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import injector as I

_passed = [0]
_failed = [0]


def ok(cond, name, detail=""):
    if cond:
        _passed[0] += 1
        print("  [PASS] %s" % name)
    else:
        _failed[0] += 1
        print("  [FAIL] %s  %s" % (name, detail))


def make_py(dirpath, filename, content):
    p = os.path.join(dirpath, filename)
    with open(p, "w", encoding="utf-8") as f:
        f.write(content)
    return p


print("== detect_duanju 纯函数 ==")
tmp = tempfile.mkdtemp()
try:
    p1 = make_py(tmp, "dj1.py", "# 短剧源\nclass Spider:\n    def homeContent(self):\n        return {'class':[{'type_name':'短剧','type_id':'duanju'}]}\n")
    p2 = make_py(tmp, "movie.py", "# 影视源\nclass Spider:\n    def homeContent(self):\n        return {'class':[{'type_name':'电影','type_id':'movie'},{'type_name':'电视剧','type_id':'tv'}]}\n")
    p3 = make_py(tmp, "asd.py", "# 有声\nclass Spider:\n    cates = ['有声短剧','广播剧']\n")

    r = I.detect_duanju(p1, "某短剧网")
    ok(r[0] is True and r[1] == "短剧", "py 内容含短剧 -> 命中", str(r))
    r = I.detect_duanju(p2, "某影视")
    ok(r[0] is False and r[1] is None, "普通影视源 -> 不命中", str(r))
    r = I.detect_duanju(p3, "某有声")
    ok(r[0] is True, "分类含「有声短剧」-> 命中", str(r))
    r = I.detect_duanju("", "天天短剧")
    ok(r[0] is True and r[1] == "短剧", "仅站点名含短剧 -> 命中", str(r))
    r = I.detect_duanju("", "天堂影视")
    ok(r[0] is False, "普通站点名 -> 不命中", str(r))
    r = I.detect_duanju("", "DuanJu Hub")
    ok(r[0] is True and r[1] == "duanju", "英文 duanju 词边界命中", str(r))
    r = I.detect_duanju("", "adjacentxduanju")
    ok(r[0] is False, "duanju 作为子串不作词 -> 不命中", str(r))
    r = I.detect_duanju("", "Short Drama TV")
    ok(r[0] is True and r[1] == "short drama", "short drama 命中", str(r))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("== CLI --duanju-scan（预览 / --write 禁用 / --enable 恢复）==")
tmp = tempfile.mkdtemp()
try:
    py_dir = os.path.join(tmp, "py")
    os.makedirs(py_dir)
    make_py(py_dir, "dj.py", "# 短剧\nclass Spider: pass\n")
    make_py(py_dir, "mv.py", "# 电影电视剧\nclass Spider: pass\n")
    sites = [
        {"key": "py_dj", "name": "快看短剧", "api": "./py/dj.py", "type": 3,
         "filterable": 1, "quickSearch": 1, "searchable": 1},
        {"key": "py_mv", "name": "好看电影", "api": "./py/mv.py", "type": 3,
         "filterable": 1, "quickSearch": 1, "searchable": 1},
    ]
    with open(os.path.join(tmp, "py.json"), "w", encoding="utf-8") as f:
        json.dump({"sites": sites}, f, ensure_ascii=False, indent=2)

    # 预览模式
    from contextlib import redirect_stdout
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = I.run_cli(["--repo", tmp, "--duanju-scan"])
    out = buf.getvalue()
    ok(rc == 0, "预览 rc=0")
    ok("检测到 1 个短剧类站点" in out and "py_dj" in out, "预览列出 py_dj", out[-300:])
    ok("py_mv" not in out.split("短剧类站点")[1], "预览不含 py_mv", out[-300:])
    ok("[预览模式]" in out, "预览提示未写入")
    with open(os.path.join(tmp, "py.json"), encoding="utf-8") as f:
        ok("[disabled]" not in f.read(), "预览后文件未被改动")

    # --write 批量禁用
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = I.run_cli(["--repo", tmp, "--duanju-scan", "--write"])
    out = buf.getvalue()
    ok(rc == 0, "write rc=0")
    ok("已禁用 1 个短剧类站点" in out, "write 报已禁用", out[-300:])
    with open(os.path.join(tmp, "py.json"), encoding="utf-8") as f:
        raw2 = f.read()
    ok("[disabled]" in raw2, "py_dj 已被注释禁用")
    ok('"py_mv"' in raw2 and "[disabled]" not in raw2.split('"py_mv"')[0].split("*/")[-1],
       "py_mv 保持启用")
    ok(any(fn.startswith("py.json.") for fn in os.listdir(os.path.join(tmp, "backups"))) if os.path.isdir(os.path.join(tmp, "backups")) else False, "生成备份文件（backups/ 目录）")

    # 重复禁用 -> 幂等（已无未禁用的短剧站）
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = I.run_cli(["--repo", tmp, "--duanju-scan", "--write"])
    ok("未检测到短剧类站点" in buf.getvalue() or "未找到任何可禁用" in buf.getvalue(),
       "重复禁用幂等", buf.getvalue()[-200:])

    # --enable 恢复
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = I.run_cli(["--repo", tmp, "--enable", "py_dj", "--write"])
    out = buf.getvalue()
    ok(rc == 0, "enable rc=0")
    with open(os.path.join(tmp, "py.json"), encoding="utf-8") as f:
        ok("[disabled]" not in f.read(), "py_dj 已恢复启用")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\n结果: %d 通过, %d 失败" % (_passed[0], _failed[0]))
sys.exit(1 if _failed[0] else 0)
