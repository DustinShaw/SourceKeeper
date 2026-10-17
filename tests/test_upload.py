# -*- coding: utf-8 -*-
"""「上传到电视 / 盒子」纯逻辑测试（pyinj_upload）。

覆盖（全部零网络、零真实 adb）：
  1) 远端路径拼接：基础目录 + 相对路径、默认 /sdcard、重复斜杠、绝对路径覆盖、Windows 反斜杠；
  2) shell 单引号转义（中文 / 空格 / 单引号）；
  3) 仓库扫描：默认排除构建产物 / 备份 / 版本库 / exe，保留 py/ 与 data/；
  4) 自定义文件 / 文件夹（等价于「不用源管家改配置也能传别的配置」）；
  5) adb 输出解析：devices -l（device / offline / unauthorized）、md5sum、错误翻译；
  6) 上传执行：建目录去重、跳过 MD5 相同、失败重试一次、单文件失败不中断、取消、本地文件缺失。

本文件为纯逻辑测试（不含任何 Qt 绑定字样），两条构建链都会跑。
"""
import io
import os
import sys
import hashlib
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pyinj_upload as U

PASS = FAIL = 0


def ok(cond, name, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] %s" % name)
    else:
        FAIL += 1
        print("  [FAIL] %s  %s" % (name, detail))


def md5(b):
    return hashlib.md5(b).hexdigest()


print("== 1) 远端路径拼接 ==")
ok(U.norm_remote("/sdcard/", "py/a.py") == "/sdcard/py/a.py", "基础目录带尾斜杠",
   U.norm_remote("/sdcard/", "py/a.py"))
ok(U.norm_remote("/sdcard", "py/a.py") == "/sdcard/py/a.py", "基础目录无尾斜杠")
ok(U.norm_remote("", "a.json") == "/sdcard/a.json", "基础目录留空 → 默认 /sdcard")
ok(U.norm_remote("/sdcard//TVBox/", "a.json") == "/sdcard/TVBox/a.json", "重复斜杠被折叠",
   U.norm_remote("/sdcard//TVBox/", "a.json"))
ok(U.norm_remote("sdcard", "py/a.py") == "/sdcard/py/a.py", "缺前导斜杠自动补上")
ok(U.norm_remote("/sdcard/", "py\\a.py") == "/sdcard/py/a.py", "Windows 反斜杠转 /")
ok(U.norm_remote("/sdcard/", "/data/local/tmp/x.json") == "/data/local/tmp/x.json",
   "相对路径写成绝对路径 → 覆盖基础目录")
ok(U.remote_dir("/sdcard/py/a.py") == "/sdcard/py", "取远端目录")
ok(U.remote_dir("/a.py") == "/", "根目录下的文件，其目录是 /")

print("\n== 2) shell 转义 ==")
ok(U.shq("/sdcard/a b.py") == "'/sdcard/a b.py'", "空格路径被整体包裹", U.shq("/sdcard/a b.py"))
ok(U.shq("a'b") == "'a'\\''b'", "单引号正确转义", U.shq("a'b"))
ok(U.shq("/sdcard/农民影视.py") == "'/sdcard/农民影视.py'", "中文路径原样包裹")

print("\n== 3) 仓库扫描与默认排除 ==")
tmp = tempfile.mkdtemp(prefix="pyinj_up_")
TREE = {
    "py.json": b'{"sites":[]}',
    "README.md": b"# doc",
    "data/word.txt": b"kw",
    "py/a.py": b"class Spider: pass",
    "py/sub/b.py": b"x" * 100,
    "backups/py.json.1.bak": b"old",
    "py_trash/a.py.1.bak": b"old",
    "dist/z.txt": b"z",
    "build/z.txt": b"z",
    "__pycache__/a.pyc": b"c",
    "tool.exe": b"MZ",
    "note.log": b"l",
}
for rel, data in TREE.items():
    p = os.path.join(tmp, rel.replace("/", os.sep))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(data)

items = U.scan_repo(tmp)
rels = [i["rel"] for i in items]
ok(rels == ["README.md", "data/word.txt", "py.json", "py/a.py", "py/sub/b.py"],
   "默认排除 backups/py_trash/dist/build/__pycache__/exe/log", str(rels))
ok([i["size"] for i in items if i["rel"] == "py/sub/b.py"] == [100], "大小统计正确")
ok(U.scan_repo(tmp) == sorted(U.scan_repo(tmp), key=lambda x: x["rel"]), "清单按相对路径排序")
ok(U.scan_repo(os.path.join(tmp, "不存在")) == [], "目录不存在 → 空清单")

rel2 = [i["rel"] for i in U.scan_repo(tmp, excludes=["py", "*.md"])]
ok("py.json" in rel2 and "data/word.txt" in rel2 and "README.md" not in rel2
   and not any(r.startswith("py/") for r in rel2),
   "自定义排除（目录名 + 通配符）**替换**默认表", str(rel2))
rel3 = [i["rel"] for i in U.scan_repo(tmp, excludes=[])]
ok("backups/py.json.1.bak" in rel3 and "tool.exe" in rel3, "传入空排除表 → 全量扫描", str(len(rel3)))

f1 = U.custom_file(os.path.join(tmp, "py", "a.py"))
ok(f1 and f1["rel"] == "a.py", "自定义单文件：rel 取文件名", str(f1))
ok(U.custom_file(os.path.join(tmp, "nope.txt")) is None, "自定义单文件：不存在 → None")
d1 = U.custom_dir(os.path.join(tmp, "py"))
ok([x["rel"] for x in d1] == ["py/a.py", "py/sub/b.py"], "自定义文件夹：保留文件夹名", str(d1))
ok(all(x["src"] == "custom" for x in d1), "自定义来源标记 src=custom")

print("\n== 4) 传输计划 ==")
plan = U.build_plan([f1, f1, {"local": os.path.join(tmp, "py.json"), "rel": "cfg/py.json"}],
                    "/sdcard/")
ok(len(plan) == 2, "同一本地文件只出现一次", str(len(plan)))
ok(plan[1]["remote"] == "/sdcard/cfg/py.json", "显式 rel 被用于远端路径", plan[1]["remote"])
job = U.build_plan([{"local": os.path.join(tmp, "py.json"), "rel": "x.json",
                     "remote": "/data/local/tmp/x.json"}], "/sdcard/")
ok(job[0]["remote"] == "/data/local/tmp/x.json", "条目可单独指定绝对远端路径", job[0]["remote"])

print("\n== 5) adb 输出解析 ==")
DEV = ("List of devices attached\n"
       "192.168.1.9:5555\tdevice product:x model:TV_Box_4 device:x\n"
       "emulator-5554\toffline\n"
       "abc123\tunauthorized\n"
       "192.168.1.10:5555\tdevice\n")
devs = U.parse_devices(DEV)
ok(len(devs) == 4, "解析出 4 台设备", str(len(devs)))
ok(devs[0]["serial"] == "192.168.1.9:5555" and devs[0]["state"] == "device", "首行字段正确")
ok(U.pick_device(devs, "192.168.1.10:5555")["serial"] == "192.168.1.10:5555",
   "优先挑指定串号")
ok(U.pick_device(devs)["state"] == "device", "未指定时挑第一台 device")
ok(U.pick_device([{"serial": "a", "state": "offline"}]) is None, "全是 offline → 不返回设备")
ok(U.describe_device(devs[0]) == "TV Box 4", "从 model: 字段取型号（下划线转空格）",
   U.describe_device(devs[0]))
ok(U.parse_md5sum("D41D8CD98F00B204E9800998ECF8427E  /sdcard/a\r\n")
   == "d41d8cd98f00b204e9800998ecf8427e", "md5sum 输出转小写")
ok(U.parse_md5sum("error: no such file") == "", "无 md5 时返回空串")
ok("未授权" in U.explain_adb_error("error: device unauthorized"), "unauthorized → 中文提示")
ok("离线" in U.explain_adb_error("device offline"), "offline → 中文提示")
ok("只读" in U.explain_adb_error("adb: error: failed to copy: Read-only file system"),
   "read-only → 中文提示")
ok("写权限" in U.explain_adb_error("failed to copy: Permission denied"), "权限被拒 → 中文提示")

print("\n== 6) 上传执行 ==")
class FakeAdb(object):
    def __init__(self, fail_push=False, flaky=False, fail_mkdir=False):
        self.remote = {}
        self.mkdirs = []
        self.pushes = []
        self.fail_push = fail_push
        self.flaky = flaky
        self.fail_mkdir = fail_mkdir
        self._flaked = set()

    def mkdir_p(self, d):
        if self.fail_mkdir:
            return {"ok": False, "err": "mkdir failed: Permission denied", "out": ""}
        if d not in self.mkdirs:
            self.mkdirs.append(d)
        return {"ok": True, "out": "", "err": ""}

    def md5(self, r):
        return self.remote.get(r, "")

    def rm(self, r):
        self.remote.pop(r, None)
        return {"ok": True, "out": "", "err": ""}

    def push(self, local, remote):
        self.pushes.append(remote)
        if self.fail_push:
            return {"ok": False, "err": "adb: error: failed to copy: Permission denied", "out": ""}
        data = open(local, "rb").read()
        if self.flaky and remote not in self._flaked:
            self._flaked.add(remote)
            self.remote[remote] = "0" * 32       # 第一次故意给错 md5
            return {"ok": True, "out": "", "err": ""}
        self.remote[remote] = md5(data)
        return {"ok": True, "out": "", "err": ""}


a = FakeAdb()
rows = U.upload_plan(a, plan, skip_same=False)
ok([r["status"] for r in rows] == ["ok", "ok"], "全部成功", str([r["status"] for r in rows]))
ok(a.remote.get("/sdcard/a.py") == md5(TREE["py/a.py"]), "远端内容 md5 与本地一致")
ok(a.mkdirs == ["/sdcard", "/sdcard/cfg"], "同一远端目录只建一次且按需创建", str(a.mkdirs))

rows2 = U.upload_plan(a, plan, skip_same=True)
ok([r["status"] for r in rows2] == ["skip", "skip"], "MD5 相同 → 全部跳过",
   str([r["status"] for r in rows2]))
ok(len(a.pushes) == 2, "跳过时不再 push", str(len(a.pushes)))

b = FakeAdb()
rows3 = U.upload_plan(b, plan, skip_same=True)
ok([r["status"] for r in rows3] == ["ok", "ok"], "远端没有文件时不跳过，正常上传")

c = FakeAdb(flaky=True)
rows4 = U.upload_plan(c, plan[:1], skip_same=False)
ok(rows4[0]["status"] == "ok", "MD5 不一致 → 自动重试一次后成功", str(rows4[0]))
ok(len(c.pushes) == 2, "确实重试了一次", str(len(c.pushes)))

d = FakeAdb(fail_push=True)
rows5 = U.upload_plan(d, plan, skip_same=False)
ok([r["status"] for r in rows5] == ["fail", "fail"], "push 失败 → 全部 fail 但都试过")
ok("写权限" in rows5[0]["msg"], "失败原因翻译成中文提示", rows5[0]["msg"])

e = FakeAdb(fail_mkdir=True)
rows6 = U.upload_plan(e, plan, skip_same=False)
ok([r["status"] for r in rows6] == ["fail", "fail"], "建目录失败 → fail（不崩）")
ok("创建远端目录失败" in rows6[0]["msg"], "建目录失败有明确说明", rows6[0]["msg"])

f = FakeAdb()
seen = {"n": 0}


def _cancel():
    seen["n"] += 1
    return seen["n"] > 1        # 第一个文件后取消


rows7 = U.upload_plan(f, plan, skip_same=False, check_cancel=_cancel)
ok([r["status"] for r in rows7] == ["ok", "cancel"], "取消：已传的保留，剩余标为取消",
   str([r["status"] for r in rows7]))
ok(len(f.pushes) == 1, "取消后不再 push 剩余文件", str(len(f.pushes)))

g = FakeAdb()
missing = U.build_plan([{"local": os.path.join(tmp, "gone.py"), "rel": "gone.py"}], "/sdcard/")
rows8 = U.upload_plan(g, missing, skip_same=False)
ok(rows8[0]["status"] == "fail" and "不存在" in rows8[0]["msg"],
   "本地文件缺失 → fail 且说明原因", str(rows8[0]))

s = U.summarize(rows7)
ok(s == {"ok": 1, "skip": 0, "fail": 0, "cancel": 1, "total": 2}, "汇总统计正确", str(s))
ok(U.format_size(0) == "0 B" and U.format_size(1536) == "1.5 KB", "大小格式化",
   "%s / %s" % (U.format_size(0), U.format_size(1536)))

print("\n结果：%d 通过 / %d 失败" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
