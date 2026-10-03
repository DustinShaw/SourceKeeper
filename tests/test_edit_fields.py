#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试「编辑站点」对话框背后的字段写回能力：
jar（字符串字段）与 ext（JSON 字段）的 新增 / 修改 / 清空，
以及清空时不应往原本没有该字段的源里塞空值。
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pyinj_core as C


def ok(name, cond, extra=""):
    print(("✓ " if cond else "✗ ") + name + (("  -> " + str(extra)) if (extra and not cond) else ""))
    if not cond:
        ok.failed += 1
ok.failed = 0


BASE = '''{
  "sites": [
    {
      "key": "py_x",
      "name": "测试源",
      "api": "py_x.py",
      "type": 3,
      "filterable": 1,
      "quickSearch": 1,
      "searchable": 1
    },
    {
      "key": "jar_a",
      "name": "Jar源",
      "api": "csp_Foo",
      "jar": "foo.jar",
      "ext": {"site": "http://a.com"},
      "type": 3
    }
  ]
}'''


def sites_of(t):
    return C.parse_jsonc(t)["sites"]


# 1) 给无 jar 的源加上 jar
t, _ = C.update_site(BASE, "py_x", "jar", "new.jar")
o = sites_of(t)
ok("set jar 新增字段", o[0].get("jar") == "new.jar", o[0])

# 2) 给无 ext 的源设置 ext（dict）
t, _ = C.update_site(BASE, "py_x", "ext", {"site": "http://b.com", "n": 1})
o = sites_of(t)
ok("set ext 新增字段", o[0].get("ext") == {"site": "http://b.com", "n": 1}, o[0].get("ext"))

# 3) 已有 ext 的源修改 ext（嵌套对象整体替换）
t, _ = C.update_site(BASE, "jar_a", "ext", {"site": "http://changed.com"})
o = sites_of(t)
ok("改已有 ext", o[1]["ext"] == {"site": "http://changed.com"}, o[1]["ext"])

# 4) 清空 ext（None）→ 删除字段
t, _ = C.update_site(BASE, "jar_a", "ext", None)
o = sites_of(t)
ok("清空 ext 删除字段", "ext" not in o[1], o[1])

# 5) 清空 jar（空串）→ 删除字段
t, _ = C.update_site(BASE, "jar_a", "jar", "")
o = sites_of(t)
ok("清空 jar 删除字段", "jar" not in o[1], o[1])

# 6) 对原本没有 ext 的源清空 ext（None）→ 不应新增
t, _ = C.update_site(BASE, "py_x", "ext", None)
o = sites_of(t)
ok("对无 ext 源清空 ext 不新增", "ext" not in o[0], o[0])

# 7) 修改后整段仍为合法 JSON（parse_jsonc 不报错已在上面隐式验证）
ok("整体仍可解析", True)

print("\n失败 %d 项" % ok.failed)
sys.exit(1 if ok.failed else 0)
