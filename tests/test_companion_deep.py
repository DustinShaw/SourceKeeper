# -*- coding: utf-8 -*-
"""配套文件「深度搬运」测试（2026-09-30 用户反馈：搬运不彻底）
=================================================================
需求：搬一个 js/py 时，**它内部引用到的别的文件也要一并搬**；若目标目录已存在
同名文件且内容不同，从安全出发**重命名**并**同步改写引用它的引用串**。

覆盖：
  A) 本地深挖：require('./x.js') / require('b.js') 裸名 / import x from './c.js' /
     import './h.js' / load('./d.js') / require(`./e.js`) 模板串 / require('./lib/a') 无扩展名 /
     二级链（a.js → ../f.js）
  B) 本地冲突改名 + 引用改写（含裸名保持裸名、ESM、load、无扩展名风格保持）
  C) 内置/第三方裸名（fs / axios）不得被误当本地文件搬运
  D) 远程（file:// 模拟）同一套深挖 + 冲突改名

用法：python test_companion_deep.py
"""
import os
import sys
import io
import json
import tempfile
import shutil
from urllib.parse import urljoin

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import pyinj_core as C  # noqa: E402

PASS, FAIL = 0, 0


def ok(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ✓ %s" % name)
    else:
        FAIL += 1
        print("  ✗ %s  %s" % (name, extra))


def write(p, text):
    d = os.path.dirname(p)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)


def read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def mkrepo(root):
    return os.path.join(root, "src"), os.path.join(root, "tgt")


MAIN_JS = """// main.js 各种引用形态
var a = require('./lib/a.js');
var b = require('b.js');
import c from './c.js';
import './h.js';
load('./d.js');
var e = require(`./e.js`);
var g = require('./lib/a');
var fs = require('fs');
var axios = require('axios');
var lib2 = { mod: 'x' };
var dyn = require(lib2.mod);
"""

SRC_FILES = {
    "py/main.js": MAIN_JS,
    "py/lib/a.js": "var f = require('../f.js');\n",
    "py/b.js": "// b\n",
    "py/c.js": "// c\n",
    "py/d.js": "// d\n",
    "py/e.js": "// e\n",
    "py/f.js": "// f\n",
    "py/h.js": "// h\n",
}

DEEP_EXPECT = ["py/main.js", "py/lib/a.js", "py/b.js", "py/c.js",
               "py/d.js", "py/e.js", "py/f.js", "py/h.js"]

# ---------------------------------------------------------------- A) 本地深挖
print("== A) 本地：main.js 内所有引用形态都要一并搬运 ==")
tmp = tempfile.mkdtemp(prefix="pyinj_deep_")
src, tgt = mkrepo(tmp)
for rel, txt in SRC_FILES.items():
    write(os.path.join(src, rel.replace("/", os.sep)), txt)

st = C.copy_companions(src, tgt, [{"key": "js_main", "api": "./py/main.js", "type": 3}])
for rel in DEEP_EXPECT:
    ok("搬运 " + rel, os.path.isfile(os.path.join(tgt, rel.replace("/", os.sep))),
       "stats=%s" % st)
ok("stats.copied 覆盖全部 8 个文件", len(st["copied"]) == 8, st["copied"])
ok("未把内置/第三方裸名当文件（fs/axios 不在 missing_src）",
   not any(str(x).endswith(("fs", "axios")) for x in st["missing_src"]),
   st["missing_src"])
ok("无扩展名补全的噪声候选不刷 missing_src（无 *.js.py 之类）",
   not any(".js." in str(x) for x in st["missing_src"]), st["missing_src"])
shutil.rmtree(tmp, ignore_errors=True)

# 显式写出扩展名但源里真不存在 → 必须如实上报（不能被降噪吞掉）
tmp = tempfile.mkdtemp(prefix="pyinj_deep_miss_")
src, tgt = mkrepo(tmp)
write(os.path.join(src, "py", "n.js"), "var x = require('./nope.js');\nimport os\n")
st = C.copy_companions(src, tgt, [{"api": "./py/n.js"}])
ok("显式引用但源缺失 → 进 missing_src（如实上报）",
   any(str(x).endswith("nope.js") for x in st["missing_src"]), st["missing_src"])
ok("python stdlib（import os）不产生任何候选",
   not any(str(x).endswith(("os.py", "os.js", "os.drpy")) for x in st["missing_src"]),
   st["missing_src"])
shutil.rmtree(tmp, ignore_errors=True)

# ------------------------------------------------- B) 冲突改名 + 引用改写
print("\n== B) 目标同名不同内容 → 改名并改写引用 ==")
tmp = tempfile.mkdtemp(prefix="pyinj_deep2_")
src, tgt = mkrepo(tmp)
for rel, txt in SRC_FILES.items():
    write(os.path.join(src, rel.replace("/", os.sep)), txt)
# 目标已存在同名但内容不同的文件（模拟"名字相同内容不同"）
write(os.path.join(tgt, "py", "b.js"), "// OLD B\n")
write(os.path.join(tgt, "py", "c.js"), "// OLD C\n")
write(os.path.join(tgt, "py", "d.js"), "// OLD D\n")
write(os.path.join(tgt, "py", "lib", "a.js"), "// OLD A\n")
# 内容完全一致的：应跳过且不改写（本地站共用）
write(os.path.join(tgt, "py", "e.js"), "// e\n")

st = C.copy_companions(src, tgt, [{"key": "js_main", "api": "./py/main.js", "type": 3}])
ok("b.js → b_2.js 落地", os.path.isfile(os.path.join(tgt, "py", "b_2.js")), st["renamed"])
ok("c.js → c_2.js 落地", os.path.isfile(os.path.join(tgt, "py", "c_2.js")), st["renamed"])
ok("d.js → d_2.js 落地", os.path.isfile(os.path.join(tgt, "py", "d_2.js")), st["renamed"])
ok("lib/a.js → lib/a_2.js 落地",
   os.path.isfile(os.path.join(tgt, "py", "lib", "a_2.js")), st["renamed"])
ok("原 b.js 未被覆盖（内容仍是 OLD）",
   read(os.path.join(tgt, "py", "b.js")) == "// OLD B\n", read(os.path.join(tgt, "py", "b.js")))
ok("内容一致的 e.js 跳过", "py/e.js" in st["skipped"], st["skipped"])

main_txt = read(os.path.join(tgt, "py", "main.js"))
ok("改写 require('./lib/a.js') → ./lib/a_2.js",
   "require('./lib/a_2.js')" in main_txt, main_txt)
ok("改写裸名 require('b.js') → 'b_2.js'（保持裸名风格）",
   "require('b_2.js')" in main_txt, main_txt)
ok("改写 import c from './c.js' → './c_2.js'",
   "from './c_2.js'" in main_txt, main_txt)
ok("改写 load('./d.js') → './d_2.js'",
   "load('./d_2.js')" in main_txt, main_txt)
ok("改写无扩展名 require('./lib/a') → './lib/a_2'（保持无扩展名风格）",
   "require('./lib/a_2')" in main_txt, main_txt)
ok("无冲突的 e.js 引用保持原样（内容相同被跳过）",
   "require(`./e.js`)" in main_txt, main_txt)
ok("未误伤 fs / axios 裸名", "require('fs')" in main_txt and "require('axios')" in main_txt,
   main_txt)
ok("未误伤动态 require(lib2.mod)", "require(lib2.mod)" in main_txt, main_txt)
a2 = read(os.path.join(tgt, "py", "lib", "a_2.js"))
ok("二级链引用未被破坏（../f.js 仍在）", "../f.js" in a2, a2)
shutil.rmtree(tmp, ignore_errors=True)

# ------------------------------------------------------------ C) 无扩展名链
print("\n== C) 无扩展名引用：能解析到 .js 并搬运 ==")
tmp = tempfile.mkdtemp(prefix="pyinj_deep3_")
src, tgt = mkrepo(tmp)
write(os.path.join(src, "py", "m.js"), "var z = require('./sub/z');\n")
write(os.path.join(src, "py", "sub", "z.js"), "// z\n")
st = C.copy_companions(src, tgt, [{"api": "./py/m.js"}])
ok("无扩展名引用解析并搬运 sub/z.js",
   os.path.isfile(os.path.join(tgt, "py", "sub", "z.js")), st)
# 目标已有不同内容的 sub/z.js → 改名 + 改写（保持无扩展名风格）
write(os.path.join(tgt, "py", "sub", "z.js"), "// OLD Z\n")
shutil.rmtree(tgt, ignore_errors=True)
os.makedirs(tgt, exist_ok=True)
write(os.path.join(tgt, "py", "sub", "z.js"), "// OLD Z\n")
st = C.copy_companions(src, tgt, [{"api": "./py/m.js"}])
ok("冲突 → sub/z_2.js", os.path.isfile(os.path.join(tgt, "py", "sub", "z_2.js")), st["renamed"])
ok("改写为 require('./sub/z_2')",
   "require('./sub/z_2')" in read(os.path.join(tgt, "py", "m.js")),
   read(os.path.join(tgt, "py", "m.js")))
shutil.rmtree(tmp, ignore_errors=True)

# ----------------------------------------------------------------- D) 远程
print("\n== D) 远程（file://）：同一套深挖 + 冲突改名 ==")
tmp = tempfile.mkdtemp(prefix="pyinj_deep4_")
src, tgt = mkrepo(tmp)
for rel, txt in SRC_FILES.items():
    write(os.path.join(src, rel.replace("/", os.sep)), txt)
rb = urljoin("file:///" + src.replace("\\", "/") + "/", "./")
st = C.copy_companions_remote(rb, tgt, [{"api": "./py/main.js"}])
for rel in DEEP_EXPECT:
    ok("远程搬运 " + rel, os.path.isfile(os.path.join(tgt, rel.replace("/", os.sep))), st)
ok("远程 stats.copied 覆盖全部 8 个", len(st["copied"]) == 8, st["copied"])

# 远程 + 目标冲突：改名并改写
shutil.rmtree(tgt, ignore_errors=True)
os.makedirs(tgt, exist_ok=True)
write(os.path.join(tgt, "py", "b.js"), "// OLD B\n")
st = C.copy_companions_remote(rb, tgt, [{"api": "./py/main.js"}])
ok("远程冲突 → b_2.js", os.path.isfile(os.path.join(tgt, "py", "b_2.js")), st["renamed"])
ok("远程改写 require('b_2.js')",
   "require('b_2.js')" in read(os.path.join(tgt, "py", "main.js")),
   read(os.path.join(tgt, "py", "main.js")))
shutil.rmtree(tmp, ignore_errors=True)

# ------------------------------------------------------- E) 编码安全（不损坏文件）
print("\n== E) 非 UTF-8 引用文件：宁可不断链也不写坏文件 ==")
tmp = tempfile.mkdtemp(prefix="pyinj_deep5_")
src, tgt = mkrepo(tmp)
gbk = "var a = require('./b.js');\n// 中文注释\n".encode("gbk")
os.makedirs(os.path.join(src, "py"), exist_ok=True)
with open(os.path.join(src, "py", "g.js"), "wb") as f:
    f.write(gbk)
write(os.path.join(src, "py", "b.js"), "// b\n")
write(os.path.join(tgt, "py", "b.js"), "// OLD B\n")   # 触发 b.js 改名
st = C.copy_companions(src, tgt, [{"api": "./py/g.js"}])
with open(os.path.join(tgt, "py", "g.js"), "rb") as f:
    got = f.read()
ok("GBK 文件字节完全未被改动（不写坏）", got == gbk, got[:40])
ok("如实记入 ref_skipped_encoding", "py/g.js" in st.get("ref_skipped_encoding", []), st)
ok("改名仍然发生（b_2.js）", os.path.isfile(os.path.join(tgt, "py", "b_2.js")), st["renamed"])
shutil.rmtree(tmp, ignore_errors=True)

# ------------------------------------------------ F) ext 字段里的本地脚本路径
print("\n== F) ext 里藏的本地脚本路径：要搬、要改名、不误伤 URL/配置串 ==")

# F0) 识别层单测（噪声必须被挡住）
ok("ext dict: ./py/lib/x.js 被识别", C.iter_ext_refs({"ext": {"site": "./py/lib/x.js"}}) == {"py/lib/x.js"})
ok("ext JSON 串: 相对路径被识别",
   "py/lib/x.js" in C.iter_ext_refs({"ext": '{"site": "./py/lib/x.js"}'}))
ok("ext: http(s):// 不识别",
   C.iter_ext_refs({"ext": {"site": "https://a.com/py/x.js"}}) == set())
ok("ext: 绝对路径（含盘符）不识别",
   C.iter_ext_refs({"ext": {"p": "/opt/x.js"}}) == set()
   and C.iter_ext_refs({"ext": {"p": "D:/a/x.js"}}) == set())
ok("ext: 普通配置串/裸名不识别（无扩展名的带 ./ 除外）",
   C.iter_ext_refs({"ext": "1$22$33"}) == set()
   and C.iter_ext_refs({"ext": {"flag": "fs"}}) == set())
ok("ext: 带脚本扩展名的裸名识别（x.js）", C.iter_ext_refs({"ext": "x.js"}) == {"x.js"})
ok("ext: '|' 与 'k=v' 分隔都能切出",
   C.iter_ext_refs({"ext": "a=./py/lib/x.js|b=./py/lib/y.js"}) == {"py/lib/x.js", "py/lib/y.js"})

tmp = tempfile.mkdtemp(prefix="pyinj_ext_")
src, tgt = mkrepo(tmp)
write(os.path.join(src, "py", "lib", "x.js"), "// X\n")
write(os.path.join(src, "py", "lib", "y.js"), "// Y\n")

# F1) dict 形式 ext → 一并搬运
st = C.copy_companions(src, tgt, [{"key": "k1", "type": 3, "ext": {"site": "./py/lib/x.js"}}])
ok("dict ext 引用的 x.js 被搬运",
   os.path.isfile(os.path.join(tgt, "py", "lib", "x.js")), st)

# F2) JSON 串 ext（含 URL）→ 只搬本地那个
st = C.copy_companions(src, tgt, [{"key": "k2", "type": 3, "ext":
    '{"site": "./py/lib/y.js", "u": "https://a.com/py/z.js"}'}])
ok("JSON 串 ext 引用的 y.js 被搬运",
   os.path.isfile(os.path.join(tgt, "py", "lib", "y.js")), st)
ok("ext 里的 URL 不搬也不刷 missing_src",
   not any("z.js" in str(x) for x in st["missing_src"] + st["copied"]), st)

# F3) 远程（file://）同一套
tmp2 = tempfile.mkdtemp(prefix="pyinj_ext_r_")
src2, tgt2 = mkrepo(tmp2)
write(os.path.join(src2, "py", "lib", "x.js"), "// X\n")
rb = urljoin("file:///" + src2.replace("\\", "/") + "/", "./")
st = C.copy_companions_remote(rb, tgt2, [{"key": "k3", "type": 3,
                                          "ext": {"site": "./py/lib/x.js"}}])
ok("远程 ext 引用的脚本被下载（file:// 模拟）",
   os.path.isfile(os.path.join(tgt2, "py", "lib", "x.js")), st)
shutil.rmtree(tmp2, ignore_errors=True)

# F4) 目标同名不同内容 → 改名 + 同步改写 ext（各种 ext 形态都保持原风格）
for label, ext_in, get_out, expect in [
    ("dict",     {"site": "./py/lib/x.js"},   lambda o: o["ext"]["site"],     "./py/lib/x_2.js"),
    ("JSON 串",  '{"site": "./py/lib/x.js"}',
     lambda o: json.loads(o["ext"])["site"],                                  "./py/lib/x_2.js"),
    ("k=v 串",   "site=./py/lib/x.js",        lambda o: o["ext"],             "site=./py/lib/x_2.js"),
    ("裸路径",   "./py/lib/x.js",             lambda o: o["ext"],             "./py/lib/x_2.js"),
]:
    t = tempfile.mkdtemp(prefix="pyinj_ext_ren_")
    s1, t1 = mkrepo(t)
    write(os.path.join(s1, "py", "lib", "x.js"), "// NEW X\n")
    write(os.path.join(t1, "py", "lib", "x.js"), "// OLD X\n")   # 同名不同内容
    obj = {"key": "k4", "type": 3, "ext": json.loads(json.dumps(ext_in))}
    fp = C.plan_companion_files_local(s1, t1, [obj])
    ok("ext(%s) 冲突 → 改名 x_2.js" % label, fp["map"].get("py/lib/x.js") == "py/lib/x_2.js", fp["map"])
    C.copy_companions(s1, t1, [obj], plan=fp)
    ok("ext(%s) 落盘 x_2.js 且不改坏原名" % label,
       read(os.path.join(t1, "py", "lib", "x_2.js")) == "// NEW X\n"
       and read(os.path.join(t1, "py", "lib", "x.js")) == "// OLD X\n")
    C._apply_rename_to_entry(obj, fp["map"])
    ok("ext(%s) 引用被改写为新名" % label, get_out(obj) == expect, obj["ext"])
    shutil.rmtree(t, ignore_errors=True)

# F5) 端到端：apply_merge 后配置文本里 ext 的路径已是新名
tmp = tempfile.mkdtemp(prefix="pyinj_ext_e2e_")
s1, t1 = mkrepo(tmp)
write(os.path.join(s1, "py", "lib", "x.js"), "// NEW X\n")
write(os.path.join(t1, "py", "lib", "x.js"), "// OLD X\n")
raw = ('{"sites": [{"key": "a", "name": "A", "api": "csp_Other", "type": 3}]}')
inc = C.load_sites_from_text(
    '{"sites": [{"key": "n1", "name": "N1", "type": 3, "ext": {"site": "./py/lib/x.js"}}]}')
rows = C.plan_merge(C.parse_sites_with_disabled(raw), inc)["rows"]
fp = C.plan_companion_files_local(s1, t1, [r["obj"] for r in rows if r["action"] == "add"])
nt, _stt, fst = C.apply_merge(raw, rows, src_repo_dir=s1, target_repo_dir=t1, file_plan=fp)
n1 = [x for x in json.loads(nt)["sites"] if x["key"] == "n1"][0]
ok("apply_merge 后配置里 ext 指向新名", n1["ext"]["site"] == "./py/lib/x_2.js", n1.get("ext"))
ok("apply_merge 后 ext 引用的文件确实落盘",
   os.path.isfile(os.path.join(t1, "py", "lib", "x_2.js")), fst)
shutil.rmtree(tmp, ignore_errors=True)

shutil.rmtree(tmp, ignore_errors=True)   # F 段最初的临时目录

print("\n结果：%d 通过, %d 失败" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
