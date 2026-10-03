# -*- coding: utf-8 -*-
"""试验：QTableWidget 行号列（垂直表头）如何跟随数据行斑马纹。
渲染到 QImage 后采样像素颜色验证，不依赖目测。"""
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication, QTableWidget, QTableWidgetItem
from PySide6.QtGui import QColor, QImage
from PySide6.QtCore import Qt

QSS = (
    "QTableWidget { alternate-background-color: #eef4fb; background: #ffffff; }"
    "QHeaderView::section:horizontal { background: #34538a; color: #ffffff;"
    " font-weight: bold; padding: 5px 6px; border: none;"
    " border-right: 1px solid #2b4470; border-bottom: 2px solid #2b4470; }"
    "QTableCornerButton::section { background: #34538a; border: none; }")

# D 方案：横向表头 QSS 只挂在 horizontalHeader 自己身上，表本体样式不含任何 QHeaderView 规则
QSS_TBL = "QTableWidget { alternate-background-color: #eef4fb; background: #ffffff; }"
QSS_HDR = ("QHeaderView::section { background: #34538a; color: #ffffff; font-weight: bold;"
           " padding: 5px 6px; border: none; border-right: 1px solid #2b4470;"
           " border-bottom: 2px solid #2b4470; }")

app = QApplication([])

def build(with_item_bg, vh_qss=None, split_qss=False):
    t = QTableWidget(6, 3)
    t.setHorizontalHeaderLabels(["a", "b", "c"])
    t.setAlternatingRowColors(True)
    if split_qss == "noqss":
        pass  # 完全不设任何样式表
    elif split_qss:
        t.setStyleSheet(QSS_TBL)
        t.horizontalHeader().setStyleSheet(QSS_HDR)
    else:
        t.setStyleSheet(QSS + (vh_qss or ""))
    for r in range(6):
        for c in range(3):
            t.setItem(r, c, QTableWidgetItem("cell%d%d" % (r, c)))
        if with_item_bg:
            vh = QTableWidgetItem(str(r + 1))
            vh.setTextAlignment(Qt.AlignCenter)
            vh.setBackground(QColor("#eef4fb") if r % 2 == 1 else QColor("#ffffff"))
            t.setVerticalHeaderItem(r, vh)
    t.resize(400, 200)
    img = QImage(400, 200, QImage.Format_ARGB32)
    img.fill(0xFFFFFFFF)
    t.render(img)
    return t, img

def px(img, x, y):
    c = img.pixelColor(x, y)
    return (c.red(), c.green(), c.blue())

# 找垂直表头中心 x（行号列宽度）与某行中心 y
def probe(with_item_bg, vh_qss=None, label="", split_qss=False):
    t, img = build(with_item_bg, vh_qss, split_qss)
    app.processEvents()
    vhw = t.verticalHeader().width()
    hh = t.horizontalHeader().height()
    rowh = t.rowHeight(0)
    from collections import Counter
    rows = []
    for r in range(4):
        y = hh + r * rowh + rowh // 2
        cnt = Counter(px(img, x, y) for x in range(1, vhw - 1))
        main = cnt.most_common(1)[0][0] if cnt else None
        rows.append(main)
    zebra = len(set(rows)) >= 2
    print("%s 行号列主色 rows=%s 斑马纹=%s" % (label, rows, zebra))
    return zebra

ok1 = probe(True, None, "A) 表QSS含横向规则+item背景:", False)
okD = probe(True, None, "D) 表头QSS挂horizontalHeader+item背景:", True)
okE = probe(True, None, "E) 完全无QSS+item背景:", "noqss")

# 验证数据区斑马纹奇偶：采样第 0/1 行数据单元格背景
t, img = build(False, None, False)
app.processEvents()
hh2 = t.horizontalHeader().height()
vhw2 = t.verticalHeader().width()
rowh2 = t.rowHeight(0)
for r in range(2):
    y = hh2 + r * rowh2 + rowh2 // 2
    print("数据行 %d 背景采样 x=60: %s, x=120: %s" % (r, px(img, 60, y), px(img, 120, y)))
print("\n结论：A=%s D=%s E=%s" % (ok1, okD, okE))
