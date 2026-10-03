# -*- coding: utf-8 -*-
"""测试配置文件识别（guess_config_file）：
A 真实仓库(有 py.json)  B 无 py.json 但有别名的 spider 配置  C 空目录
D 用户指定 hint 存在/不存在  E 一级子目录里的配置  F 非站点 json 不应命中
全部在临时目录构造，真实仓库只读。"""
import os, json, shutil, tempfile, importlib.util, hashlib

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("inj", os.path.join(HERE, "injector.py"))
inj = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inj)

REAL_CFG = os.path.join(HERE, "py.json")
real_md5 = hashlib.md5(open(REAL_CFG, "rb").read()).hexdigest()

SITES = {"sites": [{"key": "py_a", "name": "A", "api": "./py/a.py", "type": 3},
                   {"key": "py_b", "name": "B", "api": "./py/b.py", "type": 3}]}
NOTSITES = {"foo": 1, "bar": [1, 2, 3]}

results = []


def check(name, got, want):
    ok = (got == want)
    results.append(ok)
    print("[%s] %-42s got=%-18s want=%-18s" % ("OK " if ok else "FAIL", name, got, want))


# A 真实仓库：有 py.json，应精确命中
check("A 真实仓库(有 py.json)", inj.guess_config_file(HERE), "py.json")

# B 无 py.json，但有别名的 spider 配置 jk.json
t = tempfile.mkdtemp(prefix="cfg_b_")
try:
    open(os.path.join(t, "jk.json"), "w", encoding="utf-8").write(
        "// 注释\n" + json.dumps(SITES, ensure_ascii=False))
    check("B 别名配置 jk.json", inj.guess_config_file(t), "jk.json")
finally:
    shutil.rmtree(t, ignore_errors=True)

# C 空目录 -> None
t = tempfile.mkdtemp(prefix="cfg_c_")
try:
    check("C 空目录", inj.guess_config_file(t), None)
finally:
    shutil.rmtree(t, ignore_errors=True)

# D 用户指定 hint
t = tempfile.mkdtemp(prefix="cfg_d_")
try:
    open(os.path.join(t, "mine.json"), "w", encoding="utf-8").write(json.dumps(SITES, ensure_ascii=False))
    check("D1 hint 存在(mine.json)", inj.guess_config_file(t, "mine.json"), "mine.json")
    check("D2 hint 不存在", inj.guess_config_file(t, "nope.json"), None)
    # hint 存在但目录里也有 py.json 时仍尊重用户指定
    open(os.path.join(t, "py.json"), "w", encoding="utf-8").write(json.dumps(SITES, ensure_ascii=False))
    check("D3 hint 优先于 py.json", inj.guess_config_file(t, "mine.json"), "mine.json")
finally:
    shutil.rmtree(t, ignore_errors=True)

# E 一级子目录里的配置
t = tempfile.mkdtemp(prefix="cfg_e_")
try:
    os.makedirs(os.path.join(t, "sub"))
    open(os.path.join(t, "sub", "spider.json"), "w", encoding="utf-8").write(
        json.dumps(SITES, ensure_ascii=False))
    check("E 一级子目录 spider.json", inj.guess_config_file(t), "sub/spider.json")
finally:
    shutil.rmtree(t, ignore_errors=True)

# F 有 json 但不是站点配置 -> None
t = tempfile.mkdtemp(prefix="cfg_f_")
try:
    open(os.path.join(t, "other.json"), "w", encoding="utf-8").write(json.dumps(NOTSITES, ensure_ascii=False))
    check("F 非站点 json", inj.guess_config_file(t), None)
finally:
    shutil.rmtree(t, ignore_errors=True)

# G 多个候选：py 命名加分 + 站点数更多者胜
t = tempfile.mkdtemp(prefix="cfg_g_")
try:
    open(os.path.join(t, "zzz.json"), "w", encoding="utf-8").write(json.dumps({"sites": [{"key": "k1"}]}))
    open(os.path.join(t, "mypy.json"), "w", encoding="utf-8").write(json.dumps(SITES, ensure_ascii=False))
    check("G 多候选选 py 命名/站点多", inj.guess_config_file(t), "mypy.json")
finally:
    shutil.rmtree(t, ignore_errors=True)

# 备份文件不应被当配置
t = tempfile.mkdtemp(prefix="cfg_h_")
try:
    open(os.path.join(t, "py.json.bak.20260101"), "w", encoding="utf-8").write(json.dumps(SITES, ensure_ascii=False))
    check("H .bak 不参与识别", inj.guess_config_file(t), None)
finally:
    shutil.rmtree(t, ignore_errors=True)

md5_after = hashlib.md5(open(REAL_CFG, "rb").read()).hexdigest()
print("\n真实 py.json 未改动: %s" % (real_md5 == md5_after))
print("GUESS-CFG TEST %s (%d/%d)" % ("OK" if all(results) and real_md5 == md5_after else "FAIL",
                                     sum(results), len(results)))
