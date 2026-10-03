# -*- coding: utf-8 -*-
"""端到端：仓库里没有 py.json、只有别名配置 jk.json 时，CLI 应自动识别并写入它。
全程在临时目录构造，真实仓库只读。"""
import os, json, shutil, tempfile, importlib.util, hashlib

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("inj", os.path.join(HERE, "injector.py"))
inj = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inj)

REAL_CFG = os.path.join(HERE, "py.json")
real_md5 = hashlib.md5(open(REAL_CFG, "rb").read()).hexdigest()

SITES = {"sites": [{"key": "py_a", "name": "A", "api": "./py/a.py", "type": 3}]}

t = tempfile.mkdtemp(prefix="cfgcli_")
try:
    # 仓库只有 jk.json（没有 py.json）
    open(os.path.join(t, "jk.json"), "w", encoding="utf-8").write(
        "// 这是注释\n" + json.dumps(SITES, ensure_ascii=False))
    os.makedirs(os.path.join(t, "py"))
    # 一个待扫描的 spider
    open(os.path.join(t, "py", "newsite.py"), "w", encoding="utf-8").write(
        "# -*- coding: utf-8 -*-\nclass Spider:\n    def getName(self):\n        return '新站点'\n")

    print("=== 1) --list 应自动识别 jk.json ===")
    rc = inj.run_cli(["--repo", t, "--list"])
    print("rc=%d" % rc)

    print("\n=== 2) --scan --write 应写入 jk.json（不是 py.json）===")
    rc = inj.run_cli(["--repo", t, "--scan", "--write"])
    print("rc=%d" % rc)

    data = inj.parse_jsonc(open(os.path.join(t, "jk.json"), encoding="utf-8").read())
    n = len(data.get("sites", []))
    has_new = any(s.get("key") == "py_newsite" for s in data.get("sites", []))
    bak = [f for f in os.listdir(os.path.join(t, "backups")) if f.startswith("jk.json.")] if os.path.isdir(os.path.join(t, "backups")) else []
    no_pyjson = not os.path.isfile(os.path.join(t, "py.json"))
    print("\njk.json 站点数=%d 新增 py_newsite=%s 备份=%s 未生成 py.json=%s"
          % (n, has_new, bool(bak), no_pyjson))

    print("\n=== 3) --config 显式指定另一个文件 ===")
    open(os.path.join(t, "alt.json"), "w", encoding="utf-8").write(json.dumps(SITES, ensure_ascii=False))
    rc = inj.run_cli(["--repo", t, "--config", "alt.json", "--list"])
    print("rc=%d" % rc)

    ok = (rc == 0 and n == 2 and has_new and bool(bak))
    print("\n=== 4) 真实仓库是否被触碰 ===")
    md5_after = hashlib.md5(open(REAL_CFG, "rb").read()).hexdigest()
    print("真实 py.json md5 一致: %s" % (real_md5 == md5_after))
    print("CLI-GENERIC-CFG TEST %s" % ("OK" if ok and real_md5 == md5_after else "FAIL"))
finally:
    shutil.rmtree(t, ignore_errors=True)
    print("已清理临时仓库")
