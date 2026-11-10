# -*- coding: utf-8 -*-
"""v1.5 验证：之前编译失败的存档尝试，现在应当能解析。"""
import sys
from pathlib import Path

QY = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(QY / "src"))
import qiyu  # noqa: E402

CASES = [
    ("T02.qiyu.s1/_attempt_r0.qy", "对每行 隐式行变量"),
    ("T03.qiyu.s3/_attempt_r0.qy", "裸派生语句重绑"),
    ("T01.qiyu.s3/_attempt_r1.qy", "裸说明"),
]
for rel, why in CASES:
    p = QY / "experiment/runs" / rel
    if not p.exists():
        print(f"- 跳过（无存档）：{rel}")
        continue
    try:
        qiyu.parse_source(p.read_text(encoding="utf-8"))
        print(f"✅ {why}: {rel}")
    except qiyu.QiyuError as e:
        print(f"❌ {why}: {rel} → {e.human()}")
