# -*- coding: utf-8 -*-
"""v1.4 冒烟：参数裸名直接可用。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import qiyu  # noqa: E402

SRC = '''
工具 测试 {
  说明 "参数裸名冒烟"
  参数 today: 文本
  能力 读 "~/customers.csv"
  表 = 读表格("~/customers.csv")
  返回 转文本(长度(today)) + "/" + 转文本(表.行数)
}
'''
r = qiyu.run_source(SRC, params={"today": "2024-06-15"},
                    root=str(Path(__file__).resolve().parent.parent / "fixtures/T07"))
assert r["结果"] == "10/6", r["结果"]
print("✅ v1.4 裸参数名冒烟通过：", r["结果"])
