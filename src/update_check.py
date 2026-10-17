"""
update_check.py - "检测更新":把远端发布信息和本地版本号比一下。

数据源
------
GitHub Releases(仓库是公开的,不用 token):
    GET https://api.github.com/repos/yumehanab1/OCR-Kards-Auto/releases/latest
返回里的 `tag_name` 就是版本,`body` 是更新说明,`assets[]` 是附件(我们发的是 zip
和同名 `.manifest.json` 清单)。
要换成别的源,把 `config/app_version.json` 的 `update_url` 填上就行 —— 那个字段
在 v0.1.0 就留好了,一直空着(当时项目还不是 git 仓库,机制没定;现在定了)。

三条纪律(和项目其它地方一致,不是随手写的)
------------------------------------------
① **不假装**。网络不通 / 超时 / 仓库没发过 Release / 返回的不是我们认识的 JSON ——
   一律如实说"查不到"并**带上原因**,绝不把它说成"已是最新"。这跟面板上
   `check_update()` 原来那句"更新源还没配置"是同一条规矩:宁可难看,不许骗人。
② 检测本身不安装。用户点击应用后，由 update_install 先校验变更文件，
   等面板退出再替换，失败恢复备份。
③ **只比对清单**。有清单时只下载小 JSON，并在本地计算 SHA-256；不会下载或解压 zip，
   也不会自动替换文件。清单缺失或格式不对时明确报告，绝不把未知说成无变更。
④ **纯逻辑可离线测**。版本比较、解析、每一条错误分支都不碰网络:
   `check(..., _fetch=假取数器)` 可以喂任意响应,见 `dev/update_check_test.py`。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from html.parser import HTMLParser
from urllib.parse import quote, urljoin, urlsplit
import urllib.error
import urllib.request
# ★ 放在**模块顶层**而不是函数里:面板要打成 onefile exe(见 build_gui.bat),
#   而打包工具是靠静态分析找依赖的 —— 藏在函数体里的 import 有漏掉的风险,
#   漏了的后果是"exe 里一切正常,只有点检测更新时崩"。
import xml.etree.ElementTree as ET

#: 默认更新源(没配 update_url 就用它)
DEFAULT_API = ("https://api.github.com/repos/yumehanab1/OCR-Kards-Auto"
               "/releases/latest")
#: ★★ 备用源:GitHub 的 releases atom 订阅。**这条不限流、不要 token**。
#:   为什么必须有它:实测第一次真去查就撞上 `HTTP 403`(未登录调用每小时只有 60 次,
#:   而且这个额度是**按 IP** 算的 —— 共用出口/公司网络的用户很容易直接用光)。
#:   只有 API 一条路的话,那类用户点"检测更新"永远只会看到"查不到"。
#:   Atom没有附件，取得tag后再读公开expanded_assets列表，补齐PC包/清单链接和公布的哈希；
#:   不猜测附件存在，不要求用户登录。先API、不行再退这条。
DEFAULT_FEED = "https://github.com/yumehanab1/OCR-Kards-Auto/releases.atom"
DEFAULT_ASSETS = "https://github.com/yumehanab1/OCR-Kards-Auto/releases/expanded_assets/"
DEFAULT_TAG_API = ("https://api.github.com/repos/yumehanab1/OCR-Kards-Auto"
                   "/releases/tags/")
RELEASE_VERSION_PATTERN = r'[0-9]+(?:\.[0-9]+)+(?:_beta)?'
#: 用不了 API 时,人能自己去看的地方
RELEASES_PAGE = "https://github.com/yumehanab1/OCR-Kards-Auto/releases"
#: 超时给短一点:面板上点一下按钮,卡 30 秒是不可接受的
TIMEOUT = 6.0
#: 更新说明最多带回来多少字(面板是 toast,长了没人看;全文在发布页)
NOTES_MAX = 400


def parse_version(text) -> tuple:
    """
    "v0.1.10" -> (0, 1, 10)。认不出来就返回 **空元组**(调用方按"不知道"处理)。

    ★ 为什么要退回元组比较而不是字符串比较:`"0.1.10" < "0.1.9"` 在字符串下是 **True**
      (逐字符比,'1'<'9'),那样第 10 个补丁会被判成"比第 9 个旧",更新提示永远不出现。
    """
    if not text:
        return ()
    s = str(text).strip().lstrip("vV")
    parts = re.findall(r"\d+", s)
    if not parts:
        return ()
    return tuple(int(p) for p in parts)


def is_newer(remote, local) -> bool:
    """
    远端比本地新吗?**认不出任何一边就返回 False** —— 宁可漏报一次更新,
    也不许在"版本号没读懂"的时候弹一句"有新版本"骗人。
    """
    r, l = parse_version(remote), parse_version(local)
    if not r or not l:
        return False
    n = max(len(r), len(l))
    r = r + (0,) * (n - len(r))
    l = l + (0,) * (n - len(l))
    if r != l:
        return r > l
    # Keep parse_version's public numeric tuple unchanged. A beta is older
    # than the stable release with the same numeric core.
    return _is_beta(local) and not _is_beta(remote)


def _is_beta(version) -> bool:
    return bool(re.fullmatch(r'[vV]?[0-9]+(?:\.[0-9]+)+_beta',
                             str(version or '').strip()))


def _asset_entries(assets):
    """Return only a list-like asset collection; malformed JSON is empty."""
    if isinstance(assets, (list, tuple)):
        return assets
    return ()


def pick_asset(assets) -> dict | None:
    """
    从附件里挑"该下的那个":优先 `*x86_64*.zip`(我们的命名是
    `kards-auto_v<版本>_x86_64.zip`),退一步随便一个 zip。

    ★ 挑不到不算错:有的 Release 只写说明、不发附件,面板仍然可以给发布页地址。
    """
    # GitHub normally returns a list of objects, but keep malformed entries
    # from making the update panel crash if a proxy or custom update source
    # injects a scalar/list item into ``assets``.
    zips = [a for a in _asset_entries(assets)
            if isinstance(a, dict)
            and str(a.get("name", "")).lower().endswith(".zip")]
    if not zips:
        return None
    for a in zips:
        if "x86_64" in str(a.get("name", "")).lower():
            return a
    return zips[0]


def pick_manifest_asset(assets) -> dict | None:
    """Pick the small hash manifest used for file-level update checks."""
    manifests = [a for a in _asset_entries(assets)
                 if isinstance(a, dict)
                 if str(a.get("name", "")).lower().endswith(".manifest.json")]
    if not manifests:
        return None
    for a in manifests:
        if "x86_64" in str(a.get("name", "")).lower():
            return a
    return manifests[0]


def parse_release(payload) -> dict:
    """
    把 GitHub 那条 release JSON 变成我们要的几个字段;缺东西就留空,不抛异常。

    返回 {tag, version, name, notes, url, published_at, asset, manifest_asset}
    """
    p = payload if isinstance(payload, dict) else {}
    tag = str(p.get("tag_name") or "").strip()
    body = str(p.get("body") or "").strip()
    if len(body) > NOTES_MAX:
        body = body[:NOTES_MAX].rstrip() + " …(全文见发布页)"
    return {
        "tag": tag,
        "version": tag.lstrip("vV"),
        "name": str(p.get("name") or "").strip(),
        "notes": body,
        "url": str(p.get("html_url") or "").strip() or RELEASES_PAGE,
        "published_at": str(p.get("published_at") or "").strip(),
        "prerelease": bool(p.get("prerelease")) or _is_beta(tag),
        "asset": pick_asset(p.get("assets")),
        "manifest_asset": pick_manifest_asset(p.get("assets")),
    }


def _manifest_files(payload) -> dict:
    """Normalize a manifest to ``{relative_path: {sha256, size}}``."""
    if not isinstance(payload, dict) or not isinstance(payload.get("files"), dict):
        return {}
    out = {}
    for raw_rel, item in payload["files"].items():
        # The manifest is downloaded from a release, so treat its paths as
        # untrusted input.  Reject absolute paths and traversal segments
        # instead of allowing a malformed manifest to make us hash files
        # outside the installed package.  Empty/dot segments are rejected as
        # well: silently normalizing them could make two entries collide.
        raw_rel = str(raw_rel)
        if (not raw_rel or raw_rel.startswith(("/", "\\"))
                or re.match(r"^[A-Za-z]:", raw_rel)):
            continue
        parts = raw_rel.replace("\\", "/").split("/")
        if any(part in ("", ".", "..") for part in parts):
            continue
        rel = "/".join(parts)
        if not isinstance(item, dict):
            continue
        digest = str(item.get("sha256") or "").lower()
        if re.fullmatch(r"[0-9a-f]{64}", digest):
            out[rel] = {"sha256": digest, "size": item.get("size")}
    return out


def compare_manifest(root: str, manifest=None, manifest_url: str | None = None,
                     timeout: float = TIMEOUT, _fetch=None) -> dict:
    """Compare installed files with a remote manifest without downloading zip."""
    if manifest is None:
        if not manifest_url:
            return {"ok": False, "changed": [], "missing": [], "same": 0,
                    "remote_files": 0, "msg": "该 Release 没有文件清单附件"}
        fetch = _fetch or _http_get
        try:
            code, raw = fetch(manifest_url, timeout)
        except Exception as e:
            return {"ok": False, "changed": [], "missing": [], "same": 0,
                    "remote_files": 0,
                    "msg": f"文件清单下载失败({type(e).__name__}: {e})"}
        if code != 200:
            return {"ok": False, "changed": [], "missing": [], "same": 0,
                    "remote_files": 0, "msg": f"文件清单返回 HTTP {code}"}
        try:
            manifest = json.loads(raw.decode("utf-8", "replace"))
        except Exception:
            return {"ok": False, "changed": [], "missing": [], "same": 0,
                    "remote_files": 0, "msg": "文件清单不是有效 JSON"}
    files = _manifest_files(manifest)
    if not files:
        return {"ok": False, "changed": [], "missing": [], "same": 0,
                "remote_files": 0, "msg": "文件清单为空或格式不兼容"}

    changed, missing, same = [], [], 0
    root = os.path.abspath(root)
    for rel, expected in files.items():
        path = os.path.join(root, *rel.split("/"))
        if not os.path.isfile(path):
            missing.append(rel)
            continue
        h = hashlib.sha256()
        try:
            with open(path, "rb") as f:
                for block in iter(lambda: f.read(1024 * 1024), b""):
                    h.update(block)
        except OSError:
            missing.append(rel)
            continue
        if h.hexdigest().lower() == expected["sha256"]:
            same += 1
        else:
            changed.append(rel)
    return {"ok": True, "changed": changed, "missing": missing, "same": same,
            "remote_files": len(files),
            "msg": (f"文件清单比对完成：{len(changed)} 个变更、{len(missing)} 个缺失、"
                    f"{same} 个一致")}


def parse_feed(xml_bytes) -> dict:
    """
    解析 GitHub 的 `releases.atom`(**备用源**)。缺东西就留空,不抛异常。

    ★ 版本号从 `<link href=".../releases/tag/v0.1.2">` 里取,不从 `<title>` 取 ——
      GitHub 的 title 是**发布标题**(比如 "KARDS AUTO v0.1.2"),用户填什么都可能,
      而 tag 是机器填的、形状稳定。title 只当兜底(用正则捞一个 x.y.z)。
    """
    try:
        root = ET.fromstring(xml_bytes)
    except Exception:
        return {}
    ns = {"a": "http://www.w3.org/2005/Atom"}
    # Atom does not expose GitHub's prerelease boolean. Only a complete
    # numeric stable tag may enter the default stable-update fallback.
    for entry in root.findall("a:entry", ns):
        release = _parse_feed_entry(entry, ns)
        if re.fullmatch(r'[vV]?[0-9]+(?:\.[0-9]+)+', release.get('tag', '')):
            return release
    return {}


def _parse_feed_entry(entry, ns):
    href = ""
    link = entry.find("a:link", ns)
    if link is not None:
        href = str(link.get("href") or "")
    title = (entry.findtext("a:title", default="", namespaces=ns) or "").strip()
    tag = href.rsplit("/", 1)[-1] if "/releases/tag/" in href else ""
    if not tag:
        # Include suffixes so a title-only beta cannot be truncated into a
        # stable version before the caller applies its stable-tag filter.
        m = re.search(r"[vV]?\d+(?:\.\d+)+(?:[._-][A-Za-z0-9][A-Za-z0-9._-]*)?", title)
        tag = m.group(0) if m else ""
    notes = re.sub(r"<[^>]+>", " ", entry.findtext("a:content", default="",
                                                   namespaces=ns) or "")
    notes = re.sub(r"\s+", " ", notes).strip()
    if len(notes) > NOTES_MAX:
        notes = notes[:NOTES_MAX].rstrip() + " …(全文见发布页)"
    return {
        "tag": tag,
        "version": tag.lstrip("vV"),
        "name": title,
        "notes": notes,
        "url": href or RELEASES_PAGE,
        "published_at": (entry.findtext("a:updated", default="", namespaces=ns)
                         or entry.findtext("a:published", default="",
                                           namespaces=ns) or ""),
        "asset": None,                   # 之后由公开附件列表补齐
        "manifest_asset": None,
    }


class _ReleaseLinks(HTMLParser):
    """Read GitHub's attachment links and optional published digests."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.digests = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'a' and attrs.get('href'):
            self.links.append(attrs['href'])
        if tag == 'clipboard-copy':
            label = attrs.get('aria-label', '')
            prefix = 'Copy to clipboard digest for '
            digest = attrs.get('value', '')
            if label.startswith(prefix) and re.fullmatch(r'sha256:[0-9a-f]{64}', digest):
                self.digests[label[len(prefix):]] = digest


def parse_release_assets(raw, tag):
    """Accept only the paired PC attachments actually linked for this tag."""
    if not re.fullmatch(r'[vV]?' + RELEASE_VERSION_PATTERN, tag or ''):
        return {}
    parser = _ReleaseLinks()
    parser.feed(raw.decode('utf-8', 'replace'))
    stem = 'kards-auto_v' + tag.lstrip('vV') + '_x86_64'
    expected = {stem + '.zip': 'asset', stem + '.manifest.json': 'manifest_asset'}
    prefix = '/yumehanab1/OCR-Kards-Auto/releases/download/' + quote(tag, safe='') + '/'
    result = {}
    for href in parser.links:
        url = urljoin('https://github.com', href)
        parts = urlsplit(url)
        if (parts.scheme != 'https' or parts.netloc != 'github.com'
                or parts.query or parts.fragment or not parts.path.startswith(prefix)):
            continue
        name = parts.path[len(prefix):]
        if name not in expected:
            continue
        asset = dict(name=name, browser_download_url=url)
        if name in parser.digests:
            asset['digest'] = parser.digests[name]
        result[expected[name]] = asset
    return result


def _feed_assets(rel, fetch, head, timeout):
    """The feed has no assets; fetch the public HTML list without API quota."""
    tag = rel.get('tag', '')
    if not re.fullmatch(r'[vV]?' + RELEASE_VERSION_PATTERN, tag):
        return dict(rel, asset_error='备用源版本号无效，无法读取附件列表')
    url = DEFAULT_ASSETS + quote(tag, safe='')
    try:
        code, raw = fetch(url, timeout)
        if code != 200:
            return dict(rel, asset_error=f'发布页附件列表读取失败(HTTP {code})')
        assets = parse_release_assets(raw, tag)
        if assets.get('asset'):
            size = head(assets['asset']['browser_download_url'], timeout)
            if type(size) is not int or not 0 < size <= 2*1024*1024*1024:
                raise ValueError('PC附件未返回有效字节大小')
            assets['asset']['size'] = size
    except Exception as error:
        return dict(rel, asset_error=f'发布页附件列表读取失败({type(error).__name__}: {error})')
    error = '' if assets.get('manifest_asset') and assets.get('asset') else '发布页附件列表未找到配套PC包和文件清单'
    return dict(rel, **assets, asset_source=url, asset_error=error)


def _http_head(url, timeout):
    """Read exact ZIP length without transferring the archive body."""
    request = urllib.request.Request(url, method='HEAD', headers={
        'User-Agent': 'kards-auto-update-check', 'Accept-Encoding': 'identity'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return int(response.headers.get('Content-Length', '0'))


def _http_get(url: str, timeout: float):
    """
    默认取数器:返回 (状态码, 正文 bytes)。**HTTP 错误也返回状态码,不抛异常** ——
    因为 404/403 都是"要如实讲给用户听"的结论,不是崩溃。
    只有"连不上/超时"这类才抛出来(由 check 转成人话)。
    """
    req = urllib.request.Request(url, headers={
        # GitHub API 不带 User-Agent 直接 403,这条不能省
        "User-Agent": "kards-auto-update-check",
        "Accept": "application/vnd.github+json",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.getcode(), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, (e.read() or b"")


def _why_http(code: int, api_url: str) -> str:
    """把 HTTP 状态码说成人话(每条都要能指导下一步动作)。不带"查不到:"前缀,
    那一层由 `check()` 统一加(不然会出现"查不到:查不到:…")。"""
    if code == 404:
        return ("这个仓库还没有发布过 Release(HTTP 404)。"
                f"发布页:{RELEASES_PAGE}")
    if code in (403, 429):
        return ("GitHub 说请求太频繁(HTTP %d)。未登录的调用每小时只有 60 次、"
                "而且按 IP 算,过一会儿再点。" % code)
    if code >= 500:
        return f"GitHub 那边出错了(HTTP {code}),过一会儿再试"
    return f"更新源返回 HTTP {code}"


def check(local_version: str, api_url: str | None = None,
          timeout: float = TIMEOUT, _fetch=None, _head=None) -> dict:
    """
    查一次更新。**永远返回同一个形状**,面板照着 `msg` 显示就行:

        {"ok": 查询本身成功了吗, "has_update": 远端是否更新,
         "local": ..., "remote": ..., "msg": 一句人话,
         "url": 发布页, "asset": 附件信息或 None,
         "manifest_asset": 文件清单附件或 None, "notes": 更新说明,
         "source": 实际用的地址}

    `ok` 与 `has_update` 是**两件事**:查不到(ok=False)不等于"已是最新";
    面板必须分开说,否则就是在骗人 —— 这正是这个模块存在的理由。
    """
    api = (api_url or "").strip() or DEFAULT_API
    local = str(local_version or "0.0.0")
    # Only an exact official beta-tag API is allowed this quota-free
    # fallback. Custom sources never acquire default-repository assets.
    beta_source = re.fullmatch(re.escape(DEFAULT_TAG_API)
                               + r'([vV]?[0-9]+(?:\.[0-9]+)+_beta)', api)
    beta_tag = beta_source.group(1) if beta_source else None

    fetch = _fetch or _http_get
    base = {"ok": False, "has_update": False, "local": local, "remote": None,
            "url": RELEASES_PAGE, "asset": None, "manifest_asset": None,
            "notes": "", "source": api,
            "via": "api", "msg": ""}

    # ---- 第一路:API(信息最全:附件名 + 大小 + 说明) ----
    rel, why = None, ""
    try:
        code, raw = fetch(api, timeout)
        if code == 200:
            try:
                payload = json.loads(raw.decode("utf-8", "replace"))
            except Exception:
                why = "更新源返回的不是 JSON(可能是代理/拦截页)"
            else:
                rel = parse_release(payload)
                if not rel["tag"]:
                    rel, why = None, "更新源返回里没有版本号(tag_name),大概不是 Release 接口"
                elif api == DEFAULT_API and rel.get('prerelease'):
                    rel, why = None, "默认更新源返回预发布版本，正在查找正式版本"
                elif beta_tag and rel['tag'] != beta_tag:
                    rel, why = None, "更新源返回的标签与指定 beta 标签不一致"
        else:
            why = _why_http(code, api)
    except urllib.error.URLError as e:                  # 断网/代理/DNS
        why = f"连不上 GitHub({e.reason})"
    except TimeoutError:
        why = f"连 GitHub 超时({timeout:.0f} 秒)"
    except Exception as e:                              # 兜底:绝不让面板崩
        why = f"请求出错({type(e).__name__}: {e})"

    # ---- 第二路:官方标签/Atom版本 + 公开附件列表(不消耗API配额) ----
    #   ★ 正式默认源才使用Atom；已限定本仓库的beta标签直接核实该标签附件。
    #     其它自定义update_url不借用默认仓库的版本或附件。
    #   ★ 注意 API 在 `api.github.com`、feed 在 `github.com` —— **两个域名**,
    #     不能拿 API 的地址去拼 `.atom`(第一版就是这么写的,于是备用源永远试不到)。
    via = "api"
    if rel is None and beta_tag:
        fallback = _feed_assets(parse_release({
            'tag_name': beta_tag, 'prerelease': True,
            'html_url': RELEASES_PAGE + '/tag/' + quote(beta_tag, safe=''),
        }), fetch, _head or _http_head, timeout)
        if (not fallback.get('asset_error') and fallback.get('asset')
                and fallback.get('manifest_asset')):
            rel, via = fallback, 'tag_assets'
        else:
            why += '；' + fallback.get('asset_error', '指定 beta 的配套附件不可用')
    if rel is None and api == DEFAULT_API:
        try:
            code2, raw2 = fetch(DEFAULT_FEED, timeout)
            if code2 == 200:
                rel2 = parse_feed(raw2)
                if rel2.get("tag"):
                    rel, via = _feed_assets(rel2, fetch, _head or _http_head, timeout), "feed"
        except Exception:
            pass                                        # 备用也失败 -> 保留第一路的 why

    if rel is None:
        # ★ 两路都没成:**如实说**,并给一条"能自己去看"的路
        return dict(base, msg=f"查不到:{why}。可以直接开 {RELEASES_PAGE}")

    out = dict(base, ok=True, remote=rel["version"] or rel["tag"],
               url=rel["url"], asset=rel["asset"],
               manifest_asset=rel.get("manifest_asset"),
               notes=rel["notes"], via=via, asset_error=rel.get('asset_error', ''),
               asset_source=rel.get('asset_source', ''), api_error=why if via != 'api' else '')
    tail = '' if via == 'api' else ('(备用源)' if not out['asset_error'] else '(备用源;附件信息未取全)')
    if is_newer(rel["tag"], local):
        size = ""
        if rel["asset"] and rel["asset"].get("size"):
            size = f",包 {rel['asset']['size'] / 1048576:.1f} MB"
        return dict(out, has_update=True,
                    msg=f"发现新版本 {rel['tag']}(本地 v{local}){size}{tail} —— "
                        f"点一下这里打开发布页下载")
    if is_newer(local, rel["tag"]):
        # 本地比远端还新 = 开发版。**如实说**,不要假装"已是最新"
        return dict(out, msg=f"本地 v{local} 比远端 {rel['tag']} 还新"
                             f"(开发版?){tail}。发布页:{rel['url']}")
    return dict(out, msg=f"已是最新(v{local}){tail}")
