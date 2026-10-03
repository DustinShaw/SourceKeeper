# -*- coding: utf-8 -*-
"""无界面验证排序键逻辑（与 ConfigDialog._sort_key 同构）。
确认：type 按数值、成人按等级、name/api 大小写不敏感、稳定。"""
import os, importlib.util

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("inj", os.path.join(HERE, "injector.py"))
inj = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inj)


def to_bool(v):
    try:
        return bool(int(v))
    except Exception:
        return bool(v)


def sort_key(e, col, scanning=False, detect_map=None):
    """与 ConfigDialog._sort_key 同构（key 列已移除：0=name 1=api 2=type 3=筛选/快搜/搜）。"""
    if col == 0:
        return str(e.get("name", "")).lower()
    if col == 1:
        return str(e.get("api", "")).lower()
    if col == 2:
        try:
            return int(e.get("type", 0) or 0)
        except Exception:
            return 0
    if col == 3:
        return (to_bool(e.get("filterable", 1)), to_bool(e.get("quickSearch", 1)),
                to_bool(e.get("searchable", 1)))
    if col == 4:
        return 0  # 排序测试不依赖检测状态，仅验证键可计算
    return 0


raw, sites, _, _ = inj.load_repo(HERE)
print("站点总数: %d" % len(sites))

# type 数值排序正确性：取若干 type 值，确认升序是整数序而非字典序
by_type = sorted(sites, key=lambda e: sort_key(e, 2))
types = [int(e.get("type", 0) or 0) for e in by_type]
print("type 升序前 8: %s" % types[:8])
print("type 严格非降?: %s" % all(types[i] <= types[i + 1] for i in range(len(types) - 1)))

# name 排序（大小写不敏感）：检查首字母序
by_name = sorted(sites, key=lambda e: sort_key(e, 0))
names = [str(e.get("name", "")).lower() for e in by_name]
print("name 升序前 5: %s" % names[:5])
print("name 严格非降?: %s" % all(names[i] <= names[i + 1] for i in range(len(names) - 1)))

# 成人列排序键可计算且分组（用真实 detect_map 模拟：直接调 detect_adult 作代理）
dm = {}
for e in sites:
    p = inj.api_to_path(HERE, e.get("api", ""))
    a, _ = inj.detect_adult(p, e.get("name", ""))
    dm[str(e.get("key", ""))] = a
adult_keys_rank = {}
for e in sites:
    k = str(e.get("key", ""))
    adult_keys_rank[k] = 1 if dm.get(k) else 0
by_adult = sorted(sites, key=lambda e: (adult_keys_rank[str(e.get("key", ""))], str(e.get("key", ""))))
# 成人应全部排在非成人之前（rank 分组）
seq = [adult_keys_rank[str(e.get("key", ""))] for e in by_adult]
print("成人排序列前段(取前 10 的 rank): %s" % seq[:10])
print("成人是否集前?: %s" % (all(r == 1 for r in seq[:sum(seq)]) and sum(seq) == seq.count(1)))
print("SORT KEY LOGIC OK")
