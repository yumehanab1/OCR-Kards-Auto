"""Find DEFAULT_V and lang constants in karsenal page JS."""
import re
import requests

r = requests.get("https://karsenal.netlify.app/", headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
html = r.text
for pat in [
    r"DEFAULT_V\s*=\s*['\"][^'\"]+['\"]",
    r"version\s*=\s*['\"][^'\"]+['\"]",
    r"lang\s*=\s*['\"][^'\"]+['\"]",
    r"zh-Hans|zh-CN",
    r"v5\d",
]:
    found = re.findall(pat, html)
    print(pat, "->", sorted(set(found))[:8])
