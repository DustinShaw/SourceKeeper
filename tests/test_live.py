# -*- coding: utf-8 -*-
"""直播检测专项测试（纯函数 + CLI，不依赖 Qt）：
- detect_live：中文/英文关键词、站点名、裸 live 误报排除
- CLI --live-scan：预览列出；--write 批量注释禁用（可再 --enable 恢复）
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


print("== detect_live 纯函数 ==")
tmp = tempfile.mkdtemp()
try:
    p1 = make_py(tmp, "lv1.py", "# 直播源\nclass Spider:\n    def homeContent(self):\n        return {'class':[{'type_name':'直播','type_id':'live'}]}\n")
    p2 = make_py(tmp, "movie.py", "# 影视源\nclass Spider:\n    def homeContent(self):\n        return {'class':[{'type_name':'电影','type_id':'movie'}]}\n")
    p3 = make_py(tmp, "show.py", "# 有声\nclass Spider:\n    cates = ['秀场','广播剧']\n")

    r = I.detect_live(p1, "某直播网")
    ok(r[0] is True and r[1] == "直播", "py 内容含直播 -> 命中", str(r))
    r = I.detect_live(p2, "某影视")
    ok(r[0] is False and r[1] is None, "普通影视源 -> 不命中", str(r))
    r = I.detect_live(p3, "某秀场")
    ok(r[0] is True and r[1] == "秀场", "分类含「秀场」-> 命中", str(r))
    r = I.detect_live("", "天天直播")
    ok(r[0] is True and r[1] == "直播", "仅站点名含直播 -> 命中", str(r))
    r = I.detect_live("", "天堂影视")
    ok(r[0] is False, "普通站点名 -> 不命中", str(r))
    r = I.detect_live("", "LiveTV Hub")
    ok(r[0] is True and r[1] == "livetv", "英文 livetv 词边界命中", str(r))
    r = I.detect_live("", "live data here")
    ok(r[0] is False, "裸 live（live data）已排除 -> 不命中", str(r))
    r = I.detect_live("", "adjacentxlive")
    ok(r[0] is False, "live 作为子串不作词 -> 不命中", str(r))
    r = I.detect_live("", "IPTV Box")
    ok(r[0] is True and r[1] == "iptv", "iptv 命中", str(r))
    r = I.detect_live("", "Live Stream TV")
    ok(r[0] is True and r[1] == "live stream", "live stream 命中", str(r))
    r = I.detect_live("", "直播间小姐姐")
    ok(r[0] is True and r[1] in ("直播", "直播间"), "直播间命中（含直播子串即命中）", str(r))
    r = I.detect_live("", "主播日常")
    ok(r[0] is True and r[1] == "主播", "主播命中", str(r))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("== CLI --live-scan（预览 / --write 禁用 / --enable 恢复）==")
tmp = tempfile.mkdtemp()
try:
    py_dir = os.path.join(tmp, "py")
    os.makedirs(py_dir)
    make_py(py_dir, "lv.py", "# 直播\nclass Spider: pass\n")
    make_py(py_dir, "mv.py", "# 电影电视剧\nclass Spider: pass\n")
    sites = [
        {"key": "py_lv", "name": "快看直播", "api": "./py/lv.py", "type": 3,
         "filterable": 1, "quickSearch": 1, "searchable": 1},
        {"key": "py_mv", "name": "好看电影", "api": "./py/mv.py", "type": 3,
         "filterable": 1, "quickSearch": 1, "searchable": 1},
    ]
    with open(os.path.join(tmp, "py.json"), "w", encoding="utf-8") as f:
        json.dump({"sites": sites}, f, ensure_ascii=False, indent=2)

    from contextlib import redirect_stdout
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = I.run_cli(["--repo", tmp, "--live-scan"])
    out = buf.getvalue()
    ok(rc == 0, "预览 rc=0")
    ok("检测到 1 个直播类站点" in out and "py_lv" in out, "预览列出 py_lv", out[-300:])
    ok("py_mv" not in out.split("直播类站点")[-1], "预览不含 py_mv", out[-300:])
    ok("[预览模式]" in out, "预览提示未写入")
    with open(os.path.join(tmp, "py.json"), encoding="utf-8") as f:
        ok("[disabled]" not in f.read(), "预览后文件未被改动")

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = I.run_cli(["--repo", tmp, "--live-scan", "--write"])
    out = buf.getvalue()
    ok(rc == 0, "write rc=0")
    ok("已禁用 1 个直播类站点" in out, "write 报已禁用", out[-300:])
    with open(os.path.join(tmp, "py.json"), encoding="utf-8") as f:
        raw2 = f.read()
    ok("[disabled]" in raw2, "py_lv 已被注释禁用")
    ok('"py_mv"' in raw2 and "[disabled]" not in raw2.split('"py_mv"')[0].split("*/")[-1],
       "py_mv 保持启用")
    ok(any(fn.startswith("py.json.") for fn in os.listdir(os.path.join(tmp, "backups"))) if os.path.isdir(os.path.join(tmp, "backups")) else False, "生成备份文件（backups/ 目录）")

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = I.run_cli(["--repo", tmp, "--live-scan", "--write"])
    ok("未检测到直播类站点" in buf.getvalue() or "未找到任何可禁用" in buf.getvalue(),
       "重复禁用幂等", buf.getvalue()[-200:])

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = I.run_cli(["--repo", tmp, "--enable", "py_lv", "--write"])
    ok(rc == 0, "enable rc=0")
    with open(os.path.join(tmp, "py.json"), encoding="utf-8") as f:
        ok("[disabled]" not in f.read(), "py_lv 已恢复启用")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\n结果: %d 通过, %d 失败" % (_passed[0], _failed[0]))
sys.exit(1 if _failed[0] else 0)
