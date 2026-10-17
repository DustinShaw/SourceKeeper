# -*- coding: utf-8 -*-
"""在 wonder.js 中定位 ppt 默认值与 ee(md5) 函数"""
import re

src = open('tests/tmp/wonder.js', encoding='utf-8', errors='ignore').read()

pats = [
    r'ppt\s*[:=]\s*["\']?\d{6,}',
    r'_params\s*=\s*\{',
    r'ppt\s*:\s*["\']?\d',
]
for pat in pats:
    m = re.search(pat, src)
    if m:
        i = m.start()
        print('PAT:', pat, '@', i)
        print(src[max(0, i - 250):i + 250])
        print('=' * 70)

# ee 函数定义
for pat in ['function ee(', 'ee=function', 'const ee=', 'var ee=']:
    i = src.find(pat)
    if i != -1:
        print('EE DEF:', pat)
        print(src[i:i + 400])
        print('=' * 70)
        break

# md5 关键字
for m in re.finditer(r'md5', src[:2000000]):
    i = m.start()
    seg = src[max(0, i - 120):i + 120]
    if 'function' in seg or 'require' in seg or 'lib' in seg:
        print('MD5:', seg)
        print('=' * 70)
        break
