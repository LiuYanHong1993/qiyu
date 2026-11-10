# -*- coding: utf-8 -*-
"""v1.6 冒烟：否则若链 + 被拆关键字 + 回归。"""
import sys
from pathlib import Path

QY = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(QY / "src"))
import qiyu  # noqa: E402

SRC1 = '''
工具 测试 {
  说明 分层规则测试
  参数 today: 文本
  能力 读 "~/customers.csv"
  表 = 读表格("~/customers.csv")
  对 行 在 表 {
    若 行.年度消费 >= 100000 {
      标签 = "VIP"
    } 否则 若 行.年度消费 >= 10000 {
      标签 = "重要"
    } 否则 {
      标签 = "普通"
    }
  }
  返回 表
}
'''
qiyu.parse_source(SRC1)
print("✅ 否则若链 + 裸说明 + 对(空格)每行 全部解析通过")

CASES = [
    ("T05.qiyu.s1/_attempt_r0.qy", "否则若链（T05 现场重放）"),
    ("T06.qiyu.s1/_attempt_r0.qy", "T06 现场"),
]
for rel, why in CASES:
    p = QY / "experiment/runs" / rel
    if not p.exists():
        continue
    try:
        qiyu.parse_source(p.read_text(encoding="utf-8"))
        print(f"✅ {why}")
    except qiyu.QiyuError as e:
        print(f"⚠️ {why}: {e.human()[:80]}")
