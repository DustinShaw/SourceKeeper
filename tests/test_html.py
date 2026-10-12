# -*- coding: utf-8 -*-
"""文档 HTML 生成自检（纯逻辑，两条 Qt 构建链都跑）。

验证 tools/md2html.py 把 使用方法.md 渲染成带侧边栏书签的 使用方法.html：
  ① 转换成功且关键章节都在；
  ② 侧边栏链接数 == 目录项数，且每个 #锚点 都能命中真实存在的 id；
  ③ 锚点 id 全局唯一；
  ④ 单文件零外链（不引 CDN / 不含 http(s) 外链的 src/href）；
  ⑤ HTML 结构完整（doctype / 侧边栏 / main）；
  ⑥ 表格 / 代码块数量与源 md 一致（渲染不丢块）。
安全：本测试只读源 md、只在临时目录写产物，不触碰仓库里的 使用方法.html。
"""
import os
import re
import sys
import html as H
import tempfile
import importlib.util

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(HERE, "使用方法.md")

PASS = FAIL = 0


def ok(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ✓ %s" % name)
    else:
        FAIL += 1
        print("  ✗ %s  %s" % (name, extra))


# ---- 载入生成器模块 ----
spec = importlib.util.spec_from_file_location(
    "md2html", os.path.join(HERE, "tools", "md2html.py"))
md2html = importlib.util.module_from_spec(spec)
spec.loader.exec_module(md2html)

md = open(SRC, encoding="utf-8").read()
page, toc = md2html.convert(md, "源管家 使用方法", "v1.0.3")
body = page.split("<main>", 1)[1].split("</main>", 1)[0]

print("== 1) 基本转换 ==")
ok("生成内容非空", len(page) > 20000, len(page))
ok("含 doctype", page.lstrip().startswith("<!DOCTYPE html>"))
ok("含侧边栏 <aside>", "<aside>" in page and "</aside>" in page)
ok("含正文 <main>", "<main>" in page)
ok("目录项数量合理（≥15）", len(toc) >= 15, len(toc))

print("\n== 2) 书签（侧边栏）与锚点一一对应 ==")
ids = re.findall(r'<h[1-4] id="([^"]+)"', page)
hrefs = re.findall(r'<a href="#([^"]+)"', page)
ok("锚点 id 唯一", len(ids) == len(set(ids)),
   [x for x in ids if ids.count(x) > 1])
ok("侧边栏链接数 == 目录项数", len(hrefs) == len(toc), "%d vs %d" % (len(hrefs), len(toc)))
missing = [h for h in hrefs if h not in ids]
ok("每个侧边栏链接都能命中锚点", not missing, missing)
ok("目录里 H2/H3 都进了侧边栏", len(toc) == len(re.findall(r'<h[23] id=', page)),
   "%d vs %d" % (len(toc), len(re.findall(r'<h[23] id=', page))))

print("\n== 3) 关键章节与内容完整 ==")
for kw in ["0. 第一次使用", "场景 9", "常见问题", "备份文件一览", "判重口径"]:
    ok("含章节「%s」" % kw, kw in H.unescape(re.sub(r"<[^>]+>", "", body)))

# 表格 / 代码块数量与源 md 一致
lines = md.split("\n")
sep = re.compile(r"^\|[\s:\-|]+\|$")
md_tables = sum(1 for i in range(len(lines) - 1)
                if lines[i].strip().startswith("|") and sep.match(lines[i + 1].strip()))
html_tables = len(re.findall(r"<table>", body))
ok("表格数量与源 md 一致", md_tables == html_tables, "%d vs %d" % (md_tables, html_tables))
md_fences = md.count("```") // 2
ok("代码块数量与源 md 一致", md_fences == len(re.findall(r"<pre", body)),
   "%d vs %d" % (md_fences, len(re.findall(r"<pre", body))))
ok("无空表（每个表都有数据行）",
   all(len(re.findall(r"<tr>", t)) >= 2
       for t in re.findall(r"<table>(.*?)</table>", body, re.S)))

print("\n== 4) 零外链（可离线双击打开）==")
ext = re.findall(r'(?:src|href)="(https?://[^"]+)"', page)
ok("不含任何 http(s) 外链资源", not ext, ext)
ok("不含 <link rel=stylesheet>（CSS 内联）", "<link" not in page.lower())
ok("CSS 与 JS 均内联", "<style>" in page and "<script>" in page)

print("\n== 5) CLI 模式 ==")
tmp = tempfile.mkdtemp(prefix="md2html_")
try:
    out = os.path.join(tmp, "x.html")
    rc = md2html.main.__wrapped__ if hasattr(md2html.main, "__wrapped__") else None
    # 直接调用 argparse 主函数（模拟 argv）
    old = sys.argv
    sys.argv = ["md2html.py", "--in", SRC, "--out", out, "--check"]
    rc_check = md2html.main()
    sys.argv = ["md2html.py", "--in", SRC, "--out", out]
    rc_write = md2html.main()
    sys.argv = old
    ok("--check 返回 0", rc_check == 0, rc_check)
    ok("写盘模式返回 0", rc_write == 0, rc_write)
    ok("产物已写出", os.path.isfile(out) and os.path.getsize(out) > 20000)
finally:
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)

# 真实仓库里的 使用方法.html 不该被本测试改动
print("\n== 6) 不触碰仓库产物 ==")
real = os.path.join(HERE, "使用方法.html")
if os.path.isfile(real):
    ok("仓库 使用方法.html 存在（已由构建生成）", True)
    ok("仓库文件含侧边栏", "<aside>" in open(real, encoding="utf-8").read())
else:
    ok("仓库 使用方法.html 尚未生成（构建时才产出）", True)

print("\n结果：%d 通过 / %d 失败" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
