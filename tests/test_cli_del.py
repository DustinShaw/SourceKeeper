# -*- coding: utf-8 -*-
"""端到端安全测试：CLI `--del --write` 删除配置项时一并删除对应 .py（仅临时副本）。"""
import os, sys, shutil, tempfile, importlib.util, hashlib

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("inj", os.path.join(HERE, "injector.py"))
inj = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inj)

REAL_CFG = os.path.join(HERE, "py.json")
real_md5 = hashlib.md5(open(REAL_CFG, "rb").read()).hexdigest()
real_py = len([f for f in os.listdir(os.path.join(HERE, "py")) if f.endswith(".py")])

tmp = tempfile.mkdtemp(prefix="pyinj_clidel_")
try:
    shutil.copy2(REAL_CFG, os.path.join(tmp, "py.json"))
    shutil.copytree(os.path.join(HERE, "py"), os.path.join(tmp, "py"))
    sites = (inj.parse_jsonc(open(os.path.join(tmp, "py.json"), encoding="utf-8").read())
             .get("sites", []) or [])
    tkey = str(sites[0].get("key", ""))
    tpath = inj.api_to_path(tmp, sites[0].get("api", ""))
    print("目标 key=%s  .py=%s" % (tkey, tpath))

    rc = inj.run_cli(["--repo", tmp, "--del", tkey, "--write"])
    print("run_cli rc=%d" % rc)

    # 验证：临时 py.json 不再含该 key，且 .py 已删、备份存在
    after = (inj.parse_jsonc(open(os.path.join(tmp, "py.json"), encoding="utf-8").read())
             .get("sites", []) or [])
    assert tkey not in [str(s.get("key", "")) for s in after], "配置项应已被删除"
    assert not os.path.isfile(tpath), ".py 应已被删除"
    trash = os.path.join(tmp, "py_trash")
    assert os.path.isdir(trash) and any(f.startswith(os.path.basename(tpath) + ".")
                                        for f in os.listdir(trash)), "py_trash 应有备份"
    print("临时副本：配置项已删、.py 已删、备份存在 ✓")

    # 真实仓库不被触碰
    md5_after = hashlib.md5(open(REAL_CFG, "rb").read()).hexdigest()
    py_after = len([f for f in os.listdir(os.path.join(HERE, "py")) if f.endswith(".py")])
    print("真实 md5 一致: %s | 真实 .py 数一致(%d): %s" %
          (md5_after == real_md5, real_py, py_after == real_py))
    print("CLI-DEL TEST %s" % ("OK" if (md5_after == real_md5 and py_after == real_py) else "FAIL"))
finally:
    shutil.rmtree(tmp, ignore_errors=True)
    print("已清理临时副本: %s" % tmp)
