# -*- coding: utf-8 -*-
"""type 字段修复回归测试（影视仓 / TVBox 接口类型规则）。

影视仓/TVBox 的 sites[].type 是「接口类型」数字：
    0 = XML（极少用）
    1 = JSON 直连（CMS 类，如 api.php/provide/vod、普通 http(s) 接口）
    3 = Spider（jar / js / py / csp_* 全部归这一类；具体引擎由
        api 字段的后缀区分，*不* 靠 type）
    4 = T4 / 目录型（Alist、WebDAV）
本文件锁定：写入配置时绝不把每条记录的 type 抹平成同一个全局值。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pyinj_core as C  # noqa: E402

passed = 0
failed = 0


def ok(name, cond, extra=""):
    global passed, failed
    if cond:
        passed += 1
        print("  \u2713 " + name)
    else:
        failed += 1
        print("  \u2717 " + name + "   " + str(extra))


# ---------------------------------------------------------------- infer_type
print("== infer_type（接口类型推断）==")
ok("api 为空 → 回落 3", C.infer_type("") == 3, C.infer_type(""))
ok("csp_ 前缀 → 3", C.infer_type("csp_DouBan") == 3)
ok("csp_ 前缀（小写）→ 3", C.infer_type("Csp_NewCz") == 3)
ok(".py → 3", C.infer_type("./py/a.py") == 3)
ok(".js → 3", C.infer_type("./js/x.js") == 3)
ok(".jar → 3", C.infer_type("spider.jar") == 3)
ok("远程 .py → 3", C.infer_type("http://x.com/y.py") == 3)
ok("直连 http CMS → 1", C.infer_type("https://x.com/api.php/provide/vod") == 1)
ok("直连 http（无路径）→ 1", C.infer_type("http://x.com") == 1)
ok("未知形态 → 3", C.infer_type("weird") == 3)

# ------------------------------------------------------------ normalize_site
print("== normalize_site（type 取值优先级）==")
e = C.normalize_site({"key": "k", "name": "n", "api": "./py/a.py"})
ok("缺 type + .py → 推断 3（不再是 0）", e["type"] == 3, e["type"])
e = C.normalize_site({"key": "k", "name": "n", "api": "https://x.com/api.php/provide/vod"})
ok("缺 type + 直连 → 推断 1", e["type"] == 1, e["type"])
e = C.normalize_site({"key": "k", "name": "n", "api": "./py/a.py", "type": "py"})
ok("字符串 type('py') 原样保留", e["type"] == "py", e["type"])
e = C.normalize_site({"key": "k", "name": "n", "api": "./py/a.py", "type": "1"})
ok("字符串 '1' → int 1", e["type"] == 1, e["type"])
e = C.normalize_site({"key": "k", "name": "n", "api": "./py/a.py", "type": 4})
ok("数字 4（Alist）保留", e["type"] == 4, e["type"])
e = C.normalize_site({"key": "k", "name": "n", "api": "http://x.com", "type": None})
ok("type=None + 直连 → 1", e["type"] == 1, e["type"])

# ----------------------------------------------------------------- fmt_entry
print("== fmt_entry（type 输出兼容字符串）==")
txt = C.fmt_entry({"key": "k", "name": "n", "api": "./py/a.py", "type": "py",
                   "filterable": 1, "quickSearch": 1, "searchable": 1})
ok("字符串 type 带引号输出", '"type": "py"' in txt, txt)
txt = C.fmt_entry({"key": "k", "name": "n", "api": "./py/a.py", "type": 3,
                   "filterable": 1, "quickSearch": 1, "searchable": 1})
ok("数字 type 普通输出", '"type": 3' in txt, txt)
ok("数字输出不带引号", '"type": "3"' not in txt, txt)

# --------------------------------------------------------------- commit_write
print("== commit_write（不全局抹平每条 type）==")
repo = tempfile.mkdtemp()
raw = '{"sites": []}'
# backup_and_write 会先备份已存在的配置文件，故测试前需落盘一份
open(os.path.join(repo, "py.json"), "w", encoding="utf-8").write(raw)
ents = [{"key": "py_x", "name": "X", "api": "./py/x.py", "type": 3,
         "filterable": 1, "quickSearch": 1, "searchable": 1}]
sw = {"filterable": 1, "quickSearch": 1, "searchable": 1, "type": 9}  # 全局误设 9
try:
    C.commit_write(repo, raw, ents, sw, "py.json")
    written = os.path.join(repo, "py.json")
    data = C.parse_config_text(open(written, encoding="utf-8").read())
    got = data["sites"][0].get("type")
    ok("条目自带 type=3 不被全局 9 覆盖", got == 3, got)
except Exception as ex:
    ok("commit_write 执行成功", False, ex)

# 缺失 type 时仍应回落 switches
repo2 = tempfile.mkdtemp()
open(os.path.join(repo2, "py.json"), "w", encoding="utf-8").write(raw)
ents2 = [{"key": "py_y", "name": "Y", "api": "./py/y.py",
          "filterable": 1, "quickSearch": 1, "searchable": 1}]
try:
    C.commit_write(repo2, raw, ents2, sw, "py.json")
    data2 = C.parse_config_text(open(os.path.join(repo2, "py.json"), encoding="utf-8").read())
    got2 = data2["sites"][0].get("type")
    ok("条目缺 type 时回落 switches(=9)", got2 == 9, got2)
except Exception as ex:
    ok("commit_write 回落执行", False, ex)

# 显式 type=0（XML）是合法值，绝不能被当成「缺失」而改写
repo3 = tempfile.mkdtemp()
open(os.path.join(repo3, "py.json"), "w", encoding="utf-8").write(raw)
ents3 = [{"key": "xml_z", "name": "Z", "api": "http://xml.example.com/feed.xml", "type": 0,
          "filterable": 1, "quickSearch": 1, "searchable": 1}]
try:
    C.commit_write(repo3, raw, ents3, sw, "py.json")
    data3 = C.parse_config_text(open(os.path.join(repo3, "py.json"), encoding="utf-8").read())
    got3 = data3["sites"][0].get("type")
    ok("显式 type=0(XML) 不被全局 9 覆盖", got3 == 0, got3)
except Exception as ex:
    ok("commit_write type=0 保留执行", False, ex)

# ------------------------------------------------------------------ make_entry
print("== make_entry（注入 .py 时按文件推断 type）==")
try:
    td = tempfile.mkdtemp()
    pyf = os.path.join(td, "demo.py")
    open(pyf, "w", encoding="utf-8").write(
        "class Spider:\n    def getDependence(self):\n        pass\n")
    ent = C.make_entry(pyf, td, False)
    ok("注入 .py → type=3", ent.get("type") == 3, ent.get("type"))
except Exception as ex:
    ok("make_entry 执行", False, ex)

print("\n\u7ed3\u679c\uff1a%d \u901a\u8fc7, %d \u5931\u8d25" % (passed, failed))
sys.exit(1 if failed else 0)
