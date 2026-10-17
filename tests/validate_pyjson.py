# -*- coding: utf-8 -*-
"""py.json JSONC 校验（字符串感知剥注释）"""
import json, os, sys

path = sys.argv[1] if len(sys.argv) > 1 else "py.json"
src = open(path, encoding="utf-8").read()
out = []
i, n = 0, len(src)
in_str = False
BS = chr(92)  # backslash
while i < n:
    ch = src[i]
    if in_str:
        out.append(ch)
        if ch == BS:
            if i + 1 < n:
                out.append(src[i + 1])
            i += 2
            continue
        if ch == '"':
            in_str = False
        i += 1
        continue
    if ch == '"':
        in_str = True
        out.append(ch)
        i += 1
        continue
    if ch == "/" and i + 1 < n and src[i + 1] == "/":
        j = src.find("\n", i)
        i = n if j < 0 else j
        continue
    out.append(ch)
    i += 1

d = json.loads("".join(out))
sites = d.get("sites") or []
keys = [s.get("key") for s in sites]
print("sites total:", len(sites))
if "MiguMV" in keys:
    idx = keys.index("MiguMV")
    print("MiguMV idx:", idx, "| neighbor:", keys[idx - 1], "->", keys[idx + 1])
    print("entry:", json.dumps(sites[idx], ensure_ascii=False))
    print("api file exists:", os.path.exists(os.path.join(os.path.dirname(path) or ".", "py", "MiguMV.py")))
else:
    print("MiguMV MISSING")
print("JSONC PARSE OK")
