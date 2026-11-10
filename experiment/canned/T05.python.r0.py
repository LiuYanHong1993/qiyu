import csv
import os
import shutil
from datetime import datetime
from pathlib import Path

root = Path(os.path.expanduser("~"))
target_root = root / "归档"
log = []

pdfs = sorted(
    [p for p in (root / "下载").rglob("*.pdf") if p.is_file()],
    key=lambda p: p.relative_to(root).as_posix())
for p in pdfs:
    name = p.name
    parts = name[:-4].split("_")  # 去掉 .pdf 再切段
    supplier, raw_date = parts[0], parts[1]
    d = None
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y/%m/%d"):
        try:
            d = datetime.strptime(raw_date, fmt).date()
            break
        except ValueError:
            pass
    dest_dir = target_root / f"{d.year:04d}-{d.month:02d}" / supplier
    dest = dest_dir / name
    if dest.exists():
        dest = dest_dir / (name[:-4] + "_2.pdf")
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(p), str(dest))
    log.append([p.relative_to(root).as_posix(), dest.relative_to(root).as_posix()])

with open(target_root / "archive_log.csv", "w", encoding="utf-8-sig", newline="") as f:
    w = csv.writer(f, lineterminator="\r\n")
    w.writerow(["原路径", "新路径"])
    w.writerows(log)
