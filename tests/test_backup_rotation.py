# -*- coding: utf-8 -*-
"""v2026.09.25.b 备份轮转测试（真实 PySide6 offscreen 不需要，纯核心逻辑）：
1) backup_and_write 备份落入 repo/backups/（不再散落配置同目录）
2) 连续写 12 次 → 轮转只留最近 10 份（BACKUP_KEEP）
3) 最新备份内容 = 写入前配置内容；list_backups 新→旧有序
4) 旧版本散落的 <cfg>.bak.<ts> 文件不受影响（兼容历史）
"""
import os, sys, json, tempfile, shutil, importlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pyinj_core as I

PASS = 0
FAIL = 0


def ok(cond, msg, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ✓ %s" % msg)
    else:
        FAIL += 1
        print("  ✗ %s  %s" % (msg, extra))


def main():
    tmp = tempfile.mkdtemp(prefix="pyinj_bak_")
    try:
        cfg = os.path.join(tmp, "py.json")
        with open(cfg, "w", encoding="utf-8") as f:
            json.dump({"sites": [{"key": "k0", "name": "n0", "api": "./py/a.py", "type": 3}]}, f)

        print("\n=== 1) 备份落入 backups/ 目录 ===")
        bak1 = I.backup_and_write(tmp, '{"sites": []}')
        ok(os.path.dirname(bak1) == os.path.join(tmp, "backups"), "备份在 backups/ 子目录", bak1)
        ok(os.path.basename(bak1).startswith("py.json.") and bak1.endswith(".bak"), "命名 <cfg>.<ts>.bak", os.path.basename(bak1))
        ok(not [f for f in os.listdir(tmp) if f.startswith("py.json.")], "配置同目录不再产生备份")
        with open(bak1, encoding="utf-8") as f:
            ok('"k0"' in f.read(), "备份内容 = 写入前配置")

        print("\n=== 2) 连续写 12 次 → 轮转只留 10 份 ===")
        for i in range(1, 12):
            I.backup_and_write(tmp, '{"sites": [], "i": %d}' % i)
        baks = I.list_backups(tmp)
        ok(len(baks) == I.BACKUP_KEEP, "backups/ 恰好保留 %d 份" % I.BACKUP_KEEP, "实际 %d" % len(baks))
        with open(baks[0], encoding="utf-8") as f:
            ok('"i": 10' in f.read(), "最新一份是最后一次调用（i=11）写入前的内容（即 i=10 时的配置）")

        print("\n=== 3) list_backups 新→旧有序 ===")
        mtimes = [os.path.getmtime(p) for p in baks]
        ok(mtimes == sorted(mtimes, reverse=True), "mtime 严格倒序")
        ok(all(os.path.basename(p).startswith("py.json.") for p in baks), "全部是该配置的备份")

        print("\n=== 4) 历史散落备份兼容 ===")
        legacy = os.path.join(tmp, "py.json.bak.20260101")
        open(legacy, "w", encoding="utf-8").write("{}")
        I.backup_and_write(tmp, '{"sites": []}')
        ok(os.path.isfile(legacy), "旧散落备份不被清理/不受影响")
        ok(len(I.list_backups(tmp)) == I.BACKUP_KEEP, "轮转后仍为 %d 份" % I.BACKUP_KEEP)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n结果：%d 通过, %d 失败" % (PASS, FAIL))
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
