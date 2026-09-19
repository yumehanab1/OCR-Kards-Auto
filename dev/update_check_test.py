"""
update_check_test.py - "检测更新"的离线用例(不需要网络、不需要窗口)。

为什么这个模块值得单独一套用例
------------------------------
它是**唯一一个会去连外网**的地方,而"连不上"和"已是最新"在面板上长得一样
(都是弹一句话)。**把查不到说成已是最新,就是在骗人** —— 所以这里逐条考:
  · 版本号怎么比(★ "0.1.10" 与 "0.1.9" 的坑);
  · 每一条错误分支(断网/超时/404/403/坏 JSON/没有 tag)说的话对不对;
  · 附件挑得对不对;
  · **本地比远端新**时不假装"已是最新"。

★ 一条都不碰网络:`check(..., _fetch=假取数器)` 可以喂任意响应。
  想真去查一次加 `--live`(那才会连 GitHub,用来验接口形状有没有变)。
"""

from __future__ import annotations

import os
import sys
import urllib.error

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "src"))

import update_check as uc

ALLOK = True


def C(label, cond, extra=""):
    global ALLOK
    ALLOK &= bool(cond)
    print(f"  {'OK ' if cond else 'FAIL'} {label}" + (f"   {extra}" if extra else ""))


def fake(code=200, body=b"", exc=None):
    """造一个假取数器:_fetch(url, timeout) -> (code, body),或者抛 exc。"""
    def _f(url, timeout):
        if exc is not None:
            raise exc
        return code, body
    return _f


RELEASE = {
    "tag_name": "v0.9.9",
    "name": "KARDS AUTO v0.9.9",
    "body": "这次修了很多东西。" * 80,          # 故意超长,考截断
    "html_url": "https://github.com/yumehanab1/OCR-Kards-Auto/releases/tag/v0.9.9",
    "published_at": "2026-10-01T00:00:00Z",
    "assets": [
        {"name": "source.zip", "size": 100, "browser_download_url": "u1"},
        {"name": "kards-auto_v0.9.9_x86_64.zip", "size": 139000000,
         "browser_download_url": "u2"},
    ],
}

print("=" * 84)
print("① 版本号比较(★ 字符串比会在这里翻车)")
print("=" * 84)
C("parse_version('v0.1.10') -> (0,1,10)", uc.parse_version("v0.1.10") == (0, 1, 10))
C("parse_version('0.1.2') -> (0,1,2)", uc.parse_version("0.1.2") == (0, 1, 2))
C("parse_version('1.0') -> (1,0)", uc.parse_version("1.0") == (1, 0))
C("parse_version('乱码') -> 空(按不知道处理)", uc.parse_version("乱码") == ())
C("parse_version(None) -> 空", uc.parse_version(None) == ())
C("★ 0.1.10 比 0.1.9 新(字符串比会得出相反结论)",
  uc.is_newer("v0.1.10", "0.1.9") is True,
  f"(字符串比较会是 {'0.1.10' < '0.1.9'} —— 所以不能那么写)")
C("0.1.2 -> 0.1.3 是新", uc.is_newer("v0.1.3", "0.1.2") is True)
C("一样 -> 不是新", uc.is_newer("v0.1.2", "0.1.2") is False)
C("更旧 -> 不是新", uc.is_newer("v0.1.1", "0.1.2") is False)
C("★ 版本号没读懂 -> 一律 False(宁可漏报,不许瞎报)",
  uc.is_newer("beta", "0.1.2") is False and uc.is_newer("v0.2", "") is False)
C("0.2 与 0.2.0 视为相同", uc.is_newer("v0.2", "0.2.0") is False)

print()
print("=" * 84)
print("② 解析 Release:挑对附件、说明截断")
print("=" * 84)
rel = uc.parse_release(RELEASE)
C("版本号取到 0.9.9", rel["version"] == "0.9.9", rel["version"])
C("★ 优先挑 x86_64 那个 zip(不是在前的 source.zip)",
  rel["asset"] and rel["asset"]["name"] == "kards-auto_v0.9.9_x86_64.zip",
  (rel["asset"] or {}).get("name"))
C("说明截断了(400 字以内)", len(rel["notes"]) <= uc.NOTES_MAX + 20,
  f"{len(rel['notes'])} 字")
C("空 payload 不炸", uc.parse_release(None)["tag"] == "")
C("没有 zip 附件时 asset=None(不算错)", uc.parse_release(
    {"tag_name": "v1.0", "assets": [{"name": "x.7z"}]})["asset"] is None)

print()
print("=" * 84)
print("③ 正常路径:有新版本 / 已是最新 / 本地是开发版")
print("=" * 84)
import json as _json

body_new = _json.dumps(RELEASE).encode("utf-8")
r = uc.check("0.1.2", _fetch=fake(200, body_new))
C("查到(ok=True)且 has_update=True", r["ok"] and r["has_update"])
C("话里带上远端和本地两个版本号",
  "v0.9.9" in r["msg"] and "0.1.2" in r["msg"], r["msg"][:60])
C("附件大小换算成 MB", "MB" in r["msg"], r["msg"][-24:])
C("给了发布页地址", r["url"].startswith("https://github.com/"), r["url"])

same = dict(RELEASE, tag_name="v0.1.2", assets=[])
r2 = uc.check("0.1.2", _fetch=fake(200, _json.dumps(same).encode()))
C("一样时如实说'已是最新'", r2["ok"] and not r2["has_update"]
  and "已是最新" in r2["msg"], r2["msg"])
C("★ 本地更新时说'开发版',**不许**说'已是最新'",
  "开发版" in uc.check("1.0.0", _fetch=fake(200, body_new))["msg"],
  uc.check("1.0.0", _fetch=fake(200, body_new))["msg"])

print()
print("=" * 84)
print("④ 错误分支(★ 这一节是这个模块存在的理由:不许把'查不到'说成'已是最新')")
print("=" * 84)
cases = [
    ("断网/代理", fake(exc=urllib.error.URLError("getaddrinfo failed")), "连不上"),
    ("超时", fake(exc=TimeoutError()), "超时"),
    ("404 没发过 Release", fake(404, b"{}"), "404"),
    ("403 限流", fake(403, b"{}"), "请求太频繁"),
    ("500 服务端错", fake(500, b""), "GitHub 那边出错"),
    ("返回的不是 JSON(拦截页)", fake(200, b"<html>proxy</html>"), "不是 JSON"),
    ("返回里没有 tag_name", fake(200, b'{"name":"x"}'), "没有版本号"),
]
for label, f, must in cases:
    rr = uc.check("0.1.2", _fetch=f)
    ok = (rr["ok"] is False and rr["has_update"] is False and must in rr["msg"])
    C(f"{label}:ok=False、has_update=False、话里说清原因", ok, rr["msg"][:78])
C("★ 任何错误分支都不许出现'已是最新'",
  all("已是最新" not in uc.check("0.1.2", _fetch=f)["msg"]
      for _l, f, _m in cases))
C("★ 不认识的异常也不许把面板弄崩",
  uc.check("0.1.2", _fetch=fake(exc=RuntimeError("boom")))["ok"] is False)

print()
print("=" * 84)
print("⑤ 备用源(releases.atom):★ API 被限流时也得能报出新版本")
print("=" * 84)
FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Release notes from OCR-Kards-Auto</title>
  <entry>
    <title>KARDS AUTO v0.9.9</title>
    <link rel="alternate" type="text/html"
          href="https://github.com/yumehanab1/OCR-Kards-Auto/releases/tag/v0.9.9"/>
    <updated>2026-10-01T00:00:00Z</updated>
    <content type="html">&lt;p&gt;这次修了很多东西。&lt;/p&gt;</content>
  </entry>
</feed>""".encode("utf-8")
EMPTY_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>x</title></feed>""".encode("utf-8")

C("parse_feed 能从 link 里取出 tag(不从 title 取)",
  uc.parse_feed(FEED)["tag"] == "v0.9.9", uc.parse_feed(FEED)["tag"])
C("parse_feed 去掉 HTML 标签", "<p>" not in uc.parse_feed(FEED)["notes"],
  uc.parse_feed(FEED)["notes"])
C("parse_feed 空 feed(一条 release 都没有)-> 空 dict",
  uc.parse_feed(EMPTY_FEED) == {})
C("parse_feed 烂 XML 不抛异常", uc.parse_feed(b"not xml at all") == {})


def route(api_resp, feed_resp):
    """按 URL 分别应答的假取数器。"""
    def _f(url, timeout):
        return feed_resp if "releases.atom" in url else api_resp
    return _f


r403 = uc.check("0.1.2", _fetch=route((403, b"{}"), (200, FEED)))
C("★ API 403 时**退到备用源**,照样报出新版本",
  r403["ok"] and r403["has_update"] and r403["remote"] == "0.9.9", r403["msg"])
C("★ 结果里写清'走的是备用源'", r403["via"] == "feed" and "备用源" in r403["msg"])
C("备用源没有附件 -> asset=None,不许瞎编大小", r403["asset"] is None)

r404 = uc.check("0.1.2", _fetch=route((404, b"{}"), (200, EMPTY_FEED)))
C("两路都说没有 -> 如实报查不到", not r404["ok"] and "查不到" in r404["msg"],
  r404["msg"][:60])
C("★ 备用源成功时就不会再提'请求太频繁'",
  "太频繁" not in r403["msg"], r403["msg"][:50])

print()
print("=" * 84)
print("⑥ 更新源地址:空就用默认的 GitHub,填了就用填的")
print("=" * 84)
C("默认源指向本仓库",
  "yumehanab1/OCR-Kards-Auto" in uc.DEFAULT_API, uc.DEFAULT_API)
C("备用源也指向本仓库",
  "yumehanab1/OCR-Kards-Auto" in uc.DEFAULT_FEED, uc.DEFAULT_FEED)
seen = {}


def spy(url, timeout):
    seen["url"] = url
    return 200, body_new


uc.check("0.1.2", _fetch=spy)
C("update_url 为空 -> 用默认源", seen["url"] == uc.DEFAULT_API, seen["url"])
uc.check("0.1.2", "https://example.com/rel.json", _fetch=spy)
C("配了 update_url -> 用配的那个", seen["url"] == "https://example.com/rel.json")
C("结果里回报'实际用了哪个地址'(排错要用)", r["source"] == uc.DEFAULT_API)

if "--live" in sys.argv:
    print()
    print("=" * 84)
    print("⑦ --live:真去 GitHub 查一次(只有这一节连网)")
    print("=" * 84)
    live = uc.check("0.0.0")
    print(f"  msg : {live['msg']}")
    print(f"  ok={live['ok']} has_update={live['has_update']} "
          f"remote={live['remote']} via={live['via']} source={live['source']}")
    C("★ 真接口能查到(说明仓库有 Release、形状没变)", live["ok"], live["msg"][:70])

print()
print("=" * 84)
print("全部通过" if ALLOK else "存在失败项")
print("=" * 84)
sys.exit(0 if ALLOK else 1)
