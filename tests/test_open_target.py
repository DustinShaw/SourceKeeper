# -*- coding: utf-8 -*-
"""open_target_of（按 type 分流打开）单元测试。

覆盖用户反馈的「双击 jar 型 spider 报『未找到对应 .py 文件』」问题：
不同 type 的条目要打开的东西完全不同，不能一律当 .py 处理。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pyinj_core as C   # noqa: E402


def _mk(api, **kw):
    e = {"key": kw.pop("key", "k_" + str(abs(hash(api)) % 99999)),
         "name": kw.pop("name", "站点"), "api": api}
    e.update(kw)
    return e


# ---------------------------------------------------------------- 基础口径
def test_jar_spider_opens_jar_not_py():
    """jar 型 spider（api 是类名，带 jar 字段）→ 打开远程 jar，绝不找本地 .py。"""
    e = _mk("csp_HuyaLiveAmns", type=3,
            jar="http://example.com/jar/lubin.php?jar=hy.jar")
    t = C.open_target_of(e)
    assert t["kind"] == "jar", t
    assert t["url"] == "http://example.com/jar/lubin.php?jar=hy.jar"
    assert "jar" in t["label"].lower() or "jar" in t["label"]
    assert t["path"] is None
    # 关键：绝不能是 file（否则又会去找 .py）
    assert t["kind"] != "file"


def test_local_py_spider_opens_file():
    """type:3 本地 .py spider → 打开本地脚本文件。"""
    d = tempfile.mkdtemp(prefix="pypp_ot_")
    py_rel = "spider/苹果CMS.py"
    py_abs = os.path.join(d, py_rel.replace("/", os.sep))
    os.makedirs(os.path.dirname(py_abs), exist_ok=True)
    with open(py_abs, "w", encoding="utf-8") as f:
        f.write("# dummy spider\n")
    e = _mk(py_rel, type=3)
    t = C.open_target_of(e, base_dir=d)
    assert t["kind"] == "file", t
    assert os.path.isfile(t["path"])
    assert t["path"].endswith("苹果CMS.py")


def test_local_py_spider_missing_file_none():
    """type:3 本地 .py 但文件不存在 → kind=none 且带提示（不是抛异常）。"""
    e = _mk("spider/不存在.py", type=3)
    t = C.open_target_of(e, base_dir=tempfile.mkdtemp(prefix="pypp_ot_"))
    assert t["kind"] == "none", t
    assert t["note"]


def test_resolved_py_wins():
    """GUI 已通过文件重定位找到实际 .py → 用 resolved_py。"""
    d = tempfile.mkdtemp(prefix="pypp_ot_")
    real = os.path.join(d, "real_spider.py")
    with open(real, "w", encoding="utf-8") as f:
        f.write("# x\n")
    e = _mk("spider/原始名.py", type=3)
    t = C.open_target_of(e, base_dir=d, resolved_py=real)
    assert t["kind"] == "file", t
    assert os.path.abspath(t["path"]) == os.path.abspath(real)


# ---------------------------------------------------------------- 直连 / 远程
def test_cms_direct_opens_url():
    """type:1 直连 CMS（api 是 http 接口）→ 打开 API 链接。"""
    e = _mk("http://cms.example.com/api.php/provide/vod", type=1)
    t = C.open_target_of(e)
    assert t["kind"] == "url", t
    assert t["url"] == "http://cms.example.com/api.php/provide/vod"
    assert "API" in t["label"] or "链接" in t["label"]


def test_remote_py_opens_url():
    """type:3 但 api 是远程 .py 链接 → 打开远程脚本 URL。"""
    e = _mk("http://cdn.example.com/spider/foo.py", type=3)
    t = C.open_target_of(e)
    assert t["kind"] == "url", t
    assert t["url"] == "http://cdn.example.com/spider/foo.py"
    assert "脚本" in t["label"]


def test_remote_js_opens_url():
    e = _mk("https://cdn.example.com/s.js", type=3)
    t = C.open_target_of(e)
    assert t["kind"] == "url", t


# ---------------------------------------------------------------- 目录型
def test_type4_local_dir_opens_dir():
    """type:4 目录型（本地路径）→ 打开目录。"""
    d = tempfile.mkdtemp(prefix="pypp_ot_")
    e = _mk("local/alist", type=4)
    t = C.open_target_of(e, base_dir=d)
    assert t["kind"] == "dir", t


def test_type4_remote_opens_url():
    """type:4 但 api 是 http（如 Alist/WebDAV 远端）→ 打开 URL。"""
    e = _mk("http://alist.example.com/dav", type=4)
    t = C.open_target_of(e)
    assert t["kind"] == "url", t


def test_type0_xml_url():
    """type:0 XML 源（http）→ 打开 URL。"""
    e = _mk("http://xml.example.com/feed.xml", type=0)
    t = C.open_target_of(e)
    assert t["kind"] == "url", t


# ---------------------------------------------------------------- 边界
def test_empty_api_none():
    """api 为空 → kind=none，给出说明而非崩溃。"""
    e = {"key": "k1", "name": "空站点", "api": "", "type": 3}
    t = C.open_target_of(e)
    assert t["kind"] == "none", t
    assert t["note"]


def test_none_api_none():
    e = {"key": "k1", "name": "None 站点", "api": None, "type": 3}
    t = C.open_target_of(e)
    assert t["kind"] == "none", t


def test_returns_all_keys():
    """返回值结构稳定：始终含 kind/path/url/label/note 五个字段。"""
    e = _mk("csp_X", type=3, jar="http://e.com/a.jar")
    t = C.open_target_of(e)
    for k in ("kind", "path", "url", "label", "note"):
        assert k in t, "缺字段 %s" % k


def test_jartype_with_pysuffix_still_file():
    """带 jar 字段但 api 明确以 .py 结尾（罕见）：仍按本地脚本处理（后缀优先）。"""
    d = tempfile.mkdtemp(prefix="pypp_ot_")
    p = os.path.join(d, "weird.py")
    with open(p, "w", encoding="utf-8") as f:
        f.write("# x\n")
    e = _mk("weird.py", type=3, jar="http://e.com/ignored.jar")
    t = C.open_target_of(e, base_dir=d)
    assert t["kind"] == "file", t


def test_csp_dot_js_suffix_is_file():
    """.js 后缀（本地 JS spider）→ 按本地脚本文件处理。"""
    d = tempfile.mkdtemp(prefix="pypp_ot_")
    js_rel = "spider/foo.js"
    p = os.path.join(d, js_rel.replace("/", os.sep))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write("// js\n")
    e = _mk(js_rel, type=3)
    t = C.open_target_of(e, base_dir=d)
    assert t["kind"] == "file", t


# ---------------------------------------------------------------- 一致性
def test_consistency_with_expects_local_file():
    """jar 型 spider：open_target_of 不返回 file，且 expects_local_file 为 False。"""
    e = _mk("csp_Config", type=3, jar="http://e.com/x.jar")
    assert C.expects_local_file(e) is False
    assert C.open_target_of(e)["kind"] != "file"


def test_expects_local_file_true_matches_file_kind():
    """本地 .py：expects_local_file True，且（文件存在时）open_target_of 给 file。"""
    d = tempfile.mkdtemp(prefix="pypp_ot_")
    p = os.path.join(d, "s.py")
    with open(p, "w", encoding="utf-8") as f:
        f.write("# x\n")
    e = _mk("s.py", type=3)
    assert C.expects_local_file(e) is True
    assert C.open_target_of(e, base_dir=d)["kind"] == "file"


def test_real_config_jar_entries_not_file(tmp_path=None):
    """真实 py.json：所有 jar 型（带 jar 字段且 api 非脚本后缀）条目都不应给 file。"""
    cfg = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "py.json")
    if not os.path.isfile(cfg):
        return  # 无真实配置则跳过
    data = C.parse_config_text(open(cfg, encoding="utf-8").read())
    sites = data.get("sites") or []
    jar_cnt = 0
    for s in sites:
        if not isinstance(s, dict):
            continue
        api = str(s.get("api") or "")
        if s.get("jar") and not api.lower().endswith((".py", ".js", ".drpy")):
            jar_cnt += 1
            t = C.open_target_of(s, base_dir=os.path.dirname(cfg))
            assert t["kind"] == "jar", (api, t)
    assert jar_cnt >= 1, "真实配置里应至少有一个 jar 型条目"


if __name__ == "__main__":
    import traceback
    fns = [(n, f) for n, f in sorted(globals().items())
           if n.startswith("test_") and callable(f)]
    ok = bad = 0
    for n, f in fns:
        try:
            f()
            print("  ✓ %s" % n)
            ok += 1
        except Exception:
            print("  ✗ %s" % n)
            traceback.print_exc()
            bad += 1
    print("\n%d/%d 通过" % (ok, ok + bad))
    sys.exit(1 if bad else 0)
