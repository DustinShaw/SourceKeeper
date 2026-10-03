# -*- coding: utf-8 -*-
"""生成 PyInjector 图标 icon.ico（纯标准库，无需 PIL）。
设计：蓝色渐变圆角方块 + 白色闪电（象征"注入"）。
输出：icon.ico（多尺寸）+ icon_preview.png（256，便于预览）。"""

import struct
import zlib
import os

# 闪电多边形顶点（归一化 0-1，经典 zap 形状）
ZAP = [
    (0.56, 0.06),
    (0.34, 0.50),
    (0.47, 0.50),
    (0.41, 0.94),
    (0.74, 0.38),
    (0.59, 0.38),
    (0.68, 0.06),
]


def in_poly(px, py, poly):
    """射线法判断点是否在多边形内。"""
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def in_round_rect(x, y, s, r):
    """点是否在圆角矩形 [0,s]x[0,s]、圆角半径 r 内。"""
    if x < 0 or y < 0 or x >= s or y >= s:
        return False
    # 四角圆心
    cx = r if x < r else (s - r if x >= s - r else x)
    cy = r if y < r else (s - r if y >= s - r else y)
    dx, dy = x - cx, y - cy
    return dx * dx + dy * dy <= r * r if (x < r or x >= s - r) and (y < r or y >= s - r) else True


def lerp(c1, c2, t):
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


def render(size):
    """渲染一个 size x size 的 RGBA 图标，返回 bytes。"""
    top = (96, 156, 255)     # #609CFF 亮蓝
    bot = (24, 74, 200)      # #184AC8 深蓝
    radius = size * 0.20
    zap = [(x * size, y * size) for x, y in ZAP]
    # 闪电描边（略大的多边形，做白色外发光/描边）
    px = bytearray(size * size * 4)
    for y in range(size):
        for x in range(size):
            idx = (y * size + x) * 4
            if in_round_rect(x + 0.0, y + 0.0, size, radius):
                t = y / size
                r, g, b = lerp(top, bot, t)
                px[idx] = r
                px[idx + 1] = g
                px[idx + 2] = b
                px[idx + 3] = 255
                # 闪电
                if in_poly(x + 0.5, y + 0.5, zap):
                    px[idx] = 255
                    px[idx + 1] = 255
                    px[idx + 2] = 255
                    px[idx + 3] = 255
    return bytes(px)


def png_chunk(tag, data):
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff)


def make_png(w, h, rgba):
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    raw = b""
    stride = w * 4
    for y in range(h):
        raw += b"\x00" + rgba[y * stride:(y + 1) * stride]
    idat = zlib.compress(raw, 9)
    return b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", ihdr) + png_chunk(b"IDAT", idat) + png_chunk(b"IEND", b"")


def make_ico(pngs):
    header = struct.pack("<HHH", 0, 1, len(pngs))
    entries = b""
    data = b""
    offset = 6 + 16 * len(pngs)
    for size, png in pngs:
        b = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", b, b, 0, 0, 1, 32, len(png), offset)
        data += png
        offset += len(png)
    return header + entries + data


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    sizes = [16, 24, 32, 48, 64, 128, 256]
    pngs = [(s, make_png(s, s, render(s))) for s in sizes]
    ico_path = os.path.join(here, "icon.ico")
    with open(ico_path, "wb") as f:
        f.write(make_ico(pngs))
    print("已生成", ico_path, os.path.getsize(ico_path), "bytes")
    # 预览图（256）
    pv = os.path.join(here, "icon_preview.png")
    with open(pv, "wb") as f:
        f.write(pngs[-1][1])
    print("已生成", pv)


if __name__ == "__main__":
    main()
