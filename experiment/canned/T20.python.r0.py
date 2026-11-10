import os
import shutil

date = "2024-06-07"  # 本次运行参数：date=2024-06-07
src_dir = os.path.expanduser("~/工作表")
dst = os.path.expanduser("~/备份/" + date)
os.makedirs(dst, exist_ok=True)

for name in os.listdir(src_dir):
    if not name.lower().endswith((".csv", ".xlsx")):
        continue
    s = os.path.join(src_dir, name)
    d = os.path.join(dst, name)
    if os.path.exists(d) and os.path.getsize(s) == os.path.getsize(d):
        continue  # 已备份且大小相同 → 跳过（幂等）
    shutil.copy2(s, d)
