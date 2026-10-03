# -*- coding: utf-8 -*-
"""v14 无界面测试：URL 提取/可达性检测 + 禁用/启用 JSONC 文本操作。
全部为纯函数/文本操作，不依赖 Qt；网络检测用本地 http.server 验证 TCP+HTTP 路径。
"""
import os
import sys
import json
import socket
import threading
import http.server
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import injector as I

PASS, FAIL = 0, 0


def ok(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ✓ %s" % name)
    else:
        FAIL += 1
        print("  ✗ %s  %s" % (name, extra))


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class _H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"ok")
    def log_message(self, *a):
        pass


def start_server(port):
    srv = http.server.HTTPServer(("127.0.0.1", port), _H)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv


def write_tmp_py(code):
    fd, path = tempfile.mkstemp(suffix=".py")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(code)
    return path


# ---------------------------------------------------------------------------
print("== 1. extract_urls_from_py ==")
py = write_tmp_py(
    'url = "https://example.com/api/v1"\n'
    'backup = "http://test.org:8080/x"\n'
    'doc = "https://github.com/foo/bar"\n'
    'bad = "http://"\n'            # 无主机，应被过滤
    'txt = "见 https://news.site.cn/feed 详情。"\n'
)
urls = I.extract_urls_from_py(py)
ok("提取到 4 个有效 URL", len(urls) == 4, "got=%s" % urls)
ok("去重生效", "https://example.com/api/v1" in urls)
ok("过滤无主机占位", "http://" not in urls)

py_no = write_tmp_py('x = 1\ny = "no url here"\n')
ok("无 URL 返回空", I.extract_urls_from_py(py_no) == [])

# ---------------------------------------------------------------------------
print("== 2. check_url_reachable / check_site_urls（本地服务器）==")
port = free_port()
srv = start_server(port)
live = "http://127.0.0.1:%d/path" % port
# 等一会让服务器就绪
import time
time.sleep(0.2)
ok_reach, method, err = I.check_url_reachable(live)
ok("本地服务器可达", ok_reach, "method=%s err=%s" % (method, err))
ok("方法含 tcp 或 http", ("tcp" in method or "http" in method), method)

py_live = write_tmp_py('src = "%s"\n' % live)
r = I.check_site_urls(py_live)
ok("站点可达(reachable=True)", r["reachable"] is True, str(r))
ok("记录可达方法", bool(r["method"]))

# 不可达：连接一个必关闭的端口（端口 1 通常无服务）
dead = "http://127.0.0.1:1/closed"
r2 = I.check_site_urls(write_tmp_py('src = "%s"\n' % dead))
ok("站点不可达(reachable=False)", r2["reachable"] is False, str(r2))

# 无 URL
r3 = I.check_site_urls(py_no)
ok("无 URL(reachable=None)", r3["reachable"] is None, str(r3))

srv.shutdown()

# ---------------------------------------------------------------------------
print("== 3. disable_site / enable_site / parse_* 文本操作 ==")
SAMPLE = '''{
  "spider": "x",
  "sites": [
    {
      "key": "py_a",
      "name": "A┃PY",
      "api": "./py/a.py",
      "type": 3
    },
    {
      "key": "py_b",
      "name": "B┃PY",
      "api": "./py/b.py",
      "type": 3
    }
  ]
}'''
d = json.loads(I.strip_jsonc_comments(SAMPLE))
ok("初始 active=2", len(d["sites"]) == 2)

t1, found = I.disable_site(SAMPLE, "py_a")
ok("disable_site 找到并改写", found)
# 禁用后 active 只剩 1 个
d1 = json.loads(I.strip_jsonc_comments(t1))
ok("禁用后 active=1", len(d1["sites"]) == 1, str(d1["sites"]))
ok("剩余的是 py_b", d1["sites"][0]["key"] == "py_b")
ok("禁用集合含 py_a", "py_a" in I.parse_disabled_keys(t1))
ok("禁用后 parse_sites_with_disabled 含 2 项(1禁用)",
   len(I.parse_sites_with_disabled(t1)) == 2)
ok("禁用项 _disabled=True",
   [dis for _o, dis in I.parse_sites_with_disabled(t1)] == [True, False])
# 数组仍合法（disable 连同逗号注释）
try:
    json.loads(I.strip_jsonc_comments(t1))
    ok("禁用后 JSON 合法", True)
except Exception as ex:
    ok("禁用后 JSON 合法", False, str(ex))

# 再禁用 py_b
t2, found2 = I.disable_site(t1, "py_b")
ok("再禁用 py_b", found2)
d2 = json.loads(I.strip_jsonc_comments(t2))
ok("两项都禁用后 active=0", len(d2["sites"]) == 0, str(d2))
ok("禁用集合含 py_a,py_b", I.parse_disabled_keys(t2) == {"py_a", "py_b"})

# 启用 py_a
t3, ef = I.enable_site(t2, "py_a")
ok("enable_site 找到", ef)
d3 = json.loads(I.strip_jsonc_comments(t3))
ok("启用后 active=1", len(d3["sites"]) == 1, str(d3))
ok("启用的是 py_a", d3["sites"][0]["key"] == "py_a")
ok("仍禁用 py_b", I.parse_disabled_keys(t3) == {"py_b"})
# 启用后该条目字段完整保留
ok("启用后字段完整", d3["sites"][0].get("api") == "./py/a.py")
try:
    json.loads(I.strip_jsonc_comments(t3))
    ok("启用后 JSON 合法", True)
except Exception as ex:
    ok("启用后 JSON 合法", False, str(ex))

# 已禁用的再次 disable 应找不到（parse_site_spans 跳过注释）
_, dup = I.disable_site(t2, "py_b")
ok("已禁用项再次 disable 找不到", dup is False)
# 未禁用的再次 enable 应找不到
_, dup2 = I.enable_site(SAMPLE, "py_a")
ok("未禁用项 enable 找不到", dup2 is False)

# 含尾随逗号的最后一个元素禁用（无紧随逗号）
LAST = '''{
  "sites": [
    {"key":"k1","api":"./py/1.py"},
    {"key":"k2","api":"./py/2.py"}
  ]
}'''
tl, _ = I.disable_site(LAST, "k2")
dl = json.loads(I.strip_jsonc_comments(tl))
ok("末项禁用后 k1 仍 active", [s["key"] for s in dl["sites"]] == ["k1"], str(dl))
ok("末项禁用集合含 k2", I.parse_disabled_keys(tl) == {"k2"})

# 关键回归：禁用 a、再禁用 b、再启用 a —— 旧实现会因悬空逗号破坏数组合法性
MID = '''{
  "sites": [
    {"key":"a","api":"./py/a.py","type":3},
    {"key":"b","api":"./py/b.py","type":3},
    {"key":"c","api":"./py/c.py","type":3}
  ]
}'''
ta, _ = I.disable_site(MID, "a")
tb, _ = I.disable_site(ta, "b")   # a、b 均禁用，c 仍 active
ok("a、b 禁用后仅 c active", [s["key"] for s in json.loads(I.strip_jsonc_comments(tb))["sites"]] == ["c"])
ten, ef = I.enable_site(tb, "a")  # 启用 a，此时 b 仍禁用（a 后无 active 邻居）
ok("启用 a 成功且 JSON 仍合法", ef)
try:
    da = json.loads(I.strip_jsonc_comments(ten))
    ok("启用 a 后 active=[a,c]", [s["key"] for s in da["sites"]] == ["a", "c"], str(da))
    ok("a 字段完整保留", da["sites"][0].get("api") == "./py/a.py")
except Exception as ex:
    ok("启用 a 后 JSON 合法", False, str(ex))
ok("此时 b 仍禁用", I.parse_disabled_keys(ten) == {"b"})

print("\n结果：%d 通过, %d 失败" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
