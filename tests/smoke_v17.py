# -*- coding: utf-8 -*-
"""v1.7 冒烟：五连修（加行语句化/无括号体/参数省注解/裸路径/不为空）。"""
import sys
from pathlib import Path

QY = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(QY / "src"))
import qiyu  # noqa: E402

SRC = '''
工具 冒烟 {
  说明 无引号说明文本
  参数 today = 2024-06-15
  能力 读 ~/customers.csv
  能力 写 ~/out.csv
  表 = 读表格(~/customers.csv)
  干净 = 空表("客户")
  对 行 在 表
    若 不为空(行.客户) { 干净 = 加入行(干净, [行.客户]) }
  存表格 干净 到 ~/out.csv
  返回 干净
}
'''
tool = qiyu.parse_source(SRC)
qiyu.static_check(tool)
r = qiyu.run_source(SRC, params={"today": "2024-06-15"}, root=str(QY / "fixtures/T07"))
assert r["结果"]["行数"] == 6, r["结果"]
print("✅ v1.7 五连修冒烟通过：", r["结果"])

for rel in ("T09.qiyu.s2/_attempt_r0.qy", "T13.qiyu.s1/_attempt_r0.qy",
            "T16.qiyu.s3/_attempt_r2.qy", "T06.qiyu.s1/_attempt_r2.qy"):
    p = QY / "experiment/runs" / rel
    if not p.exists():
        continue
    try:
        qiyu.parse_source(p.read_text(encoding="utf-8"))
        print(f"✅ 存档复活：{rel}")
    except qiyu.QiyuError as e:
        print(f"⚠️ 存档仍败：{rel} → {e.human()[:80]}")
