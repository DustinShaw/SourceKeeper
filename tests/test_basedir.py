# -*- coding: utf-8 -*-
"""回归：配置文件在子目录时，.py 应按「配置文件所在目录」解析，而非所选根目录。
复现用户场景：exe 放别处 -> 选中父目录 -> 自动找到 sub/xxx.json -> 但 .py 找不到。
全在临时目录构造，真实仓库只读。"""
import os, json, shutil, tempfile, importlib.util, hashlib

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("inj", os.path.join(HERE, "injector.py"))
inj = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inj)

REAL_CFG = os.path.join(HERE, "py.json")
real_md5 = hashlib.md5(open(REAL_CFG, "rb").read()).hexdigest()

ADULT_PY = ("# -*- coding: utf-8 -*-\n"
            "class Spider:\n"
            "    def homeContent(self, f):\n"
            "        return [{'type_name': '成人短剧'}]\n")

results = []


def check(name, cond, extra=""):
    results.append(bool(cond))
    print("[%s] %-52s %s" % ("OK " if cond else "FAIL", name, extra))


# === 场景 1：配置在子目录 sub/，py/ 在 sub/ 内 ===
t = tempfile.mkdtemp(prefix="basedir_sub_")
try:
    sub = os.path.join(t, "sub")
    os.makedirs(os.path.join(sub, "py"))
    cfg = {"sites": [{"key": "py_adult", "name": "成人站", "api": "./py/adult.py", "type": 3}]}
    open(os.path.join(sub, "jk.json"), "w", encoding="utf-8").write(json.dumps(cfg, ensure_ascii=False))
    open(os.path.join(sub, "py", "adult.py"), "w", encoding="utf-8").write(ADULT_PY)

    g = inj.guess_config_file(t)                 # 选中父目录 t
    check("1a 自动识别子目录配置", g == os.path.join("sub", "jk.json").replace("\\", "/"), "got=%s" % g)

    base = inj.cfg_base_dir(t, g)
    check("1b base_dir = 配置文件所在目录", os.path.abspath(base) == os.path.abspath(sub), "base=%s" % base)

    # 旧行为（按所选根目录解析）——确认确实找不到，说明这就是 bug 根因
    old = inj.api_to_path(t, "./py/adult.py")
    check("1c 旧解析(根目录)找不到.py", not os.path.isfile(old), "old=%s" % old)

    # 新行为：优先 base_dir，找不到再回退 alt_dir
    new = inj.resolve_spider_path(base, "./py/adult.py", t)
    check("1d 新解析(base_dir)命中.py", os.path.isfile(new), "new=%s" % new)

    is_ad, kw = inj.detect_adult(new, "成人站")
    check("1e 成人内容可检出", is_ad is True, "kw=%s" % kw)
finally:
    shutil.rmtree(t, ignore_errors=True)

# === 场景 2：常规布局（配置与 py/ 都在根）——不应回归 ===
t = tempfile.mkdtemp(prefix="basedir_root_")
try:
    os.makedirs(os.path.join(t, "py"))
    cfg = {"sites": [{"key": "py_adult", "name": "成人站", "api": "./py/adult.py", "type": 3}]}
    open(os.path.join(t, "py.json"), "w", encoding="utf-8").write(json.dumps(cfg, ensure_ascii=False))
    open(os.path.join(t, "py", "adult.py"), "w", encoding="utf-8").write(ADULT_PY)
    g = inj.guess_config_file(t)
    base = inj.cfg_base_dir(t, g)
    check("2a 常规布局识别 py.json", g == "py.json", "got=%s" % g)
    check("2b base_dir = 根目录", os.path.abspath(base) == os.path.abspath(t))
    p = inj.resolve_spider_path(base, "./py/adult.py", t)
    is_ad, kw = inj.detect_adult(p, "成人站")
    check("2c 成人内容可检出", is_ad is True, "kw=%s" % kw)
finally:
    shutil.rmtree(t, ignore_errors=True)

# === 场景 3：配置在子目录，但 py/ 仍在所选根目录（回退必须生效）===
t = tempfile.mkdtemp(prefix="basedir_fallback_")
try:
    sub = os.path.join(t, "sub")
    os.makedirs(sub)
    os.makedirs(os.path.join(t, "py"))
    cfg = {"sites": [{"key": "py_adult", "name": "成人站", "api": "./py/adult.py", "type": 3}]}
    open(os.path.join(sub, "jk.json"), "w", encoding="utf-8").write(json.dumps(cfg, ensure_ascii=False))
    open(os.path.join(t, "py", "adult.py"), "w", encoding="utf-8").write(ADULT_PY)
    g = inj.guess_config_file(t)
    base = inj.cfg_base_dir(t, g)
    p = inj.resolve_spider_path(base, "./py/adult.py", t)
    check("3a 回退到根目录命中.py", os.path.isfile(p), "p=%s" % p)
    is_ad, kw = inj.detect_adult(p, "成人站")
    check("3b 成人内容可检出", is_ad is True, "kw=%s" % kw)
finally:
    shutil.rmtree(t, ignore_errors=True)

md5_after = hashlib.md5(open(REAL_CFG, "rb").read()).hexdigest()
print("\n真实 py.json 未改动: %s" % (real_md5 == md5_after))
print("BASE-DIR TEST %s (%d/%d)" % ("OK" if all(results) and real_md5 == md5_after else "FAIL",
                                    sum(results), len(results)))
