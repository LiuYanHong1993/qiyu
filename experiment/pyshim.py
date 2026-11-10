# -*- coding: utf-8 -*-
"""Python 侧外设 mock：把 smtplib / requests / urllib.request 替换为记录器。

由 harness 生成的 _runner.py 在执行被测脚本前 install()。所有调用写入
./_mock_records.jsonl（工作目录 = 实验沙箱根），格式与契语的审计记录对齐：

  发邮件  {"种类","发件人","收件","主题","内容"}
  发消息  {"种类","到","内容"}                  # requests.post 一律视为 IM 推送
  请求    {"种类","方法","网址"}                 # requests.get / urlopen

mock API 响应来自 _mock_api.json：[{"url_prefix": …, "responses": [body, …]}]，
同一前缀按调用次序依次返回（越界时重复最后一个）。
"""
import io
import json
import re
import sys
import types
from email.header import decode_header, make_header
from pathlib import Path


def _subject(msg):
    raw = msg if isinstance(msg, str) else bytes(msg).decode("utf-8", "replace")
    for line in raw.splitlines():
        if line.lower().startswith("subject:"):
            v = line[8:].strip()
            try:
                v = str(make_header(decode_header(v)))
            except Exception:
                pass
            return v
    return ""


def install():
    mp = Path("_mock_api.json")
    mock_api = json.loads(mp.read_text(encoding="utf-8")) if mp.exists() else []
    rec_path = Path("_mock_records.jsonl")

    def rec(d):
        with open(rec_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(d, ensure_ascii=False, default=str) + "\n")

    # ---- smtplib ------------------------------------------------------
    smtplib = types.ModuleType("smtplib")

    class SMTP:
        def __init__(self, host="localhost", port=0, **kw):
            self.host = host

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self, **kw):
            pass

        def login(self, *a, **kw):
            pass

        def sendmail(self, from_addr, to_addrs, msg, **kw):
            tos = to_addrs if isinstance(to_addrs, (list, tuple)) else [to_addrs]
            rec({"种类": "发邮件", "发件人": str(from_addr),
                 "收件": ";".join(map(str, tos)),
                 "主题": _subject(msg), "内容": str(msg)[:400]})

        def send_message(self, m, **kw):
            to = m.get("To", "")
            if isinstance(to, (list, tuple)):
                to = ";".join(map(str, to))
            atts = []
            try:
                for part in m.walk():
                    fn = part.get_filename()
                    if fn:
                        try:
                            fn = str(make_header(decode_header(fn)))
                        except Exception:
                            pass
                        atts.append(fn)
            except Exception:
                pass
            rec({"种类": "发邮件", "发件人": str(m.get("From", "")),
                 "收件": str(to), "主题": str(m.get("Subject", "")),
                 "附件": ";".join(atts), "内容": str(m)[:2000]})

        def quit(self):
            pass

    smtplib.SMTP = SMTP
    smtplib.SMTPException = Exception
    sys.modules["smtplib"] = smtplib

    # ---- requests / urllib --------------------------------------------
    class Resp:
        def __init__(self, data, status=200):
            self._d, self.status_code = data, status

        @property
        def text(self):
            return self._d if isinstance(self._d, str) else json.dumps(self._d, ensure_ascii=False)

        @property
        def content(self):
            return self.text.encode("utf-8")

        def json(self):
            return self._d

        def raise_for_status(self):
            pass

    def handle(method, url, kw):
        params = kw.get("params")
        if isinstance(params, dict) and params:
            from urllib.parse import urlencode
            q = urlencode({k: v for k, v in params.items() if v is not None})
            if q:
                url = str(url) + ("&" if "?" in str(url) else "?") + q
        for entry in mock_api:
            if str(url).startswith(entry["url_prefix"]):
                idx = entry.setdefault("_i", 0)
                body = entry["responses"][min(idx, len(entry["responses"]) - 1)]
                entry["_i"] = idx + 1
                if method == "POST":
                    payload = kw.get("json") or kw.get("data") or ""
                    rec({"种类": "发消息", "到": str(url),
                         "内容": json.dumps(payload, ensure_ascii=False, default=str)})
                else:
                    rec({"种类": "请求", "方法": method, "网址": str(url)})
                return Resp(body)
        rec({"种类": "请求", "方法": method, "网址": str(url), "未匹配": True})
        return Resp({"error": "mock 未配置该 URL"}, status=404)

    requests = types.ModuleType("requests")
    requests.exceptions = types.SimpleNamespace(RequestException=Exception)
    requests.get = lambda url, **kw: handle("GET", url, kw)
    requests.post = lambda url, **kw: handle("POST", url, kw)
    requests.put = lambda url, **kw: handle("PUT", url, kw)
    sys.modules["requests"] = requests

    import urllib.request as _u

    def urlopen(url, *a, **kw):
        u = getattr(url, "full_url", None) or str(url)
        r = handle("GET", u, {})
        return io.BytesIO(r.content)

    _u.urlopen = urlopen

    # urllib.error / urllib.parse 等子模块引用保持可用
    sys.modules.setdefault("urllib.error", __import__("urllib.error", fromlist=["*"]))
    sys.modules.setdefault("urllib.parse", __import__("urllib.parse", fromlist=["*"]))
