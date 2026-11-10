# -*- coding: utf-8 -*-
"""端点健康检查：加载 .env 发一个最小请求，只输出状态码，不回显密钥。"""
import json
import os
import sys
import urllib.request
from pathlib import Path

QY = Path(__file__).resolve().parent.parent
for cand in (QY / ".env", QY / "experiment/.env"):
    if cand.exists():
        for ln in cand.read_text(encoding="utf-8-sig").splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("#") and "=" in ln:
                k, v = ln.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

base = os.environ.get("QIYU_EXP_BASE_URL", "")
key = os.environ.get("QIYU_EXP_API_KEY", "")
if not (base and key):
    print("配置缺失（.env 里没有 BASE_URL / API_KEY）")
    sys.exit(2)
model = sys.argv[1] if len(sys.argv) > 1 else "MiniMax-M3"
body = json.dumps({"model": model,
                   "messages": [{"role": "user", "content": "回复：OK"}],
                   "max_tokens": 8}).encode("utf-8")
req = urllib.request.Request(base.rstrip("/") + "/chat/completions", data=body,
                             headers={"Content-Type": "application/json",
                                      "Authorization": "Bearer " + key})
try:
    with urllib.request.urlopen(req, timeout=120) as r:
        print(f"HTTP {r.status} · 端点正常 · 模型 {model}")
    sys.exit(0)
except urllib.error.HTTPError as e:
    print(f"HTTP {e.code} {e.reason}")
    sys.exit(1)
except Exception as e:
    print(f"网络错误: {e}")
    sys.exit(1)
