# -*- coding: utf-8 -*-
"""v1.1 冒烟：对每个 循环 + 若/否则 + 列表字面量 + 空表/加入行。"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
import qiyu  # noqa: E402

SRC = '''
工具 测试 {
  说明 "循环与分支冒烟"
  能力 读 "~/inventory.csv"
  能力 写 "~/"
  缺货表 = 空表("SKU", "缺口")
  库存 = 读表格("~/inventory.csv")
  对每个 行 在 库存 {
    若 行.现库存 < 行.安全库存 {
      缺货表 = 加入行(缺货表, [行.SKU, 行.安全库存 - 行.现库存])
    }
  }
  存表格 缺货表 到 "~/out.csv"
  返回 缺货表
}
'''

r = qiyu.run_source(SRC, root=str(HERE.parent / "fixtures/T03"))
rows = r["结果"]
assert rows["行数"] == 5, rows  # 与 T03 筛选语义一致（等于不算）
print("✅ v1.1 冒烟通过：", rows)
