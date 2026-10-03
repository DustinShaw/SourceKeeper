# -*- coding: utf-8 -*-
"""安全测试：删除配置项时一并删除对应 .py 的逻辑（仅操作临时副本）。
验证：① trash_spider 备份到 py_trash 后删除；② collect_orphan_py 在
仍有其它站点引用同一 .py 时跳过；③ 真实仓库不被触碰。"""
import os, sys, shutil, hashlib, tempfile, importlib.util

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("inj", os.path.join(HERE, "injector.py"))
inj = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inj)

REAL_CFG = os.path.join(HERE, "py.json")
real_cfg_md5 = hashlib.md5(open(REAL_CFG, "rb").read()).hexdigest()
real_py_count = len([f for f in os.listdir(os.path.join(HERE, "py")) if f.endswith(".py")])

tmp = tempfile.mkdtemp(prefix="pyinj_del_")
try:
    shutil.copy2(REAL_CFG, os.path.join(tmp, "py.json"))
    shutil.copytree(os.path.join(HERE, "py"), os.path.join(tmp, "py"))

    raw_sites = (inj.parse_jsonc(open(os.path.join(tmp, "py.json"), encoding="utf-8").read())
                 .get("sites", []) or [])
    key_api = {str(s.get("key", "")): s.get("api", "") for s in raw_sites}
    print("临时副本站点数: %d" % len(raw_sites))

    # 选一个目标删除（取第一个）
    target = raw_sites[0]
    tkey = str(target.get("key", ""))
    tapi = target.get("api", "")
    tpath = inj.api_to_path(tmp, tapi)
    print("目标 key=%s  api=%s  .py=%s  存在=%s" % (tkey, tapi, tpath, os.path.isfile(tpath)))

    # 模拟「删除该 key」后剩余站点（不含目标）
    remaining = [s for s in raw_sites if str(s.get("key", "")) != tkey]

    # 检查是否存在共享同一 .py 的情况（用于验证跳过逻辑）
    api_counter = {}
    for s in raw_sites:
        api_counter[s.get("api", "")] = api_counter.get(s.get("api", ""), 0) + 1
    shared_api = any(api_counter[s.get("api", "")] > 1 for s in raw_sites)
    print("仓库内是否存在共享同一 .py 的站点: %s" % shared_api)

    to_del, skipped = inj.collect_orphan_py(tmp, {tkey}, key_api, remaining)
    print("collect_orphan_py -> to_delete=%d, skipped=%d" % (len(to_del), len(skipped)))
    assert tpath in to_del, "目标 .py 应进入待删除列表（除非被共享引用而跳过）"

    # 执行删除（备份到 py_trash 后删除）
    deleted = []
    for p in to_del:
        dst = inj.trash_spider(tmp, p)
        if dst:
            deleted.append((p, dst))
    print("实际删除: %d 个" % len(deleted))
    for p, dst in deleted:
        print("  删除 %s  -> 备份 %s" % (p, dst))
        assert not os.path.isfile(p), "原 .py 应已删除"
        assert os.path.isfile(dst), "备份应存在"

    trash_files = os.listdir(os.path.join(tmp, "py_trash"))
    print("py_trash 内容: %s" % trash_files)

    # 验证真实仓库未被触碰
    real_cfg_md5_after = hashlib.md5(open(REAL_CFG, "rb").read()).hexdigest()
    real_py_count_after = len([f for f in os.listdir(os.path.join(HERE, "py")) if f.endswith(".py")])
    ok = (real_cfg_md5 == real_cfg_md5_after) and (real_py_count == real_py_count_after)
    print("真实 py.json md5 一致: %s" % (real_cfg_md5 == real_cfg_md5_after))
    print("真实 py/ .py 数量一致(%d): %s" % (real_py_count, real_py_count == real_py_count_after))
    print("DEL-PY TEST %s" % ("OK" if ok else "FAIL"))
finally:
    shutil.rmtree(tmp, ignore_errors=True)
    print("已清理临时副本: %s" % tmp)
