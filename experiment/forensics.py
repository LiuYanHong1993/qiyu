# -*- coding: utf-8 -*-
"""批量取证：解析所有失败格的存档尝试，输出错误码直方图与典型案例。"""
import sys
from collections import Counter
from pathlib import Path

QY = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(QY / "src"))
import qiyu  # noqa: E402

hist = Counter()
examples = {}
for f in sorted((QY / "experiment/runs").glob("*.qiyu.s*/_attempt_r*.qy")):
    cell = f.parent.name
    try:
        src = f.read_text(encoding="utf-8")
    except Exception:
        continue
    try:
        qiyu.parse_source(src)
        qiyu.static_check(qiyu.parse_source(src))
        continue  # 修复成功前的失败尝试才记录
    except qiyu.QiyuError as e:
        hist[e.code] += 1
        examples.setdefault(e.code, []).append((cell, f.name, e.message[:70], e.fix[:60]))

print("编译失败直方图（存档的失败尝试）")
for code, n in hist.most_common():
    print(f"  {code}: {n}")
print()
for code, lst in examples.items():
    for cell, fn, msg, fix in lst[:4]:
        print(f"[{code}] {cell}/{fn}")
        print(f"   {msg}")
