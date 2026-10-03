# -*- coding: utf-8 -*-
"""扫描 py/ 目录时的反向校验测试：已注册配置项对应 .py 是否存在。
覆盖 check_missing_py / check_missing_py_resilient 与 CLI --scan。"""
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import injector

PY = sys.executable   # 用当前解释器，跨机器可跑（勿硬编码具体机器路径）
INJ = os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "injector.py"))

n_ok = n_bad = 0


def ok(cond, label, extra=""):
    global n_ok, n_bad
    if cond:
        n_ok += 1
        print("  ok  %s" % label)
    else:
        n_bad += 1
        print("FAIL  %s  %s" % (label, extra))


SPIDER = "class Spider:\n    pass\n"


def make_repo():
    tmp = tempfile.mkdtemp(prefix="pyinj_miss_")
    os.makedirs(os.path.join(tmp, "py"))
    os.makedirs(os.path.join(tmp, "moved"))
    # ok.py 存在；gone.py 缺失；relocated.py 被移到 moved/ 子目录
    with open(os.path.join(tmp, "py", "ok.py"), "w", encoding="utf-8") as f:
        f.write(SPIDER)
    with open(os.path.join(tmp, "moved", "relocated.py"), "w", encoding="utf-8") as f:
        f.write(SPIDER)
    sites = [
        {"key": "py_ok", "name": "好站", "api": "./py/ok.py", "type": 3,
         "filterable": 1, "quickSearch": 1, "searchable": 1},
        {"key": "py_gone", "name": "丢失站", "api": "./py/gone.py", "type": 3,
         "filterable": 1, "quickSearch": 1, "searchable": 1},
        {"key": "py_reloc", "name": "搬走站", "api": "./py/relocated.py", "type": 3,
         "filterable": 1, "quickSearch": 1, "searchable": 1},
        {"key": "dr_remote", "name": "远程站", "api": "http://example.com/x.py", "type": 3,
         "filterable": 1, "quickSearch": 1, "searchable": 1},
    ]
    raw = '{\n  "spider": "",\n  "sites": [\n'
    raw += ",\n".join("    " + json.dumps(s, ensure_ascii=False) for s in sites)
    raw += "\n  ]\n}\n"
    with open(os.path.join(tmp, "py.json"), "w", encoding="utf-8") as f:
        f.write(raw)
    return tmp, sites


def main():
    tmp, sites = make_repo()
    print("== check_missing_py（仅直接解析）==")
    missing, relocated = injector.check_missing_py(tmp, sites, tmp)
    ok([k for k, _ in missing] == ["py_gone", "py_reloc"],
       "直接解析：gone+reloc 均缺失", str(missing))
    ok(relocated == [], "直接解析：无找回项", str(relocated))

    print("== check_missing_py_resilient（带遍历找回）==")
    missing2, relocated2 = injector.check_missing_py_resilient(tmp, sites, tmp, "py.json")
    ok([k for k, _ in missing2] == ["py_gone"], "遍历后仅 gone 缺失", str(missing2))
    ok(len(relocated2) == 1 and relocated2[0][0] == "py_reloc",
       "reloc 经遍历找回", str(relocated2))
    ok(relocated2 and relocated2[0][2].endswith(os.path.join("moved", "relocated.py")),
       "找回路径指向 moved/", relocated2[0][2] if relocated2 else "")

    print("== 全部存在时返回空 ==")
    m3, r3 = injector.check_missing_py(tmp, [sites[0]], tmp)
    ok(m3 == [] and r3 == [], "仅 ok.py 时无缺失")

    print("== 远程 api 跳过 ==")
    m4, r4 = injector.check_missing_py(tmp, [sites[3]], tmp)
    ok(m4 == [] and r4 == [], "http api 不参与存在性校验")

    print("== CLI --scan 输出反向校验 ==")
    r = subprocess.run([PY, INJ, "--scan", "--repo", tmp],
                       capture_output=True, timeout=60)
    out = r.stdout.decode("utf-8", "replace")
    ok(r.returncode == 0, "CLI 退出码 0", "rc=%s err=%s" % (r.returncode, r.stderr.decode("utf-8", "replace")[-200:]))
    ok("缺失 .py：py_gone" in out, "CLI 报告 gone 缺失")
    ok("已在别处找回" in out and "py_reloc" in out, "CLI 报告 reloc 找回")
    ok("均存在" not in out, "有缺失时不再报『均存在』")

    print("\n== CLI --scan 全部存在时 ==")
    tmp2 = tempfile.mkdtemp(prefix="pyinj_ok_")
    os.makedirs(os.path.join(tmp2, "py"))
    with open(os.path.join(tmp2, "py", "ok.py"), "w", encoding="utf-8") as f:
        f.write(SPIDER)
    raw2 = '{\n  "sites": [\n    ' + json.dumps(sites[0], ensure_ascii=False) + '\n  ]\n}\n'
    with open(os.path.join(tmp2, "py.json"), "w", encoding="utf-8") as f:
        f.write(raw2)
    r2 = subprocess.run([PY, INJ, "--scan", "--repo", tmp2],
                        capture_output=True, timeout=60)
    out2 = r2.stdout.decode("utf-8", "replace")
    ok(r2.returncode == 0, "CLI(全存在) 退出码 0")
    ok("均存在" in out2, "CLI 报告全部存在")

    print("\n结果：%d 通过, %d 失败" % (n_ok, n_bad))
    return 1 if n_bad else 0


if __name__ == "__main__":
    sys.exit(main())
